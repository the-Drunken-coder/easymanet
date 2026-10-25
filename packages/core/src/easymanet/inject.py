"""Write node-specific provisioning payloads to the boot partition."""

import json
import os
import plistlib
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .disks import DeviceIdentity, assert_device_identity
from .manifest import Manifest
from .platform import is_linux, is_macos
from .provision import ProvisionAttestation
from .render import render

ROOT_BLOCK_DEVICE_PATTERN = re.compile(r"root=(/dev/[^\s]+)")

# diskutil list -plist often omits FilesystemType; Content is set on current macOS.
_MACOS_FAT_CONTENTS = frozenset(
    {
        "Windows_FAT_32",
        "EFI",
        "DOS_FAT_12",
        "DOS_FAT_16",
        "DOS_FAT_32",
    }
)
_BOOT_FILESYSTEMS = frozenset({"msdos", "vfat", "fat32", "exfat"})

_SUBPROCESS_ERRORS = (
    subprocess.CalledProcessError,
    subprocess.TimeoutExpired,
    FileNotFoundError,
)
_BOOT_PARTITION_PARSE_ERRORS = (
    *_SUBPROCESS_ERRORS,
    OSError,
    ValueError,
    UnicodeDecodeError,
    plistlib.InvalidFileException,
)


def _debug_note(message: str) -> None:
    print(f"easymanet: {message}", file=sys.stderr)


class InjectError(Exception):
    pass


@dataclass(frozen=True)
class _BootMount:
    device_identity: DeviceIdentity
    partition: str
    mount_point: str
    mounted_here: bool

    def open_root(self) -> int:
        _assert_device_identity(self.device_identity)
        _check_boot_mount(self)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(self.mount_point, flags)
        try:
            filesystem_device = os.stat(self.partition).st_rdev
            if os.fstat(fd).st_dev != filesystem_device:
                raise InjectError(
                    "Boot destination is not the selected partition's filesystem"
                )
            _check_boot_mount(self)
            _assert_device_identity(self.device_identity)
        except BaseException:
            os.close(fd)
            raise
        return fd


def inject(
    device: str,
    manifest: Manifest,
    node_name: str,
    dry_run: bool = False,
    *,
    device_identity: DeviceIdentity,
    ssh_enabled: Optional[bool] = None,
    api_wan_enabled: Optional[bool] = None,
    attestation: ProvisionAttestation | None = None,
    admission_fd: int | None = None,
) -> List[Tuple[str, bool]]:
    if dry_run:
        render(
            manifest,
            node_name,
            ssh_enabled=ssh_enabled,
            api_wan_enabled=api_wan_enabled,
            attestation=attestation,
        )
        return [
            ("/boot/easymanet/provision.json", True),
            ("Base image must already include EasyMANET first-boot hooks", True),
        ]

    if device != device_identity.path:
        raise InjectError(
            f"Device path {device} does not match checked identity path "
            f"{device_identity.path}."
        )
    _assert_device_identity(device_identity)
    boot_mount = _mount_boot_partition(device_identity, admission_fd=admission_fd)
    results: List[Tuple[str, bool]] | None = None
    stage_error: BaseException | None = None
    try:
        _assert_device_identity(device_identity)
        boot_fd = boot_mount.open_root()
        try:
            results = _stage_boot_payload(
                boot_fd,
                manifest,
                node_name,
                ssh_enabled=ssh_enabled,
                api_wan_enabled=api_wan_enabled,
                attestation=attestation,
            )
        finally:
            os.close(boot_fd)
        _assert_device_identity(device_identity)
    except OSError as exc:
        stage_error = InjectError(
            f"Failed to write boot-partition provision.json: {exc}"
        )
        stage_error.__cause__ = exc
    except BaseException as exc:
        stage_error = exc
    try:
        _cleanup_mount(device, boot_mount.mount_point, boot_mount.mounted_here, admission_fd=admission_fd)
    except InjectError as cleanup_error:
        if stage_error is not None:
            raise InjectError(
                f"{stage_error}; boot-volume cleanup also failed: {cleanup_error}"
            ) from cleanup_error
        raise
    try:
        _assert_device_identity(device_identity)
    except InjectError as identity_error:
        if stage_error is not None:
            raise identity_error from stage_error
        raise
    if stage_error is not None:
        raise stage_error
    assert results is not None
    return results


def _assert_device_identity(expected: DeviceIdentity) -> None:
    try:
        assert_device_identity(expected)
    except (OSError, ValueError) as exc:
        raise InjectError(str(exc)) from exc


def stage_boot_payload(
    boot_root: Path,
    manifest: Manifest,
    node_name: str,
    *,
    ssh_enabled: Optional[bool] = None,
    api_wan_enabled: Optional[bool] = None,
    attestation: ProvisionAttestation | None = None,
) -> List[Tuple[str, bool]]:
    """Stage an offline boot tree, also used by artifact verification."""
    boot_fd = os.open(boot_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return _stage_boot_payload(
            boot_fd,
            manifest,
            node_name,
            ssh_enabled=ssh_enabled,
            api_wan_enabled=api_wan_enabled,
            attestation=attestation,
        )
    finally:
        os.close(boot_fd)


def _stage_boot_payload(
    boot_fd: int,
    manifest: Manifest,
    node_name: str,
    *,
    ssh_enabled: Optional[bool] = None,
    api_wan_enabled: Optional[bool] = None,
    attestation: ProvisionAttestation | None = None,
) -> List[Tuple[str, bool]]:
    provision_json = render(
        manifest,
        node_name,
        ssh_enabled=ssh_enabled,
        api_wan_enabled=api_wan_enabled,
        attestation=attestation,
    )
    try:
        os.mkdir("easymanet", mode=0o700, dir_fd=boot_fd)
    except FileExistsError:
        pass
    dest_fd = os.open(
        "easymanet",
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=boot_fd,
    )
    try:
        if os.fstat(dest_fd).st_dev != os.fstat(boot_fd).st_dev:
            raise InjectError(
                "Payload directory is on a different filesystem from the boot volume"
            )
        _atomic_write_text(
            Path("provision.json"), provision_json, mode=0o600, dir_fd=dest_fd
        )
    finally:
        os.close(dest_fd)
    results = [
        ("/boot/easymanet/provision.json", True),
        ("Base image must already include EasyMANET first-boot hooks", True),
    ]
    cmdline_result = _fix_usb_boot_root(boot_fd)
    if cmdline_result:
        results.append((cmdline_result, True))
    return results


def inject_dry_run_info() -> str:
    lines = ["Files to place on the boot FAT partition:"]
    lines.append("  /easymanet/provision.json")
    lines.append("       (generated from fleet.yml for this node)")
    lines.append("")
    lines.append("Base image requirement:")
    lines.append("  Image must already include EasyMANET first-boot hooks:")
    lines.append("  /etc/uci-defaults/99-easymanet")
    lines.append("  and /usr/lib/easymanet/provision.sh via the firmware build.")
    return "\n".join(lines)


def _root_device_partuuid_suffix(dev_path: str) -> Optional[str]:
    match = re.match(r"/dev/(?:mmcblk\d+)p(\d+)$", dev_path)
    if match:
        return f"-{int(match.group(1)):02d}"
    match = re.match(r"/dev/(?:nvme\d+n\d+)p(\d+)$", dev_path)
    if match:
        return f"-{int(match.group(1)):02d}"
    match = re.match(r"/dev/[a-z]+(\d+)$", dev_path)
    if match:
        return f"-{int(match.group(1)):02d}"
    return None


def _fix_usb_boot_root(dir_fd: int) -> Optional[str]:
    cmdline_path = Path("cmdline.txt")
    partuuid_path = Path("partuuid.txt")
    try:
        cmdline = _read_text(cmdline_path, dir_fd=dir_fd)
        partuuid = _read_text(partuuid_path, dir_fd=dir_fd).strip()
    except FileNotFoundError:
        return None
    if "root=PARTUUID=" in cmdline:
        return None

    match = ROOT_BLOCK_DEVICE_PATTERN.search(cmdline)
    if not match:
        return None

    root_device = match.group(1)
    if not partuuid:
        return None

    part_suffix = _root_device_partuuid_suffix(root_device)
    if not part_suffix:
        return None

    root_partuuid = f"PARTUUID={partuuid}{part_suffix}"
    backup_path = Path("cmdline.txt.easymanet.bak")
    cmdline_mode = stat.S_IMODE(
        os.stat(cmdline_path, dir_fd=dir_fd, follow_symlinks=False).st_mode
    )
    try:
        os.stat(backup_path, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        _atomic_write_text(backup_path, cmdline, mode=cmdline_mode, dir_fd=dir_fd)

    updated = cmdline.replace(f"root={root_device}", f"root={root_partuuid}", 1)
    _atomic_write_text(cmdline_path, updated, mode=cmdline_mode, dir_fd=dir_fd)
    return f"/boot/cmdline.txt root={root_partuuid}"


def _read_text(path: Path, *, dir_fd: int | None) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    with os.fdopen(fd, encoding="utf-8") as handle:
        return handle.read()


def _atomic_write_text(
    path: Path,
    content: str,
    *,
    mode: int,
    dir_fd: int | None = None,
) -> None:
    temp_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode, dir_fd=dir_fd)
    open_fd = fd
    try:
        try:
            os.fchmod(fd, mode)
        except OSError:
            # FAT/exFAT boot media may not honor POSIX permissions.
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            open_fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if dir_fd is None:
            os.replace(temp_path, path)
        else:
            os.replace(temp_path, path, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    finally:
        if open_fd >= 0:
            os.close(open_fd)
        try:
            os.unlink(temp_path, dir_fd=dir_fd)
        except FileNotFoundError:
            pass


def _mount_boot_partition(expected: DeviceIdentity, *, admission_fd: int | None = None) -> _BootMount:
    partition = _find_boot_partition(expected.path)
    if not partition:
        raise InjectError(f"Could not find boot partition on {expected.path}")
    existing = _find_mount_for_partition(partition)
    if existing:
        return _BootMount(expected, partition, existing, False)
    if is_macos():
        mount_point, owned = _mount_boot_partition_macos(partition, admission_fd=admission_fd)
    elif is_linux():
        mount_point, owned = _mount_boot_partition_linux(partition, admission_fd=admission_fd)
    else:
        raise InjectError("Unsupported platform for boot-partition mounting")
    return _BootMount(expected, partition, mount_point, owned)


def _mount_boot_partition_macos(partition: str, *, admission_fd: int | None = None) -> Tuple[str, bool]:
    result = subprocess.run(
        ["diskutil", "mount", partition],
        capture_output=True,
        text=True,
        timeout=30,
        pass_fds=(admission_fd,) if admission_fd is not None else (),
    )
    if result.returncode != 0:
        raise InjectError(
            f"diskutil mount failed for {partition}: {result.stderr.strip()}"
        )

    mount_point = _find_mount_for_partition(partition)
    if not mount_point:
        raise InjectError(f"Mounted {partition} but could not find its mount point")
    return mount_point, True


def _mount_boot_partition_linux(partition: str, *, admission_fd: int | None = None) -> Tuple[str, bool]:
    mount_point = tempfile.mkdtemp(prefix="easymanet_boot_")
    result = subprocess.run(
        ["mount", partition, mount_point],
        capture_output=True,
        text=True,
        timeout=30,
        pass_fds=(admission_fd,) if admission_fd is not None else (),
    )
    if result.returncode != 0:
        try:
            os.rmdir(mount_point)
        except OSError:
            pass
        raise InjectError(f"mount failed for {partition}: {result.stderr.strip()}")
    return mount_point, True


def _cleanup_mount(device: str, mount_point: str, mounted_here: bool, *, admission_fd: int | None = None) -> None:
    if not mounted_here:
        return

    if is_macos():
        try:
            result = subprocess.run(
                ["diskutil", "unmount", mount_point],
                capture_output=True,
                text=True,
                timeout=30,
                pass_fds=(admission_fd,) if admission_fd is not None else (),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise InjectError(
                f"Failed to unmount owned boot volume {mount_point} on {device}: {exc}"
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            suffix = f": {detail}" if detail else ""
            raise InjectError(
                f"Failed to unmount owned boot volume {mount_point} on {device}{suffix}"
            )
        return

    if is_linux():
        try:
            result = subprocess.run(
                ["umount", mount_point],
                capture_output=True,
                text=True,
                timeout=30,
                pass_fds=(admission_fd,) if admission_fd is not None else (),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise InjectError(
                f"Failed to unmount owned boot volume {mount_point} on {device}: {exc}"
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            suffix = f": {detail}" if detail else ""
            raise InjectError(
                f"Failed to unmount owned boot volume {mount_point} on {device}{suffix}"
            )
        try:
            os.rmdir(mount_point)
        except OSError as exc:
            raise InjectError(
                f"Failed to remove owned boot mount directory {mount_point}: {exc}"
            ) from exc
        return

    raise InjectError(
        f"Unsupported platform while cleaning up {mount_point} on {device}"
    )


def _macos_partition_index(partition: dict) -> int:
    dev_id = partition.get("DeviceIdentifier", "")
    match = re.search(r"s(\d+)$", dev_id)
    if match:
        return int(match.group(1))
    return 0


def _is_macos_fat_partition(partition: dict) -> bool:
    fs_type = (partition.get("FilesystemType") or "").lower()
    if fs_type in _BOOT_FILESYSTEMS:
        return True
    content = partition.get("Content") or ""
    if content in _MACOS_FAT_CONTENTS:
        return True
    return "FAT" in content.upper()


def _macos_partitions_for_device(device: str) -> List[dict]:
    try:
        output = subprocess.check_output(
            ["diskutil", "list", "-plist", device],
            timeout=15,
        )
        data = plistlib.loads(output)
    except _BOOT_PARTITION_PARSE_ERRORS as exc:
        _debug_note(f"boot partition lookup failed for {device}: {exc}")
        return []

    partitions: List[dict] = []
    for entry in data.get("AllDisksAndPartitions", []):
        if f"/dev/{entry.get('DeviceIdentifier', '')}" == device:
            partitions.extend(entry.get("Partitions", []))
    return sorted(partitions, key=_macos_partition_index)


def _find_boot_partition(device: str) -> Optional[str]:
    if is_macos():
        for partition in _macos_partitions_for_device(device):
            if _is_macos_fat_partition(partition) and partition.get("DeviceIdentifier"):
                return f"/dev/{partition['DeviceIdentifier']}"
        return None

    if is_linux():
        try:
            output = subprocess.check_output(
                ["lsblk", "-J", "-p", "-o", "NAME,TYPE,FSTYPE", device],
                timeout=15,
            )
            data = json.loads(output)
            for disk in data["blockdevices"]:
                if os.path.realpath(disk["name"]) != os.path.realpath(device):
                    continue
                for partition in disk.get("children", []):
                    if (
                        partition.get("type") == "part"
                        and (partition.get("fstype") or "").lower() in _BOOT_FILESYSTEMS
                    ):
                        return partition["name"]
        except (*_BOOT_PARTITION_PARSE_ERRORS, KeyError, TypeError) as exc:
            _debug_note(f"boot partition lookup failed for {device}: {exc}")
    return None


def _find_mount_for_partition(partition: str) -> Optional[str]:
    try:
        if is_macos():
            info = _macos_partition_info(partition)
            return info.get("MountPoint") or None
        if is_linux():
            filesystems = _linux_mount_info(["--source", partition])
            if len(filesystems) == 1:
                filesystem = filesystems[0]
                if os.path.realpath(filesystem["source"]) == os.path.realpath(
                    partition
                ):
                    return filesystem["target"]
    except (*_BOOT_PARTITION_PARSE_ERRORS, KeyError, TypeError) as exc:
        raise InjectError(f"Could not resolve mount for {partition}: {exc}") from exc
    return None


def _macos_partition_info(partition: str) -> dict:
    output = subprocess.check_output(
        ["diskutil", "info", "-plist", partition], timeout=15
    )
    info = plistlib.loads(output)
    if info.get("DeviceNode") != partition:
        raise InjectError(
            f"diskutil returned a different boot partition for {partition}"
        )
    return info


def _linux_mount_info(selector: list[str]) -> list[dict]:
    try:
        output = subprocess.check_output(
            ["findmnt", "-J", "-o", "SOURCE,TARGET,FSTYPE", *selector],
            timeout=5,
        )
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 1:
            return []
        raise
    return json.loads(output).get("filesystems", [])


def _check_boot_mount(mount: _BootMount) -> None:
    try:
        if is_macos():
            info = _macos_partition_info(mount.partition)
            parent = f"/dev/{info['ParentWholeDisk']}"
            if (
                parent != mount.device_identity.path
                or info.get("MountPoint") != mount.mount_point
            ):
                raise InjectError("Boot mount does not belong to the selected device")
            filesystem = (info.get("FilesystemType") or "").lower()
        elif is_linux():
            if _find_boot_partition(mount.device_identity.path) != mount.partition:
                raise InjectError(
                    "Boot partition no longer belongs to the selected device"
                )
            filesystems = _linux_mount_info(["--mountpoint", mount.mount_point])
            if len(filesystems) != 1:
                raise InjectError("Boot destination is not a mounted filesystem")
            info = filesystems[0]
            if info["target"] != mount.mount_point or os.path.realpath(
                info["source"]
            ) != os.path.realpath(mount.partition):
                raise InjectError(
                    "Boot mount does not belong to the selected partition"
                )
            filesystem = (info.get("fstype") or "").lower()
        else:
            raise InjectError("Unsupported platform for boot mount validation")
        if filesystem not in _BOOT_FILESYSTEMS:
            raise InjectError("Boot destination is not a supported FAT filesystem")
    except (*_BOOT_PARTITION_PARSE_ERRORS, KeyError, TypeError) as exc:
        raise InjectError(f"Could not verify boot mount identity: {exc}") from exc
