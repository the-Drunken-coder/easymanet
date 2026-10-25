"""Cross-platform disk listing and flash safety."""

import hashlib
import os
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..platform import is_linux, is_macos
from . import linux, macos
from ._common import (
    OVERLAY_WIPE_BLOCK_MIB,
    OVERLAY_WIPE_BLOCKS,
    DiskInfo,
)


def _is_block_device(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        return stat.S_ISBLK(os.stat(path).st_mode)
    except OSError:
        return False


@dataclass(frozen=True)
class DeviceIdentity:
    """Identity of one OS device node and its current attachment instance."""

    path: str
    filesystem_device: int
    inode: int
    raw_device: int
    changed_ns: int
    created_ns: int
    generation: int
    diskseq: str = ""


def flash_resource_key(device: str) -> str:
    canonical = os.path.realpath(device)
    if is_macos():
        whole_disk = macos._canonical_macos_whole_disk(canonical)
        if whole_disk is None:
            raise ValueError("Flash admission requires a whole physical disk.")
        return f"darwin:{whole_disk}"
    if is_linux():
        device_stat = os.stat(canonical)
        if not stat.S_ISBLK(device_stat.st_mode):
            raise ValueError("Flash admission requires a block device.")
        return f"linux:{os.major(device_stat.st_rdev)}:{os.minor(device_stat.st_rdev)}"
    raise ValueError("Flash admission requires macOS or Linux.")


def _flash_admission_path(device: str) -> str:
    try:
        resource = flash_resource_key(device)
    except OSError as exc:
        raise ValueError(f"Could not identify physical flash resource {device}: {exc}") from exc
    digest = hashlib.sha256(resource.encode()).hexdigest()
    return f"/tmp/easymanet-media-{digest}.lock"


def assert_flash_admission(device: str, admission_fd: int) -> None:
    try:
        current = os.stat(_flash_admission_path(device), follow_symlinks=False)
        held = os.fstat(admission_fd)
    except OSError as exc:
        raise ValueError(f"Could not revalidate flash admission for {device}: {exc}") from exc
    if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
        raise ValueError("Physical device changed after flash admission; refusing to write.")


@contextmanager
def flash_device_guard(device: str) -> Iterator[int]:
    """Hold one machine-wide writer slot until every inherited descriptor closes."""
    import fcntl

    lock_path = _flash_admission_path(device)
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    created = False
    try:
        try:
            fd = os.open(lock_path, flags | os.O_CREAT | os.O_EXCL, 0o666)
            created = True
        except FileExistsError:
            # O_CREAT on another uid's existing file is denied by Linux protected_regular.
            fd = os.open(lock_path, flags)
    except OSError as exc:
        raise ValueError(f"Could not open shared flash admission for {device}: {exc}") from exc
    try:
        try:
            if created:
                os.fchmod(fd, 0o666)
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise ValueError("Flash admission file must be a regular file with one link.")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError(f"Another EasyMANET process is flashing {device}.") from exc
            current = os.stat(lock_path, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("Flash admission file changed while acquiring it.")
        except OSError as exc:
            raise ValueError(f"Could not establish shared flash admission for {device}: {exc}") from exc
        yield fd
    finally:
        # Do not unlink or explicitly unlock. A surviving dd child keeps this inode locked.
        os.close(fd)


def capture_device_identity(path: str) -> DeviceIdentity:
    return _identity_from_stat(path, os.stat(path))


def assert_device_identity(expected: DeviceIdentity) -> None:
    try:
        actual = capture_device_identity(expected.path)
    except OSError as exc:
        raise ValueError(
            f"Device identity could not be revalidated for {expected.path}."
        ) from exc
    if _stable_device_identity(actual) != _stable_device_identity(expected):
        raise ValueError(
            f"Device identity changed for {expected.path}; refusing to write."
        )


def open_device_for_write(
    expected: DeviceIdentity,
    *,
    companions: Tuple[DeviceIdentity, ...] = (),
) -> int:
    """Open the expected node once and prove the path still names that object."""
    identities = (expected, *companions)
    for identity in identities:
        assert_device_identity(identity)

    flags = os.O_WRONLY | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(expected.path, flags)
    try:
        if _identity_from_stat(expected.path, os.fstat(fd)) != expected:
            raise ValueError(
                f"Opened device does not match the checked identity for {expected.path}."
            )
        for identity in identities:
            assert_device_identity(identity)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _stable_device_identity(identity: DeviceIdentity) -> tuple[object, ...]:
    return (
        identity.path,
        identity.filesystem_device,
        identity.inode,
        identity.raw_device,
        identity.created_ns,
        identity.generation,
        identity.diskseq,
    )


def _identity_from_stat(path: str, result: os.stat_result) -> DeviceIdentity:
    diskseq = _linux_diskseq(result)
    if (
        sys.platform.startswith("linux")
        and stat.S_ISBLK(result.st_mode)
        and not diskseq
    ):
        raise OSError(
            f"Could not read a stable Linux disk sequence for {path}; "
            "safe flashing requires Linux 5.14 or newer."
        )
    return DeviceIdentity(
        path=path,
        filesystem_device=result.st_dev,
        inode=result.st_ino,
        raw_device=result.st_rdev,
        changed_ns=result.st_ctime_ns,
        created_ns=int(getattr(result, "st_birthtime", 0) * 1_000_000_000),
        generation=getattr(result, "st_gen", 0),
        diskseq=diskseq,
    )


def _linux_diskseq(result: os.stat_result) -> str:
    if not sys.platform.startswith("linux") or not stat.S_ISBLK(result.st_mode):
        return ""
    major = os.major(result.st_rdev)
    minor = os.minor(result.st_rdev)
    try:
        with open(
            f"/sys/dev/block/{major}:{minor}/diskseq",
            encoding="utf-8",
        ) as handle:
            return handle.read().strip()
    except OSError:
        return ""


def list_disks(include_all: bool = False) -> List[DiskInfo]:
    if is_macos():
        disks = macos.list_disks_macos(include_all=include_all)
    elif is_linux():
        disks = linux.list_disks_linux(include_all=include_all)
    else:
        return []
    return sorted(disks, key=lambda d: d.size_bytes, reverse=True)


def lookup_device(
    device: str,
    default_disks: Optional[List[DiskInfo]] = None,
) -> Optional[DiskInfo]:
    if is_macos():
        disk = macos.lookup_device_macos(device)
    elif is_linux():
        disk = linux.lookup_device_linux(device)
    else:
        disk = None

    if disk is None:
        return None

    disks = (
        default_disks
        if default_disks is not None
        else list_disks(include_all=False)
    )
    if not any(d.device == device for d in disks):
        disk.not_in_default_list = True
    return disk


def assert_flash_allowed(device: str, force: bool = False) -> DiskInfo:
    if not _is_block_device(device):
        raise ValueError(
            f"Device {device} does not exist or is not a block device."
        )

    disk = lookup_device(device)
    if disk is None:
        raise ValueError(
            f"Could not read disk information for {device}."
        )

    if disk.safety_error:
        raise ValueError(disk.safety_error)

    if disk.is_system:
        raise ValueError(f"Refusing to flash {device}: system disk.")

    blocking = disk.blocking_warnings
    if blocking and not force:
        lines = "\n".join(f"  {w}" for w in blocking)
        raise ValueError(
            f"Refusing to flash {device}:\n{lines}\n"
            f"  Model: {disk.model}\n"
            f"  Size: {disk.size_human}\n"
            f"  Mounted: {', '.join(disk.mounted) if disk.mounted else 'none'}\n"
            f"Use --force to override."
        )
    return disk


def unmount_disk(device: str, *, admission_fd: int | None = None) -> None:
    if is_macos():
        macos.unmount_disk_macos(device, admission_fd=admission_fd)
    elif is_linux():
        linux.unmount_disk_linux(device, admission_fd=admission_fd)


def get_partition2_wipe_range(device: str) -> Optional[Tuple[int, int]]:
    """Return (start_byte_offset, wipe_bytes) for partition 2 stale-overlay tail wipe."""
    max_wipe = OVERLAY_WIPE_BLOCK_MIB * OVERLAY_WIPE_BLOCKS * 1024 * 1024

    if is_linux():
        return linux._linux_partition2_wipe_range(device, max_wipe)
    if is_macos():
        return macos._macos_partition2_wipe_range(device, max_wipe)
    return None


def eject_disk(device: str, *, admission_fd: int | None = None) -> None:
    if is_macos():
        result = subprocess.run(
            ["diskutil", "eject", device],
            capture_output=True,
            text=True,
            timeout=30,
            pass_fds=(admission_fd,) if admission_fd is not None else (),
        )
    elif is_linux():
        result = subprocess.run(
            ["eject", device],
            capture_output=True,
            text=True,
            timeout=30,
            pass_fds=(admission_fd,) if admission_fd is not None else (),
        )
    else:
        return
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Failed to eject {device}{suffix}")
