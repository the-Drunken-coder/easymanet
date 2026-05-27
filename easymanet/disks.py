"""Disk detection and listing for macOS and Linux.

Provides device listing, system disk detection, mount info,
and unmount/eject capabilities.
"""

import glob
import json
import os
import plistlib
import re
import subprocess
from typing import List, Optional, Tuple

from .platform import is_macos, is_linux

DISK_WARN_THRESHOLD_GB = 128
DISK_SUSPICIOUS_SIZE_GB = 256


class DiskInfo:
    def __init__(
        self,
        device: str,
        size_bytes: int = 0,
        model: str = "",
        removable: bool = False,
        mounted: Optional[List[str]] = None,
        is_system: bool = False,
        not_in_default_list: bool = False,
    ):
        self.device = device
        self.size_bytes = size_bytes
        self.model = model
        self.removable = removable
        self.mounted = mounted or []
        self.is_system = is_system
        self.not_in_default_list = not_in_default_list

    @property
    def size_gb(self) -> float:
        return self.size_bytes / (1024 ** 3)

    @property
    def size_human(self) -> str:
        gb = self.size_gb
        if gb < 1:
            mb = self.size_bytes / (1024 ** 2)
            return f"{mb:.1f} MB"
        return f"{gb:.1f} GB"

    @property
    def blocking_warnings(self) -> List[str]:
        w: List[str] = []
        if self.is_system:
            w.append(
                "WARNING: This appears to be a system disk — use --force to override"
            )
        elif not self.removable and self.size_gb > DISK_WARN_THRESHOLD_GB:
            w.append(
                "WARNING: Large fixed disk — use --force to proceed"
            )
        elif self.size_gb > DISK_SUSPICIOUS_SIZE_GB:
            w.append(
                "WARNING: Suspiciously large device — use --force to proceed"
            )
        if self.not_in_default_list:
            w.append(
                "WARNING: Device not in default disk list — use --force to proceed"
            )
        return w

    @property
    def warnings(self) -> List[str]:
        return self.blocking_warnings


def _is_block_device(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        import stat
        return stat.S_ISBLK(os.stat(path).st_mode)
    except OSError:
        return False


def _linux_disk_from_lsblk(dev: dict) -> DiskInfo:
    dev_name = dev.get("name", "")
    dev_path = f"/dev/{dev_name}"
    model = (dev.get("model") or "").strip() or dev_name
    removable = dev.get("rm", "0") == "1"
    tran = (dev.get("tran") or "").lower()
    if tran in ("usb", "mmc"):
        removable = True
    size_bytes = _parse_lsblk_size(dev.get("size", "0"))
    mounted = _get_linux_mounts(dev)
    is_system = _check_linux_system_disk(dev_path, mounted)
    return DiskInfo(
        device=dev_path,
        size_bytes=size_bytes,
        model=model,
        removable=removable,
        mounted=mounted,
        is_system=is_system,
    )


def _linux_should_list_default(dev: dict) -> bool:
    if dev.get("type") != "disk":
        return False
    if dev.get("rm", "0") == "1":
        return True
    tran = (dev.get("tran") or "").lower()
    return tran in ("usb", "mmc")


def _linux_lsblk_data(device: Optional[str] = None) -> Optional[dict]:
    cmd = [
        "lsblk",
        "-J",
        "-o",
        "NAME,SIZE,TYPE,MOUNTPOINT,MODEL,RM,ROTA,TRAN",
    ]
    if device:
        cmd.extend(["-n", device])
    try:
        output = subprocess.check_output(cmd, timeout=10).decode()
        return json.loads(output)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return None


def list_disks_linux(include_all: bool = False) -> List[DiskInfo]:
    data = _linux_lsblk_data()
    if not data:
        return []

    disks: List[DiskInfo] = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        if not include_all and not _linux_should_list_default(dev):
            continue
        disks.append(_linux_disk_from_lsblk(dev))

    return sorted(disks, key=lambda d: d.size_bytes, reverse=True)


def lookup_device_linux(device: str) -> Optional[DiskInfo]:
    data = _linux_lsblk_data(device)
    if not data:
        return None
    blockdevs = data.get("blockdevices", [])
    if not blockdevs:
        return None
    dev = blockdevs[0]
    if dev.get("type") != "disk":
        return None
    return _linux_disk_from_lsblk(dev)


def list_disks_macos(include_all: bool = False) -> List[DiskInfo]:
    if include_all:
        return _list_disks_macos_all()
    return _list_disks_macos_external()


def _list_disks_macos_external() -> List[DiskInfo]:
    disks: List[DiskInfo] = []
    try:
        output = subprocess.check_output(
            ["diskutil", "list", "-plist", "external"],
            timeout=15,
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return disks

    try:
        data = plistlib.loads(output.encode())
    except Exception:
        return disks

    all_disks_entries = data.get("AllDisksAndPartitions", [])
    all_mounts = _get_macos_all_mounts()

    for entry in all_disks_entries:
        disk = _diskinfo_from_macos_entry(entry, all_mounts)
        if disk:
            disks.append(disk)

    return disks


def _list_disks_macos_all() -> List[DiskInfo]:
    disks: List[DiskInfo] = []
    try:
        output = subprocess.check_output(
            ["diskutil", "list", "-plist"],
            timeout=15,
        ).decode()
        data = plistlib.loads(output.encode())
    except Exception:
        return disks

    all_mounts = _get_macos_all_mounts()
    seen = set()
    for entry in data.get("WholeDisks", []):
        dev_path = f"/dev/{entry}"
        if dev_path in seen:
            continue
        seen.add(dev_path)
        info_text = _get_diskutil_info_text(dev_path)
        if not info_text:
            continue
        size_bytes = _parse_macos_size(_parse_info_field(info_text, "Disk Size"))
        model = _parse_info_field(info_text, "Device / Media Name") or entry
        removable = _is_removable_from_info(info_text)
        mounted = _find_mounts_for_disk(entry, all_mounts)
        is_system = _check_macos_system(mounted)
        disks.append(
            DiskInfo(
                device=dev_path,
                size_bytes=size_bytes,
                model=model,
                removable=removable,
                mounted=mounted,
                is_system=is_system,
            )
        )

    return sorted(disks, key=lambda d: d.size_bytes, reverse=True)


def _diskinfo_from_macos_entry(entry: dict, all_mounts: dict) -> Optional[DiskInfo]:
    dev_id = entry.get("DeviceIdentifier", "")
    if not dev_id:
        return None
    dev_path = f"/dev/{dev_id}"
    size_bytes = entry.get("Size", 0)
    mounted = _find_mounts_for_disk(dev_id, all_mounts)
    info_text = _get_diskutil_info_text(dev_path)
    model = _parse_info_field(info_text, "Device / Media Name") or dev_id
    removable = _is_removable_from_info(info_text)
    is_system = _check_macos_system(mounted)
    return DiskInfo(
        device=dev_path,
        size_bytes=size_bytes,
        model=model,
        removable=removable,
        mounted=mounted,
        is_system=is_system,
    )


def lookup_device_macos(device: str) -> Optional[DiskInfo]:
    if not os.path.exists(device):
        return None
    info_text = _get_diskutil_info_text(device)
    if not info_text:
        return None
    dev_id = device.replace("/dev/", "")
    all_mounts = _get_macos_all_mounts()
    size_bytes = _parse_macos_size(_parse_info_field(info_text, "Disk Size"))
    model = _parse_info_field(info_text, "Device / Media Name") or dev_id
    removable = _is_removable_from_info(info_text)
    mounted = _find_mounts_for_disk(dev_id, all_mounts)
    is_system = _check_macos_system(mounted)
    return DiskInfo(
        device=device,
        size_bytes=size_bytes,
        model=model,
        removable=removable,
        mounted=mounted,
        is_system=is_system,
    )


def _parse_macos_size(size_str: str) -> int:
    if not size_str:
        return 0
    m = re.match(r"([\d.]+)\s*([KMGT]?B)", size_str.strip(), re.I)
    if not m:
        return 0
    num = float(m.group(1))
    unit = m.group(2).upper()
    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
    }
    return int(num * multipliers.get(unit, 1))


def _get_macos_all_mounts() -> dict:
    mounts = {}
    try:
        output = subprocess.check_output(["mount"], timeout=5).decode()
    except Exception:
        return mounts
    for line in output.strip().split("\n"):
        parts = line.split()
        if len(parts) >= 3:
            device = parts[0]
            mount_point = parts[2]
            base_dev = re.sub(r"s\d+$", "", device.replace("/dev/", ""))
            mounts.setdefault(base_dev, []).append(mount_point)
    return mounts


def _find_mounts_for_disk(dev_id: str, all_mounts: dict) -> List[str]:
    return all_mounts.get(dev_id, [])


def _get_diskutil_info_text(dev_path: str) -> str:
    try:
        return subprocess.check_output(
            ["diskutil", "info", dev_path],
            timeout=120,
        ).decode()
    except Exception:
        return ""


def _parse_info_field(info_text: str, field: str) -> str:
    pattern = re.escape(field) + r":\s+(.+)"
    m = re.search(pattern, info_text)
    if m:
        return m.group(1).strip()
    return ""


def _is_removable_from_info(info_text: str) -> bool:
    removable = _parse_info_field(info_text, "Removable Media")
    location = _parse_info_field(info_text, "Device Location")
    if removable.lower() in ("yes", "removable", "true"):
        return True
    if location.lower() == "external":
        return True
    return False


def _check_macos_system(mounts: List[str]) -> bool:
    sys_mounts = {"/", "/System/Volumes/Data"}
    for mp in mounts:
        if mp in sys_mounts:
            return True
    return False


def _parse_lsblk_size(size_str: str) -> int:
    try:
        return int(size_str)
    except ValueError:
        suffixes = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
        try:
            num = float(size_str[:-1])
            suffix = size_str[-1].upper()
            return int(num * suffixes.get(suffix, 1))
        except (ValueError, IndexError):
            return 0


def _get_linux_mounts(dev: dict) -> List[str]:
    mounts = []
    children = dev.get("children", [])
    for child in children:
        mp = child.get("mountpoint")
        if mp:
            mounts.append(mp)
    return mounts


def _findmnt_source(mount_point: str) -> Optional[str]:
    try:
        output = subprocess.check_output(
            ["findmnt", "-n", "-o", "SOURCE", mount_point],
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode()
        return output.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _linux_base_block_device(source: str) -> Optional[str]:
    if not source.startswith("/dev/"):
        return None
    match = re.match(r"^(?P<base>/dev/(?:mmcblk\d+|nvme\d+n\d+))p\d+$", source)
    if match:
        return match.group("base")
    match = re.match(r"^(?P<base>/dev/[a-z]+)\d+$", source)
    if match:
        return match.group("base")
    if re.match(r"^/dev/(?:mmcblk\d+|nvme\d+n\d+|[a-z]+)$", source):
        return source
    return None


def _linux_root_block_devices() -> set:
    related = set()
    for mount_point in ("/", "/boot"):
        source = _findmnt_source(mount_point)
        if not source:
            continue
        related.add(source)
        base = _linux_base_block_device(source)
        if base:
            related.add(base)
            related.update(_linux_partitions_for_device(base))
    return related


def _check_linux_system_disk(dev_path: str, mounts: List[str]) -> bool:
    root_related = _linux_root_block_devices()
    if root_related:
        if dev_path in root_related:
            return True
        if set(_linux_partitions_for_device(dev_path)) & root_related:
            return True
        for entry in root_related:
            if _linux_base_block_device(entry) == dev_path:
                return True
        return False

    sys_mounts = {"/", "/boot", "/home", "/var", "/usr"}
    for mp in mounts:
        if mp in sys_mounts:
            return True
    return False


def list_disks(include_all: bool = False) -> List[DiskInfo]:
    if is_macos():
        disks = list_disks_macos(include_all=include_all)
    elif is_linux():
        disks = list_disks_linux(include_all=include_all)
    else:
        return []
    return sorted(disks, key=lambda d: d.size_bytes, reverse=True)


def lookup_device(
    device: str,
    default_disks: Optional[List[DiskInfo]] = None,
) -> Optional[DiskInfo]:
    if is_macos():
        disk = lookup_device_macos(device)
    elif is_linux():
        disk = lookup_device_linux(device)
    else:
        disk = None

    if disk is None:
        return None

    disks = default_disks if default_disks is not None else list_disks(include_all=False)
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
    if not _is_block_device(device):
        raise ValueError(
            f"Device {device} does not exist or is not a block device."
        )

    disk = lookup_device(device)
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
    if is_macos():
        subprocess.run(["diskutil", "unmountDisk", device], capture_output=True, timeout=60)
    elif is_linux():
        targets = _linux_partitions_for_device(device) or [device]
        for target in targets:
            subprocess.run(["umount", "-l", target], capture_output=True, timeout=60)


def _linux_partitions_for_device(device: str) -> List[str]:
    partitions = set()
    for pattern in (f"{device}[0-9]*", f"{device}p[0-9]*"):
        partitions.update(glob.glob(pattern))
    partitions.discard(device)
    return sorted(partitions)


def get_macos_partitions(device: str) -> List[str]:
    try:
        output = subprocess.check_output(
            ["diskutil", "list", "-plist", device],
            timeout=15,
        ).decode()
        data = plistlib.loads(output.encode())
        partitions = []
        for a in data.get("AllDisksAndPartitions", []):
            for p in a.get("Partitions", []):
                pid = p.get("DeviceIdentifier", "")
                if pid:
                    partitions.append(f"/dev/{pid}")
        return partitions
    except Exception:
        return []


def get_partition2_wipe_range(device: str) -> Optional[Tuple[int, int]]:
    """Return (start_byte_offset, wipe_bytes) for partition 2 overlay wipe."""
    max_wipe = _OVERLAY_WIPE_BLOCK_MIB * _OVERLAY_WIPE_BLOCKS * 1024 * 1024

    if is_linux():
        return _linux_partition2_wipe_range(device, max_wipe)
    if is_macos():
        return _macos_partition2_wipe_range(device, max_wipe)
    return None


_OVERLAY_WIPE_BLOCK_MIB = 16
_OVERLAY_WIPE_BLOCKS = 288


def _linux_partition2_wipe_range(device: str, max_wipe: int) -> Optional[Tuple[int, int]]:
    cmd = ["lsblk", "-J", "-b", "-o", "NAME,START,SIZE,TYPE", "-n", device]
    try:
        output = subprocess.check_output(cmd, timeout=10).decode()
        data = json.loads(output)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return None

    blockdevs = data.get("blockdevices", [])
    if not blockdevs:
        return None
    children = blockdevs[0].get("children", [])
    parts = [c for c in children if c.get("type") == "part"]
    if len(parts) < 2:
        return None
    part2 = sorted(parts, key=lambda p: int(p.get("start", 0) or 0))[1]
    start = int(part2.get("start", 0) or 0)
    size = int(part2.get("size", 0) or 0)
    if start <= 0 or size <= 0:
        return None
    # lsblk -b reports START in 512-byte sectors on Linux.
    start_bytes = start * 512
    wipe_bytes = min(size, max_wipe)
    return (start_bytes, wipe_bytes)


def _macos_partition2_wipe_range(device: str, max_wipe: int) -> Optional[Tuple[int, int]]:
    try:
        output = subprocess.check_output(
            ["diskutil", "list", "-plist", device],
            timeout=15,
        ).decode()
        data = plistlib.loads(output.encode())
    except Exception:
        return None

    partitions = []
    for entry in data.get("AllDisksAndPartitions", []):
        for p in entry.get("Partitions", []):
            partitions.append(p)

    if len(partitions) < 2:
        return None

    part2 = sorted(partitions, key=lambda p: int(p.get("PartitionOffset", 0) or 0))[1]
    start = int(part2.get("PartitionOffset", 0) or 0)
    size = int(part2.get("Size", 0) or 0)
    if start <= 0 or size <= 0:
        return None
    wipe_bytes = min(size, max_wipe)
    return (start, wipe_bytes)


def eject_disk(device: str) -> None:
    if is_macos():
        subprocess.run(["diskutil", "eject", device], capture_output=True)
    elif is_linux():
        subprocess.run(["eject", device], capture_output=True)
