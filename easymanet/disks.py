"""Disk detection and listing for macOS and Linux.

Provides device listing, system disk detection, mount info,
and unmount/eject capabilities.
"""

import re
import subprocess
from typing import List, Optional

from .platform import is_macos, is_linux

DISK_WARN_THRESHOLD_GB = 128


class DiskInfo:
    def __init__(
        self,
        device: str,
        size_bytes: int = 0,
        model: str = "",
        removable: bool = False,
        mounted: Optional[List[str]] = None,
        is_system: bool = False,
    ):
        self.device = device
        self.size_bytes = size_bytes
        self.model = model
        self.removable = removable
        self.mounted = mounted or []
        self.is_system = is_system

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
    def warnings(self) -> List[str]:
        w = []
        if self.is_system:
            w.append("WARNING: This appears to be a system disk — refusing to flash")
        elif not self.removable and self.size_gb > DISK_WARN_THRESHOLD_GB:
            w.append("WARNING: Large fixed disk — use --force to proceed")
        elif self.size_gb > DISK_WARN_THRESHOLD_GB * 2:
            w.append("WARNING: Suspiciously large device — verify before flashing")
        return w


def list_disks_macos() -> List[DiskInfo]:
    disks: List[DiskInfo] = []
    try:
        output = subprocess.check_output(
            ["diskutil", "list", "-plist", "external"],
            timeout=15,
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return disks

    import plistlib
    try:
        data = plistlib.loads(output.encode())
    except Exception:
        return disks

    all_disks_entries = data.get("AllDisksAndPartitions", [])
    all_mounts = _get_macos_all_mounts()

    for entry in all_disks_entries:
        dev_id = entry.get("DeviceIdentifier", "")
        if not dev_id:
            continue
        dev_path = f"/dev/{dev_id}"

        size_bytes = entry.get("Size", 0)
        mounted = _find_mounts_for_disk(dev_id, all_mounts)

        info_text = _get_diskutil_info_text(dev_path)
        model = _parse_info_field(info_text, "Device / Media Name") or dev_id
        removable = _is_removable_from_info(info_text)

        is_system = _check_macos_system(mounted)

        disks.append(DiskInfo(
            device=dev_path,
            size_bytes=size_bytes,
            model=model,
            removable=removable,
            mounted=mounted,
            is_system=is_system,
        ))

    return disks


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



def list_disks_linux() -> List[DiskInfo]:
    disks: List[DiskInfo] = []
    try:
        output = subprocess.check_output(
            ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,MODEL,RM,ROTA"],
            timeout=10,
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return disks

    import json
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return disks

    blockdevs = data.get("blockdevices", [])
    for dev in blockdevs:
        if dev.get("type") != "disk":
            continue
        dev_name = dev.get("name", "")
        dev_path = f"/dev/{dev_name}"
        model = dev.get("model") or dev_name
        removable = dev.get("rm", "0") == "1"
        size_str = dev.get("size", "0")
        size_bytes = _parse_lsblk_size(size_str)

        mounted = _get_linux_mounts(dev)
        is_system = _check_linux_system_disk(dev_path, mounted)

        disks.append(DiskInfo(
            device=dev_path,
            size_bytes=size_bytes,
            model=model,
            removable=removable,
            mounted=mounted,
            is_system=is_system,
        ))

    return sorted(disks, key=lambda d: d.size_bytes, reverse=True)


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


def _check_linux_system_disk(dev_path: str, mounts: List[str]) -> bool:
    sys_mounts = {"/", "/boot", "/home", "/var", "/usr"}
    for mp in mounts:
        if mp in sys_mounts:
            return True
    return False


def list_disks() -> List[DiskInfo]:
    if is_macos():
        disks = list_disks_macos()
    elif is_linux():
        disks = list_disks_linux()
    else:
        return []
    return sorted(disks, key=lambda d: d.size_bytes, reverse=True)


def find_disk(device: str) -> Optional[DiskInfo]:
    for disk in list_disks():
        if disk.device == device:
            return disk
    return None


def unmount_disk(device: str) -> None:
    if is_macos():
        subprocess.run(["diskutil", "unmountDisk", device], capture_output=True, timeout=60)
    elif is_linux():
        subprocess.run(["umount", "-l", device + "*"], capture_output=True, shell=True)


def _get_macos_partitions(device: str) -> List[str]:
    try:
        output = subprocess.check_output(
            ["diskutil", "list", "-plist", device],
            timeout=15,
        ).decode()
        import plistlib
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


def eject_disk(device: str) -> None:
    if is_macos():
        subprocess.run(["diskutil", "eject", device], capture_output=True)
    elif is_linux():
        subprocess.run(["eject", device], capture_output=True)
