"""Image flashing — write OpenMANET images to SD cards/USB drives.

Handles .img and .img.gz, streaming decompression, progress display,
verify/sync, and clean unmount/eject.
"""

import os
import shlex
import shutil
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Callable, Optional

from .disks import unmount_disk, eject_disk, find_disk


class FlashError(Exception):
    pass


def _check_device_safety(device: str, force: bool = False) -> None:
    disk = find_disk(device)
    if disk is None:
        raise FlashError(f"Device {device} not found. Use 'easymanet disks' to list available devices.")
    if not os.path.exists(device):
        raise FlashError(f"Device {device} does not exist.")
    if disk.is_system and not force:
        raise FlashError(
            f"Device {device} appears to be a system disk. Use --force to override.\n"
            f"  Model: {disk.model}\n"
            f"  Size: {disk.size_human}\n"
            f"  Mounted: {', '.join(disk.mounted) if disk.mounted else 'none'}"
        )


def _check_image(image_path: str) -> Path:
    p = Path(image_path)
    if not p.exists():
        raise FlashError(f"Base image not found: {image_path}")
    suffix = p.suffix.lower()
    if suffix == ".gz":
        if p.stem.lower().endswith(".img"):
            _check_gzip_integrity(p)
            return p
        raise FlashError(f"Expected .img.gz file, got: {image_path}")
    if suffix == ".img":
        return p
    raise FlashError(f"Unsupported image format: {image_path}. Expected .img or .img.gz")


def _check_gzip_integrity(image_path: Path) -> None:
    try:
        _check_gzip_payload(image_path)
    except (OSError, zlib.error) as e:
        raise FlashError(f"Invalid gzip-compressed image {image_path}: {e}") from e


def _check_gzip_payload(image_path: Path) -> None:
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    total = 0
    with image_path.open("rb") as f:
        while not decompressor.eof:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            total += len(decompressor.decompress(chunk))

    if not decompressor.eof:
        raise zlib.error("compressed image ended before the gzip stream completed")
    if total == 0:
        raise zlib.error("compressed image did not contain a disk image payload")


def flash_image(
    device: str,
    image_path: str,
    dry_run: bool = False,
    force: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> None:
    image = _check_image(image_path)
    _check_device_safety(device, force=force)

    if dry_run:
        return

    disk = find_disk(device)

    if disk:
        mounted_str = ", ".join(disk.mounted) if disk.mounted else "none"
        print(f"Device: {disk.device}")
        print(f"Model: {disk.model}")
        print(f"Size: {disk.size_human}")
        print(f"Mounted: {mounted_str}")
        print(f"Removable: {'yes' if disk.removable else 'no'}")
        print()

    unmount_disk(device)
    _clear_stale_overlay(device)
    print(f"Writing {image.name} to {device}...")

    try:
        if image.suffix == ".gz":
            _write_gz_via_dd(str(image), device)
        else:
            _write_raw_via_dd(str(image), device)

        print("Syncing...")
        os.sync()
        print("Done writing.")

    except subprocess.CalledProcessError as e:
        raise FlashError(f"Flash failed: {e}")
    except Exception as e:
        raise FlashError(f"Flash failed: {e}")


def _write_gz_via_dd(image_path: str, device: str) -> None:
    gzip_proc = subprocess.Popen(
        ["gzip", "-dc", image_path],
        stdout=subprocess.PIPE,
    )
    assert gzip_proc.stdout is not None
    dd_proc = subprocess.Popen(
        ["dd", f"of={device}", "bs=16m", "status=progress"],
        stdin=gzip_proc.stdout,
    )
    gzip_proc.stdout.close()

    dd_return = dd_proc.wait()
    gzip_return = gzip_proc.wait()

    if gzip_return not in (0, 2):
        raise subprocess.CalledProcessError(gzip_return, ["gzip", "-dc", image_path])
    if dd_return != 0:
        raise subprocess.CalledProcessError(dd_return, ["dd", f"of={device}"])


# Stock OpenMANET partition 2 (squashfs+overlay) is ~4.3 GB. The f2fs
# overlay lives well past the first 512 MiB, so a small wipe leaves the
# overlay intact across re-flashes — /etc/easymanet/provisioned and the
# rest of /etc/easymanet survive, and first-boot provisioning silently
# skips on subsequent flashes. Zero 4.5 GiB to cover all of partition 2.
_OVERLAY_WIPE_BLOCK_MIB = 16
_OVERLAY_WIPE_BLOCKS = 288  # 16 MiB * 288 = 4.5 GiB


def _clear_stale_overlay(device: str) -> None:
    total_mib = _OVERLAY_WIPE_BLOCK_MIB * _OVERLAY_WIPE_BLOCKS
    print(f"Clearing stale OpenWrt overlay area ({total_mib} MiB)...")
    subprocess.run(
        [
            "dd",
            "if=/dev/zero",
            f"of={device}",
            f"bs={_OVERLAY_WIPE_BLOCK_MIB}m",
            f"count={_OVERLAY_WIPE_BLOCKS}",
            "status=progress",
        ],
        check=True,
    )


def _write_raw_via_dd(image_path: str, device: str) -> None:
    cmd = f"dd if={shlex.quote(str(image_path))} of={shlex.quote(device)} bs=16m status=progress 2>&1"
    subprocess.run(cmd, shell=True, check=True)


def _get_uncompressed_size(gz_path: Path) -> int:
    with open(gz_path, "rb") as f:
        f.seek(-4, 2)
        size_bytes = f.read(4)
        return int.from_bytes(size_bytes, "little")


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    elif n < 1024**2:
        return f"{n/1024:.1f} KB"
    elif n < 1024**3:
        return f"{n/1024**2:.1f} MB"
    else:
        return f"{n/1024**3:.1f} GB"


def finish_flash(device: str, eject: bool = True) -> None:
    os.sync()
    if eject:
        print(f"Ejecting {device}...")
        eject_disk(device)
    print("Safe to remove.")
