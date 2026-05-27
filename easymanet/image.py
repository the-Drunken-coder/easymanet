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
            _clear_stale_overlay(device, image)

    except subprocess.CalledProcessError as e:
        raise FlashError(f"Flash failed: {e}") from e
    except Exception as e:
        raise FlashError(f"Flash failed: {e}") from e


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

    # OpenWrt/OpenMANET sysupgrade metadata after the gzip stream can yield exit 2
    # ("trailing garbage ignored"); payload integrity is validated by _check_gzip_payload.
    if gzip_return not in (0, 2):
        raise subprocess.CalledProcessError(gzip_return, ["gzip", "-dc", image_path])
    if dd_return != 0:
        raise subprocess.CalledProcessError(dd_return, ["dd", f"of={device}"])


_OVERLAY_WIPE_SECTOR_BYTES = 512


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def _written_image_bytes(image: Path) -> int:
    if image.suffix.lower() == ".gz":
        proc = subprocess.run(
            ["gzip", "-l", str(image)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            lines = proc.stdout.strip().splitlines()
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 2:
                    return int(parts[1])
    return image.stat().st_size


def _clear_stale_overlay(device: str, image: Path) -> None:
    wipe_range = get_partition2_wipe_range(device)
    if not wipe_range:
        print(
            "Warning: Could not determine partition 2 layout; "
            "skipping stale overlay wipe."
        )
        return

    tail_start, wipe_bytes = wipe_range
    written_end = _written_image_bytes(image)
    start_bytes = max(tail_start, written_end)
    wipe_bytes = wipe_bytes - (start_bytes - tail_start)
    if wipe_bytes <= 0:
        print("Skipping stale overlay wipe; image covers the wipe region.")
        return
    sector_bytes = _OVERLAY_WIPE_SECTOR_BYTES
    seek_sectors = _ceil_div(start_bytes, sector_bytes)
    aligned_start = seek_sectors * sector_bytes
    span_bytes = wipe_bytes + (aligned_start - start_bytes)
    count_sectors = max(1, _ceil_div(span_bytes, sector_bytes))
    total_mib = count_sectors * sector_bytes / (1024 * 1024)
    print(
        f"Clearing stale OpenWrt overlay area ({total_mib:.1f} MiB at offset {start_bytes} bytes)..."
    )
    subprocess.run(
        [
            "dd",
            "if=/dev/zero",
            f"of={device}",
            f"bs={sector_bytes}",
            f"seek={seek_sectors}",
            f"count={count_sectors}",
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
