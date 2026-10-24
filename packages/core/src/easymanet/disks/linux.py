"""Linux disk discovery and safety helpers."""

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ._common import SYS_MOUNT_POINTS, DiskInfo

_LINUX_DEFAULT_LOGICAL_SECTOR_BYTES = 512
_NONLOCAL_FILESYSTEMS = frozenset({"nfs", "nfs4", "cifs", "smb3", "autofs", "tmpfs", "ramfs"})


@dataclass
class _BlockDevice:
    path: str
    kind: str
    size_bytes: int
    model: str
    removable: bool
    mounts: set[str] = field(default_factory=set)
    parents: set[str] = field(default_factory=set)
    children: set[str] = field(default_factory=set)


@dataclass
class _BlockGraph:
    devices: dict[str, _BlockDevice]

    @classmethod
    def from_lsblk(cls, data: dict) -> "_BlockGraph":
        graph = cls({})

        def add(entry: dict, parent: str | None = None) -> None:
            path = _block_path(entry["name"])
            node = graph.devices.get(path)
            if node is None:
                node = _BlockDevice(
                    path=path,
                    kind=entry["type"],
                    size_bytes=int(entry.get("size") or 0),
                    model=(entry.get("model") or "").strip() or path,
                    removable=_linux_should_list_default(entry),
                )
                graph.devices[path] = node
            mounts = entry.get("mountpoints") or [entry.get("mountpoint")]
            node.mounts.update(mount for mount in mounts if mount)
            if parent:
                node.parents.add(parent)
                graph.devices[parent].children.add(path)
            if entry.get("pkname"):
                node.parents.add(_block_path(entry["pkname"]))
            for child in entry.get("children", []):
                add(child, path)

        for entry in data["blockdevices"]:
            add(entry)
        for node in graph.devices.values():
            for parent in node.parents:
                if parent in graph.devices:
                    graph.devices[parent].children.add(node.path)
        return graph

    def backing_disks(
        self,
        path: str,
        visiting: frozenset[str] = frozenset(),
        *,
        allow_virtual: bool = False,
    ) -> set[str] | None:
        node = self.devices.get(path)
        if node is None or path in visiting:
            return None
        if node.kind == "disk" and not node.parents:
            return {path}
        if allow_virtual and node.kind in {"loop", "rom"} and not node.parents:
            return set()
        if not node.parents:
            return None
        backing = set()
        for parent in node.parents:
            disks = self.backing_disks(parent, visiting | {path}, allow_virtual=allow_virtual)
            if disks is None:
                return None
            backing.update(disks)
        return backing

    def descendants(self, path: str) -> set[str]:
        found = set()
        pending = [path]
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            pending.extend(self.devices[current].children)
        return found

    def mounts(self, path: str) -> list[str]:
        return sorted(
            {
                mount
                for child in self.descendants(path)
                for mount in self.devices[child].mounts
            }
        )


def _block_path(name: str) -> str:
    path = name if name.startswith("/dev/") else f"/dev/{name}"
    return os.path.realpath(path)


def _linux_should_list_default(dev: dict) -> bool:
    if dev.get("type") != "disk":
        return False
    removable = dev.get("rm") in (True, 1, "1")
    transport = (dev.get("tran") or "").lower()
    return removable or transport in ("usb", "mmc")


def _linux_lsblk_data() -> Optional[dict]:
    cmd = [
        "lsblk",
        "-J",
        "-b",
        "-p",
        "--tree",
        "-o",
        "NAME,PKNAME,SIZE,TYPE,MOUNTPOINT,MODEL,RM,TRAN",
    ]
    try:
        output = subprocess.check_output(cmd, timeout=10)
        data = json.loads(output)
        return data if isinstance(data, dict) else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _linux_block_graph() -> _BlockGraph | None:
    data = _linux_lsblk_data()
    if data is None:
        return None
    try:
        return _BlockGraph.from_lsblk(data)
    except (KeyError, TypeError, ValueError):
        return None


def _linux_resolve_findmnt_source(source: str) -> str | None:
    source = source.split("[", 1)[0]
    if source.startswith("UUID="):
        source = f"/dev/disk/by-uuid/{source.split('=', 1)[1]}"
    elif source.startswith("PARTUUID="):
        source = f"/dev/disk/by-partuuid/{source.split('=', 1)[1]}"
    if not source.startswith("/dev/"):
        return None
    return os.path.realpath(source)


def _linux_mounts_and_system_disks(graph: _BlockGraph) -> set[str] | None:
    try:
        output = subprocess.check_output(
            ["findmnt", "-J", "-o", "SOURCE,TARGET,FSTYPE"],
            timeout=5,
        )
        filesystems = json.loads(output)["filesystems"]
        protected = set()
        btrfs_members: dict[str, set[str]] = {}
        root_found = False
        pending = list(filesystems)
        while pending:
            filesystem = pending.pop()
            pending.extend(filesystem.get("children", []))
            target = filesystem["target"]
            root_found = root_found or target == "/"
            fstype = filesystem.get("fstype")
            if fstype in _NONLOCAL_FILESYSTEMS:
                continue
            source = _linux_resolve_findmnt_source(filesystem["source"])
            backing = None
            if source:
                if source not in graph.devices:
                    return None
                graph.devices[source].mounts.add(target)
            if fstype == "btrfs":
                if source is None:
                    return None
                if source not in btrfs_members:
                    members = _linux_btrfs_members(target, source)
                    if members is None:
                        return None
                    btrfs_members[source] = members
                backing = set()
                for member in btrfs_members[source]:
                    member_backing = graph.backing_disks(
                        member, allow_virtual=target not in SYS_MOUNT_POINTS
                    )
                    if member_backing is None:
                        return None
                    graph.devices[member].mounts.add(target)
                    backing.update(member_backing)
                for path in backing:
                    graph.devices[path].mounts.add(target)
            elif source:
                backing = graph.backing_disks(
                    source, allow_virtual=target not in SYS_MOUNT_POINTS
                )
                if backing is None:
                    return None
            if target not in SYS_MOUNT_POINTS:
                continue
            if not fstype or not backing:
                return None
            protected.update(backing)
        return protected if root_found else None
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None


def _linux_btrfs_members(target: str, source: str) -> set[str] | None:
    output = subprocess.check_output(
        ["btrfs", "filesystem", "show", "--raw", target], timeout=5
    ).decode()
    totals = re.findall(r"^\s*Total devices (\d+) FS bytes used \d+\s*$", output, re.MULTILINE)
    members = re.findall(
        r"^\s*devid\s+(\d+)\s+size\s+[1-9]\d*\s+used\s+\d+\s+path\s+(/dev/\S+)\s*$",
        output, re.MULTILINE,
    )
    device_lines = re.findall(r"^\s*devid\b.*$", output, re.MULTILINE)
    if len(device_lines) != len(members):
        return None
    if len(totals) != 1 or int(totals[0]) != len(members) or not members:
        return None
    if len({device_id for device_id, _path in members}) != len(members):
        return None
    paths = {_block_path(path) for _device_id, path in members}
    if source not in paths:
        return None
    return paths


def _linux_disk_info(
    node: _BlockDevice, graph: _BlockGraph, protected: set[str] | None
) -> DiskInfo:
    mounts = graph.mounts(node.path)
    backing = graph.backing_disks(node.path)
    unresolved = protected is None or backing is None
    is_system = backing is not None and protected is not None and bool(backing & protected)
    has_system_mount = bool(set(mounts) & SYS_MOUNT_POINTS)
    return DiskInfo(
        device=node.path,
        size_bytes=node.size_bytes,
        model=node.model,
        removable=node.removable,
        mounted=mounts,
        is_system=is_system or has_system_mount,
        safety_error="Could not resolve all Linux system backing disks."
        if unresolved
        else "",
    )


def list_disks_linux(include_all: bool = False) -> List[DiskInfo]:
    graph = _linux_block_graph()
    if graph is None:
        return []
    protected = _linux_mounts_and_system_disks(graph)
    disks = [
        _linux_disk_info(node, graph, protected)
        for node in graph.devices.values()
        if node.kind == "disk" and (include_all or node.removable)
    ]
    return sorted(disks, key=lambda disk: disk.size_bytes, reverse=True)


def lookup_device_linux(device: str) -> Optional[DiskInfo]:
    graph = _linux_block_graph()
    if graph is None:
        return None
    node = graph.devices.get(os.path.realpath(device))
    if node is None or node.kind != "disk":
        return None
    return _linux_disk_info(node, graph, _linux_mounts_and_system_disks(graph))


def _linux_partition2_wipe_range(
    device: str, max_wipe: int
) -> Optional[Tuple[int, int]]:
    cmd = ["lsblk", "-J", "-b", "-o", "NAME,START,SIZE,TYPE,LOG-SEC", "-n", device]
    try:
        output = subprocess.check_output(cmd, timeout=10).decode()
        data = json.loads(output)
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
    ):
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
    sector_bytes = _linux_logical_sector_bytes(part2, blockdevs[0])
    start_bytes = start * sector_bytes
    wipe_bytes = min(size, max_wipe)
    tail_start = start_bytes + size - wipe_bytes
    return (tail_start, wipe_bytes)


def _linux_logical_sector_bytes(*devices: dict) -> int:
    for dev in devices:
        for key in ("log-sec", "log_sec", "LOG-SEC"):
            try:
                value = int(dev.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
    return _LINUX_DEFAULT_LOGICAL_SECTOR_BYTES


def unmount_disk_linux(device: str, *, admission_fd: int | None = None) -> None:
    graph = _linux_block_graph()
    path = os.path.realpath(device)
    if graph is None or path not in graph.devices:
        raise RuntimeError(f"Could not resolve block devices for {device}")
    protected = _linux_mounts_and_system_disks(graph)
    backing = graph.backing_disks(path)
    if protected is None or not backing:
        raise RuntimeError(f"Could not resolve all system backing disks for {device}")
    mounts = graph.mounts(path)
    if backing & protected or set(mounts) & SYS_MOUNT_POINTS:
        raise RuntimeError(f"Refusing to unmount system disk {device}")
    for target in sorted(
        mounts, key=lambda mount: (mount.count("/"), mount), reverse=True
    ):
        result = subprocess.run(
            ["umount", target],
            capture_output=True,
            text=True,
            timeout=60,
            pass_fds=(admission_fd,) if admission_fd is not None else (),
        )
        if result.returncode == 0:
            continue
        detail = (result.stderr or result.stdout or "").strip()
        if "not mounted" in detail.lower():
            continue
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Failed to unmount {target}{suffix}")
