"""Image flashing — write OpenMANET images to SD cards/USB drives.

Handles .img and .img.gz, streaming decompression, progress display,
verify/sync, and clean unmount/eject.
"""

import os
import subprocess
import zlib
from pathlib import Path
from typing import Callable, Optional

from .disks import (
    assert_flash_allowed,
    get_partition2_wipe_range,
    lookup_device,
    unmount_disk,
    eject_disk,
    _OVERLAY_WIPE_BLOCK_MIB,
)


class FlashError(Exception):
    pass


def _check_device_safety(device: str, force: bool = False) -> None:
    try:
        assert_flash_allowed(device, force=force)
    except ValueError as e:
        raise FlashError(str(e)) from e


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
    skip_overlay_wipe: bool = False,
) -> None:
    del progress_callback
    image = _check_image(image_path)
    _check_device_safety(device, force=force)

    if dry_run:
        return

    disk = lookup_device(device)

    if disk:
        mounted_str = ", ".join(disk.mounted) if disk.mounted else "none"
        print(f"Device: {disk.device}")
        print(f"Model: {disk.model}")
        print(f"Size: {disk.size_human}")
        print(f"Mounted: {mounted_str}")
        print(f"Removable: {'yes' if disk.removable else 'no'}")
        print()

    unmount_disk(device)
    print(f"Writing {image.name} to {device}...")

    try:
        if image.suffix == ".gz":
            _write_gz_via_dd(str(image), device)
        else:
            _write_raw_via_dd(str(image), device)

        print("Syncing...")
        os.sync()
        print("Done writing.")

        if not skip_overlay_wipe:
            _clear_stale_overlay(device)

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

    if gzip_return != 0:
        raise subprocess.CalledProcessError(gzip_return, ["gzip", "-dc", image_path])
    if dd_return != 0:
        raise subprocess.CalledProcessError(dd_return, ["dd", f"of={device}"])


def _clear_stale_overlay(device: str) -> None:
    wipe_range = get_partition2_wipe_range(device)
    if not wipe_range:
        print(
            "Warning: Could not determine partition 2 layout; "
            "skipping stale overlay wipe."
        )
        return

    start_bytes, wipe_bytes = wipe_range
    block_size = _OVERLAY_WIPE_BLOCK_MIB * 1024 * 1024
    seek_blocks = start_bytes // block_size
    count = max(1, wipe_bytes // block_size)
    total_mib = (count * _OVERLAY_WIPE_BLOCK_MIB)
    print(
        f"Clearing stale OpenWrt overlay area ({total_mib} MiB at offset {start_bytes} bytes)..."
    )
    subprocess.run(
        [
            "dd",
            "if=/dev/zero",
            f"of={device}",
            f"bs={_OVERLAY_WIPE_BLOCK_MIB}m",
            f"seek={seek_blocks}",
            f"count={count}",
            "status=progress",
        ],
        check=True,
    )


def _write_raw_via_dd(image_path: str, device: str) -> None:
    subprocess.run(
        [
            "dd",
            f"if={image_path}",
            f"of={device}",
            "bs=16m",
            "status=progress",
        ],
        check=True,
    )


def finish_flash(device: str, eject: bool = True) -> None:
    os.sync()
    if eject:
        print(f"Ejecting {device}...")
        eject_disk(device)
    print("Safe to remove.")
