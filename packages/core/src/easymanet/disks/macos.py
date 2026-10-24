"""macOS disk discovery and safety helpers."""

import os
import plistlib
import re
import subprocess
from typing import List, Optional, Tuple

from ._common import DISK_PARSE_ERRORS, DiskInfo, debug_note


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
    except DISK_PARSE_ERRORS as exc:
        debug_note(f"diskutil external plist parse failed: {exc}")
        return disks

    all_disks_entries = data.get("AllDisksAndPartitions", [])
    all_mounts = _get_macos_all_mounts()

    for entry in all_disks_entries:
        disk = _diskinfo_from_macos_entry(entry, all_mounts)
        if disk and disk.virtual:
            continue
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
    except DISK_PARSE_ERRORS as exc:
        debug_note(f"diskutil list plist parse failed: {exc}")
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
        virtual = _is_virtual_from_info(info_text)
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
                virtual=virtual,
                safety_error="Could not resolve all macOS system backing disks."
                if all_mounts is None
                else "",
            )
        )

    return sorted(disks, key=lambda d: d.size_bytes, reverse=True)


def _diskinfo_from_macos_entry(entry: dict, all_mounts: dict | None) -> Optional[DiskInfo]:
    dev_id = entry.get("DeviceIdentifier", "")
    if not dev_id:
        return None
    dev_path = f"/dev/{dev_id}"
    size_bytes = entry.get("Size", 0)
    mounted = _find_mounts_for_disk(dev_id, all_mounts)
    info_text = _get_diskutil_info_text(dev_path)
    model = _parse_info_field(info_text, "Device / Media Name") or dev_id
    removable = _is_removable_from_info(info_text)
    virtual = _is_virtual_from_info(info_text)
    is_system = _check_macos_system(mounted)
    return DiskInfo(
        device=dev_path,
        size_bytes=size_bytes,
        model=model,
        removable=removable,
        mounted=mounted,
        is_system=is_system,
        virtual=virtual,
        safety_error="Could not resolve all macOS system backing disks."
        if all_mounts is None
        else "",
    )


_MACOS_WHOLE_DISK_RE = re.compile(r"^/dev/r?disk\d+$")


def _canonical_macos_whole_disk(device: str) -> Optional[str]:
    if not _MACOS_WHOLE_DISK_RE.match(device):
        return None
    return device.replace("/dev/rdisk", "/dev/disk", 1)


def lookup_device_macos(device: str) -> Optional[DiskInfo]:
    dev_path = _canonical_macos_whole_disk(device)
    if dev_path is None:
        return None
    if not os.path.exists(device) and not os.path.exists(dev_path):
        return None
    info_text = _get_diskutil_info_text(dev_path)
    if not info_text:
        return None
    dev_id = dev_path.replace("/dev/", "")
    all_mounts = _get_macos_all_mounts()
    size_bytes = _parse_macos_size(_parse_info_field(info_text, "Disk Size"))
    model = _parse_info_field(info_text, "Device / Media Name") or dev_id
    removable = _is_removable_from_info(info_text)
    virtual = _is_virtual_from_info(info_text)
    mounted = _find_mounts_for_disk(dev_id, all_mounts)
    is_system = _check_macos_system(mounted)
    return DiskInfo(
        device=dev_path,
        size_bytes=size_bytes,
        model=model,
        removable=removable,
        mounted=mounted,
        is_system=is_system,
        virtual=virtual,
        safety_error="Could not resolve all macOS system backing disks."
        if all_mounts is None
        else "",
    )


def _parse_macos_size(size_str: str) -> int:
    exact_bytes = re.search(r"\(([\d,]+) Bytes\)", size_str)
    if exact_bytes:
        return int(exact_bytes.group(1).replace(",", ""))
    return 0


def _get_macos_all_mounts() -> dict[str, list[str]] | None:
    try:
        output = subprocess.check_output(["diskutil", "list", "-plist"], timeout=15)
        data = plistlib.loads(output)
        entries = data["AllDisksAndPartitions"]
        mounts: dict[str, list[str]] = {}
        physical_parents = {}
        for entry in entries:
            dev_id = entry["DeviceIdentifier"]
            if "APFSVolumes" not in entry and "APFSPhysicalStores" not in entry:
                physical_parents[dev_id] = dev_id
            if entry.get("MountPoint"):
                mounts.setdefault(dev_id, []).append(entry["MountPoint"])
            for partition in entry.get("Partitions", []):
                physical_parents[partition["DeviceIdentifier"]] = dev_id
            volumes = entry.get("Partitions", []) + entry.get("APFSVolumes", [])
            for volume in volumes:
                mount_point = volume.get("MountPoint")
                if mount_point is None:
                    mount_point = _get_macos_mount_point(f"/dev/{volume['DeviceIdentifier']}")
                if mount_point:
                    mounts.setdefault(dev_id, []).append(mount_point)
                for snapshot in volume.get("MountedSnapshots", []):
                    snapshot_mount = snapshot.get("SnapshotMountPoint")
                    if snapshot_mount:
                        mounts.setdefault(dev_id, []).append(snapshot_mount)

        for entry in entries:
            if "APFSVolumes" not in entry:
                continue
            container_mounts = mounts.get(entry["DeviceIdentifier"], [])
            system_container = _check_macos_system(container_mounts)
            stores = entry.get("APFSPhysicalStores", [])
            if system_container and not stores:
                return None
            for store in stores:
                parent = physical_parents.get(store["DeviceIdentifier"])
                if parent is None:
                    if system_container:
                        return None
                    continue
                mounts.setdefault(parent, []).extend(container_mounts)

        if not any("/" in disk_mounts for disk_mounts in mounts.values()):
            return None
    except (*DISK_PARSE_ERRORS, KeyError, TypeError) as exc:
        debug_note(f"diskutil mount plist unavailable: {exc}")
        return None

    mounts = {device: list(dict.fromkeys(points)) for device, points in mounts.items()}
    return mounts


def _get_macos_mount_point(dev_path: str) -> str:
    try:
        output = subprocess.check_output(
            ["diskutil", "info", "-plist", dev_path],
            timeout=15,
        )
        data = plistlib.loads(output)
    except DISK_PARSE_ERRORS as exc:
        debug_note(f"diskutil mount point lookup failed for {dev_path}: {exc}")
        return ""
    return data.get("MountPoint") or ""


def _find_mounts_for_disk(dev_id: str, all_mounts: dict | None) -> List[str]:
    return all_mounts.get(dev_id, []) if all_mounts is not None else []


def _get_diskutil_info_text(dev_path: str) -> str:
    try:
        return subprocess.check_output(
            ["diskutil", "info", dev_path],
            timeout=120,
        ).decode()
    except DISK_PARSE_ERRORS as exc:
        debug_note(f"diskutil info failed for {dev_path}: {exc}")
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


def _is_virtual_from_info(info_text: str) -> bool:
    virtual = _parse_info_field(info_text, "Virtual")
    protocol = _parse_info_field(info_text, "Protocol")
    model = _parse_info_field(info_text, "Device / Media Name")
    if virtual.lower() in ("yes", "true"):
        return True
    if protocol.lower() == "disk image":
        return True
    return model.lower() == "disk image"


def _check_macos_system(mounts: List[str]) -> bool:
    sys_mounts = {"/", "/System/Volumes/Data"}
    for mp in mounts:
        if mp in sys_mounts:
            return True
    return False


def _macos_partition_index(partition: dict) -> int:
    dev_id = partition.get("DeviceIdentifier", "")
    match = re.search(r"s(\d+)$", dev_id)
    if match:
        return int(match.group(1))
    return 0


def _macos_partition_byte_offset(partition: dict) -> Optional[int]:
    """Byte offset of a partition on its parent disk."""
    offset = partition.get("PartitionOffset")
    if offset is not None:
        off = int(offset)
        if off > 0:
            return off

    dev_id = partition.get("DeviceIdentifier", "")
    if not dev_id:
        return None

    try:
        output = subprocess.check_output(
            ["diskutil", "info", "-plist", f"/dev/{dev_id}"],
            timeout=15,
        )
        info = plistlib.loads(output)
    except DISK_PARSE_ERRORS as exc:
        debug_note(f"diskutil info failed for /dev/{dev_id}: {exc}")
        return None

    for key in ("PartitionMapPartitionOffset", "PartitionOffset"):
        value = info.get(key)
        if value is not None:
            off = int(value)
            if off > 0:
                return off
    return None


def _macos_partition2_wipe_range(device: str, max_wipe: int) -> Optional[Tuple[int, int]]:
    try:
        output = subprocess.check_output(
            ["diskutil", "list", "-plist", device],
            timeout=15,
        ).decode()
        data = plistlib.loads(output.encode())
    except DISK_PARSE_ERRORS as exc:
        debug_note(f"partition 2 wipe range lookup failed for {device}: {exc}")
        return None

    partitions = []
    for entry in data.get("AllDisksAndPartitions", []):
        for p in entry.get("Partitions", []):
            partitions.append(p)

    if len(partitions) < 2:
        return None

    part2 = sorted(partitions, key=_macos_partition_index)[1]
    start = _macos_partition_byte_offset(part2)
    size = int(part2.get("Size", 0) or 0)
    if start is None or start <= 0 or size <= 0:
        return None
    wipe_bytes = min(size, max_wipe)
    tail_start = start + size - wipe_bytes
    return (tail_start, wipe_bytes)


def unmount_disk_macos(device: str, *, admission_fd: int | None = None) -> None:
    result = subprocess.run(
        ["diskutil", "unmountDisk", device],
        capture_output=True,
        text=True,
        timeout=60,
        pass_fds=(admission_fd,) if admission_fd is not None else (),
    )
    if result.returncode != 0:
        force_result = subprocess.run(
            ["diskutil", "unmountDisk", "force", device],
            capture_output=True,
            text=True,
            timeout=60,
            pass_fds=(admission_fd,) if admission_fd is not None else (),
        )
        if force_result.returncode != 0:
            detail = (force_result.stderr or force_result.stdout or "").strip()
            if not detail:
                detail = (result.stderr or result.stdout or "").strip()
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(f"Failed to unmount {device}{suffix}")
