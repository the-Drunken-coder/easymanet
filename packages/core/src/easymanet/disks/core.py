"""Cross-platform disk listing and flash safety."""

import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ._common import (
    OVERLAY_WIPE_BLOCK_MIB,
    OVERLAY_WIPE_BLOCKS,
    DiskInfo,
)


def _disks_module():
    return sys.modules[__package__]


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


def capture_device_identity(path: str) -> DeviceIdentity:
    return _identity_from_stat(path, os.stat(path))


def assert_device_identity(expected: DeviceIdentity) -> None:
    try:
        actual = capture_device_identity(expected.path)
    except OSError as exc:
        raise ValueError(
            f"Device identity could not be revalidated for {expected.path}."
        ) from exc
    if actual != expected:
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


def _identity_from_stat(path: str, result: os.stat_result) -> DeviceIdentity:
    diskseq = _linux_diskseq(result)
    if (
        sys.platform.startswith("linux")
        and stat.S_ISBLK(result.st_mode)
        and not diskseq
    ):
        raise OSError(f"Could not read a stable Linux disk sequence for {path}.")
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
    disks_mod = _disks_module()
    if disks_mod.is_macos():
        disks = disks_mod.list_disks_macos(include_all=include_all)
    elif disks_mod.is_linux():
        disks = disks_mod.list_disks_linux(include_all=include_all)
    else:
        return []
    return sorted(disks, key=lambda d: d.size_bytes, reverse=True)


def lookup_device(
    device: str,
    default_disks: Optional[List[DiskInfo]] = None,
) -> Optional[DiskInfo]:
    disks_mod = _disks_module()
    if disks_mod.is_macos():
        disk = disks_mod.lookup_device_macos(device)
    elif disks_mod.is_linux():
        disk = disks_mod.lookup_device_linux(device)
    else:
        disk = None

    if disk is None:
        return None

    disks = (
        default_disks
        if default_disks is not None
        else disks_mod.list_disks(include_all=False)
    )
    if not any(d.device == device for d in disks):
        disk.not_in_default_list = True
    return disk


def find_disk(device: str) -> Optional[DiskInfo]:
    disks = list_disks()
    for disk in disks:
        if disk.device == device:
            return disk
    return lookup_device(device, default_disks=disks)


def assert_flash_allowed(device: str, force: bool = False) -> DiskInfo:
    if not _disks_module()._is_block_device(device):
        raise ValueError(
            f"Device {device} does not exist or is not a block device."
        )

    disk = _disks_module().lookup_device(device)
    if disk is None:
        raise ValueError(
            f"Could not read disk information for {device}."
        )

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


def unmount_disk(device: str) -> None:
    disks_mod = _disks_module()
    if disks_mod.is_macos():
        disks_mod.unmount_disk_macos(device)
    elif disks_mod.is_linux():
        disks_mod.unmount_disk_linux(device)


def get_partition2_wipe_range(device: str) -> Optional[Tuple[int, int]]:
    """Return (start_byte_offset, wipe_bytes) for partition 2 stale-overlay tail wipe."""
    max_wipe = OVERLAY_WIPE_BLOCK_MIB * OVERLAY_WIPE_BLOCKS * 1024 * 1024
    disks_mod = _disks_module()

    if disks_mod.is_linux():
        return disks_mod._linux_partition2_wipe_range(device, max_wipe)
    if disks_mod.is_macos():
        return disks_mod._macos_partition2_wipe_range(device, max_wipe)
    return None


def eject_disk(device: str) -> None:
    disks_mod = _disks_module()
    if disks_mod.is_macos():
        result = subprocess.run(
            ["diskutil", "eject", device],
            capture_output=True,
            text=True,
            timeout=30,
        )
    elif disks_mod.is_linux():
        result = subprocess.run(
            ["eject", device],
            capture_output=True,
            text=True,
            timeout=30,
        )
    else:
        return
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Failed to eject {device}{suffix}")
