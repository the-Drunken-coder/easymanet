"""Write node-specific provisioning payloads to the boot partition."""

import os
import plistlib
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from .manifest import Manifest
from .platform import is_linux, is_macos
from .render import render

ROOT_BLOCK_DEVICE_PATTERN = re.compile(r"root=(/dev/[^\s]+)")


class InjectError(Exception):
    pass


def inject(
    device: str,
    manifest: Manifest,
    node_name: str,
    dry_run: bool = False,
    *,
    ssh_enabled: Optional[bool] = None,
) -> List[Tuple[str, bool]]:
    provision_json = render(manifest, node_name, ssh_enabled=ssh_enabled)
    if dry_run:
        return [
            ("/boot/easymanet/provision.json", True),
            ("Base image must already include EasyMANET first-boot hooks", True),
        ]

    mount_point, mounted_here = _mount_boot_partition(device)
    try:
        boot_root = Path(mount_point)
        dest_dir = boot_root / "easymanet"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / "provision.json"
        dest_path.write_text(provision_json)
        results = [
            ("/boot/easymanet/provision.json", True),
            ("Base image must already include EasyMANET first-boot hooks", True),
        ]
        cmdline_result = _fix_usb_boot_root(boot_root)
        if cmdline_result:
            results.append((cmdline_result, True))
        return results
    except OSError as e:
        raise InjectError(f"Failed to write boot-partition provision.json: {e}") from e
    finally:
        _cleanup_mount(device, mount_point, mounted_here)


def inject_dry_run_info(manifest: Manifest, node_name: str) -> str:
    del manifest
    del node_name
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
    match = re.match(r"/dev/[a-z]+(\d+)$", dev_path)
    if match:
        return f"-{int(match.group(1)):02d}"
    return None


def _fix_usb_boot_root(boot_root: Path) -> Optional[str]:
    cmdline_path = boot_root / "cmdline.txt"
    partuuid_path = boot_root / "partuuid.txt"
    if not cmdline_path.exists() or not partuuid_path.exists():
        return None

    cmdline = cmdline_path.read_text()
    if "root=PARTUUID=" in cmdline:
        return None

    match = ROOT_BLOCK_DEVICE_PATTERN.search(cmdline)
    if not match:
        return None

    root_device = match.group(1)
    partuuid = partuuid_path.read_text().strip()
    if not partuuid:
        return None

    part_suffix = _root_device_partuuid_suffix(root_device)
    if not part_suffix:
        return None

    root_partuuid = f"PARTUUID={partuuid}{part_suffix}"
    backup_path = boot_root / "cmdline.txt.easymanet.bak"
    if not backup_path.exists():
        backup_path.write_text(cmdline)

    updated = cmdline.replace(f"root={root_device}", f"root={root_partuuid}", 1)
    cmdline_path.write_text(updated)
    return f"/boot/cmdline.txt root={root_partuuid}"


def _mount_boot_partition(device: str) -> Tuple[str, bool]:
    existing = _find_boot_mount(device)
    if existing:
        return existing, False

    partition = _find_boot_partition(device)
    if not partition:
        raise InjectError(f"Could not find boot partition on {device}")

    if is_macos():
        return _mount_boot_partition_macos(partition)
    if is_linux():
        return _mount_boot_partition_linux(partition)
    raise InjectError("Unsupported platform for boot-partition mounting")


def _mount_boot_partition_macos(partition: str) -> Tuple[str, bool]:
    result = subprocess.run(
        ["diskutil", "mount", partition],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise InjectError(f"diskutil mount failed for {partition}: {result.stderr.strip()}")

    mount_point = _find_mount_for_partition(partition)
    if not mount_point:
        raise InjectError(f"Mounted {partition} but could not find its mount point")
    return mount_point, True


def _mount_boot_partition_linux(partition: str) -> Tuple[str, bool]:
    mount_point = tempfile.mkdtemp(prefix="easymanet_boot_")
    result = subprocess.run(
        ["mount", partition, mount_point],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        try:
            os.rmdir(mount_point)
        except OSError:
            pass
        raise InjectError(f"mount failed for {partition}: {result.stderr.strip()}")
    return mount_point, True


def _cleanup_mount(device: str, mount_point: str, mounted_here: bool) -> None:
    del device
    if not mounted_here:
        return

    if is_macos():
        subprocess.run(
            ["diskutil", "unmount", mount_point],
            capture_output=True,
            timeout=30,
        )
        return

    if is_linux():
        subprocess.run(
            ["umount", mount_point],
            capture_output=True,
            timeout=30,
        )
        try:
            os.rmdir(mount_point)
        except OSError:
            pass


def _find_boot_partition(device: str) -> Optional[str]:
    if is_macos():
        try:
            output = subprocess.check_output(
                ["diskutil", "list", "-plist", device],
                timeout=15,
            )
            data = plistlib.loads(output)
            all_disks = data.get("AllDisksAndPartitions", [])
            for entry in all_disks:
                for partition in entry.get("Partitions", []):
                    if partition.get("FilesystemType") in {"msdos", "vfat", "fat32"}:
                        return f"/dev/{partition.get('DeviceIdentifier', '')}"
                partitions = entry.get("Partitions", [])
                if partitions:
                    return f"/dev/{partitions[0].get('DeviceIdentifier', '')}"
        except Exception:
            return None
        return None

    if is_linux():
        for suffix in ["1", "p1"]:
            part = f"{device}{suffix}"
            if os.path.exists(part):
                return part
        return None

    return None


def _find_boot_mount(device: str) -> Optional[str]:
    if is_macos():
        partition = _find_boot_partition(device)
        if partition:
            return _find_mount_for_partition(partition)
        return None

    if is_linux():
        partition = _find_boot_partition(device)
        if not partition:
            return None
        return _find_mount_for_partition(partition)

    return None


def _find_mount_for_partition(partition: str) -> Optional[str]:
    try:
        output = subprocess.check_output(["mount"], timeout=5).decode()
    except Exception:
        return None

    real_partition = os.path.realpath(partition)
    for line in output.strip().split("\n"):
        parts = line.split()
        if len(parts) < 3:
            continue
        source = parts[0]
        mount_point = parts[2]
        if source == partition or os.path.realpath(source) == real_partition:
            return mount_point
    return None
