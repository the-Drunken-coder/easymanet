"""Tests for image validation before flashing."""

import gzip
import hashlib
import io
import os
import subprocess
import sys

import pytest

from easymanet.disks import DiskInfo, capture_device_identity
from easymanet.image import (
    FlashError,
    _check_device_safety,
    _check_image,
    _clear_stale_overlay,
    _dd_device_path,
    _reread_partition_table,
    _run_dd_with_progress,
    _stream_dd_device_path,
    _unmount_or_raise,
    _write_gz_via_dd,
    _write_raw_via_dd,
    finish_flash,
    flash_image,
)

REAL_DD_TEST = pytest.mark.skipif(
    sys.platform != "linux",
    reason="spawns the host dd binary; command-line flags differ across platforms",
)


def _memory_tempfile():
    import io

    return io.BytesIO()


def test_check_image_accepts_valid_gzip(tmp_path):
    image = tmp_path / "openmanet.img.gz"
    with gzip.open(image, "wb") as f:
        f.write(b"image-bytes")

    path, written = _check_image(str(image))
    assert path == image
    assert written == len(b"image-bytes")


def test_check_image_accepts_openwrt_trailing_metadata(tmp_path):
    image = tmp_path / "openmanet.img.gz"
    with gzip.open(image, "wb") as f:
        f.write(b"image-bytes")
    with image.open("ab") as f:
        f.write(b'{"metadata": "openwrt sysupgrade trailer"}')

    path, written = _check_image(str(image))
    assert path == image
    assert written == len(b"image-bytes")


def test_check_image_counts_all_concatenated_gzip_members(tmp_path):
    image = tmp_path / "openmanet.img.gz"
    image.write_bytes(gzip.compress(b"first") + gzip.compress(b"second"))

    _, written = _check_image(str(image))

    assert written == len(b"firstsecond")


def test_check_image_accepts_payload_after_empty_gzip_member(tmp_path):
    image = tmp_path / "openmanet.img.gz"
    image.write_bytes(gzip.compress(b"") + gzip.compress(b"payload"))

    _, written = _check_image(str(image))

    assert written == len(b"payload")


@pytest.mark.parametrize("damage", ["crc", "truncated"])
def test_check_image_rejects_corrupt_later_gzip_member(tmp_path, damage):
    image = tmp_path / "openmanet.img.gz"
    corrupt_member = bytearray(gzip.compress(b"second"))
    if damage == "crc":
        corrupt_member[-1] ^= 0xFF
    else:
        del corrupt_member[-4:]
    image.write_bytes(gzip.compress(b"first") + corrupt_member)

    with pytest.raises(FlashError, match="Invalid gzip-compressed image"):
        _check_image(str(image))


def test_check_image_rejects_partial_later_gzip_member_header(tmp_path):
    image = tmp_path / "openmanet.img.gz"
    image.write_bytes(gzip.compress(b"first") + b"\x1f")

    with pytest.raises(FlashError, match="Invalid gzip-compressed image"):
        _check_image(str(image))


def test_check_image_rejects_zero_total_concatenated_payload(tmp_path):
    image = tmp_path / "openmanet.img.gz"
    image.write_bytes(gzip.compress(b"") + gzip.compress(b""))

    with pytest.raises(FlashError, match="did not contain a disk image payload"):
        _check_image(str(image))


def test_clear_stale_overlay_skips_trailing_metadata_gzip_when_payload_covers_region(
    monkeypatch, tmp_path
):
    payload = b"x" * 4096
    image = tmp_path / "openmanet.img.gz"
    with gzip.open(image, "wb") as f:
        f.write(payload)
    with image.open("ab") as f:
        f.write(b'{"metadata": "openwrt sysupgrade trailer"}')
    device = tmp_path / "device"
    device.write_bytes(b"\x00" * 8192)
    identity = capture_device_identity(str(device))

    _, written = _check_image(str(image))

    monkeypatch.setattr(
        "easymanet.image.get_partition2_wipe_range",
        lambda _d: (1024, 2048),
    )

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "dd":
            raise AssertionError("dd should not run")
        return subprocess_completed()

    monkeypatch.setattr("easymanet.image.subprocess.run", fake_run)
    monkeypatch.setattr("easymanet.image._reread_partition_table", lambda _d: None)

    events = []
    _clear_stale_overlay(
        str(device),
        written,
        device_identity=identity,
        output_identity=identity,
        emit=events.append,
    )
    assert events[-1]["type"] == "overlay_wipe_skipped"
    assert "Skipping stale overlay wipe" in events[-1]["message"]


def subprocess_completed():
    class Result:
        returncode = 0

    return Result()


def test_unmount_or_raise_does_not_wrap_programming_errors(monkeypatch):
    def fail_unmount(_device):
        raise TypeError("bug in caller")

    monkeypatch.setattr("easymanet.image.unmount_disk", fail_unmount)

    with pytest.raises(TypeError, match="bug in caller"):
        _unmount_or_raise("/dev/disk4")


def test_reread_partition_table_surfaces_command_failure(monkeypatch):
    run_calls = []

    def fail_run(cmd, **kwargs):
        run_calls.append((cmd, kwargs))
        raise subprocess.CalledProcessError(1, cmd, stderr="device busy")

    monkeypatch.setattr("easymanet.image.is_linux", lambda: True)
    monkeypatch.setattr("easymanet.image.is_macos", lambda: False)
    monkeypatch.setattr("easymanet.image._tool_path", lambda name: name)
    monkeypatch.setattr("easymanet.image.subprocess.run", fail_run)

    with pytest.raises(FlashError, match="device busy"):
        _reread_partition_table("/dev/sdb")

    assert run_calls == [
        (
            ["blockdev", "--rereadpt", "/dev/sdb"],
            {"capture_output": True, "text": True, "timeout": 30, "check": True},
        ),
        (
            ["partprobe", "/dev/sdb"],
            {"capture_output": True, "text": True, "timeout": 30, "check": True},
        ),
    ]


def test_reread_partition_table_skips_partprobe_when_blockdev_succeeds(monkeypatch):
    run_calls = []

    def fake_run(cmd, **kwargs):
        run_calls.append((cmd, kwargs))

    monkeypatch.setattr("easymanet.image.is_linux", lambda: True)
    monkeypatch.setattr("easymanet.image.is_macos", lambda: False)
    monkeypatch.setattr("easymanet.image._tool_path", lambda name: name)
    monkeypatch.setattr("easymanet.image.subprocess.run", fake_run)

    _reread_partition_table("/dev/sdb")

    assert run_calls == [
        (
            ["blockdev", "--rereadpt", "/dev/sdb"],
            {"capture_output": True, "text": True, "timeout": 30, "check": True},
        )
    ]


def test_check_image_rejects_corrupt_gzip(tmp_path):
    image = tmp_path / "openmanet.img.gz"
    with gzip.open(image, "wb") as f:
        f.write(b"image-bytes")
    data = image.read_bytes()
    image.write_bytes(data[:-8])

    with pytest.raises(FlashError, match="Invalid gzip-compressed image"):
        _check_image(str(image))


def test_clear_stale_overlay_uses_large_bulk_dd(monkeypatch, tmp_path):
    calls = []
    unmount_calls = []
    close_calls = []
    seek_calls = []
    identity = object()

    def fake_run(cmd, check=False, **kwargs):
        calls.append((cmd, check, kwargs))

    def fake_unmount(device):
        unmount_calls.append(device)

    tail_start = 138412032
    wipe_bytes = 4500000000
    written_bytes = 64

    def fake_wipe_range(device):
        assert device == "/dev/disk4"
        return (tail_start, wipe_bytes)

    monkeypatch.setattr("easymanet.image.subprocess.run", fake_run)
    monkeypatch.setattr("easymanet.image.unmount_disk", fake_unmount)
    monkeypatch.setattr("easymanet.image.get_partition2_wipe_range", fake_wipe_range)
    monkeypatch.setattr("easymanet.image._reread_partition_table", lambda _d: None)
    monkeypatch.setattr("easymanet.image._assert_device_identity", lambda _identity: None)
    monkeypatch.setattr(
        "easymanet.image._open_device_for_write",
        lambda _identity, companions=(): 42,
    )
    monkeypatch.setattr("easymanet.image.os.close", close_calls.append)
    monkeypatch.setattr(
        "easymanet.image.os.lseek",
        lambda fd, offset, whence: seek_calls.append((fd, offset, whence)),
    )
    monkeypatch.setattr("easymanet.image._tool_path", lambda name: name)

    _clear_stale_overlay(
        "/dev/disk4",
        written_bytes,
        device_identity=identity,
        output_identity=identity,
    )

    start_bytes = max(tail_start, written_bytes)
    adjusted_wipe = wipe_bytes - (start_bytes - tail_start)
    sector_bytes = 512
    bulk_bytes = 16 * 1024 * 1024
    expected_seek = (start_bytes + sector_bytes - 1) // sector_bytes
    aligned_start = expected_seek * sector_bytes
    span_bytes = adjusted_wipe + (aligned_start - start_bytes)
    expected_count = max(1, (span_bytes + sector_bytes - 1) // sector_bytes)
    expected_total_bytes = expected_count * sector_bytes
    expected_prefix_bytes = bulk_bytes - (aligned_start % bulk_bytes)
    expected_bulk_blocks = (expected_total_bytes - expected_prefix_bytes) // bulk_bytes
    expected_tail_bytes = expected_total_bytes - expected_prefix_bytes - (
        expected_bulk_blocks * bulk_bytes
    )
    expected_tail_seek = (
        aligned_start + expected_prefix_bytes + expected_bulk_blocks * bulk_bytes
    ) // sector_bytes

    dd_calls = [call for call in calls if call[0][0] == "dd"]
    assert len(dd_calls) == 3
    assert unmount_calls == ["/dev/disk4"]
    assert close_calls == [42]
    assert seek_calls == [(42, 0, os.SEEK_SET)] * 3
    prefix, bulk, tail = dd_calls
    assert all(check is True for _, check, _kwargs in dd_calls)
    assert all(kwargs["stdout"] == 42 for _cmd, _check, kwargs in dd_calls)
    assert "if=/dev/zero" in prefix[0]
    assert not any(arg.startswith("of=") for arg in prefix[0])
    assert f"bs={sector_bytes}" in prefix[0]
    assert f"seek={expected_seek}" in prefix[0]
    assert f"count={expected_prefix_bytes // sector_bytes}" in prefix[0]
    assert f"bs={bulk_bytes}" in bulk[0]
    assert f"seek={(aligned_start + expected_prefix_bytes) // bulk_bytes}" in bulk[0]
    assert f"count={expected_bulk_blocks}" in bulk[0]
    assert f"bs={sector_bytes}" in tail[0]
    assert f"seek={expected_tail_seek}" in tail[0]
    assert f"count={expected_tail_bytes // sector_bytes}" in tail[0]


def test_clear_stale_overlay_places_each_dd_phase_at_absolute_offset(monkeypatch, tmp_path):
    device = tmp_path / "device"
    device.write_bytes(b"x" * 4096)
    identity = capture_device_identity(str(device))
    dd_calls = []

    def emulate_dd(cmd, check=False, stdout=None, **_kwargs):
        assert check is True
        assert stdout is not None
        args = dict(arg.split("=", 1) for arg in cmd[1:] if "=" in arg)
        block_bytes = int(args["bs"])
        seek_blocks = int(args["seek"])
        count_blocks = int(args["count"])
        os.lseek(stdout, seek_blocks * block_bytes, os.SEEK_CUR)
        os.write(stdout, b"\x00" * block_bytes * count_blocks)
        dd_calls.append(cmd)

    monkeypatch.setattr("easymanet.image._OVERLAY_WIPE_SECTOR_BYTES", 1)
    monkeypatch.setattr("easymanet.image._OVERLAY_WIPE_BULK_BYTES", 1024)
    monkeypatch.setattr("easymanet.image._reread_partition_table", lambda _d: None)
    monkeypatch.setattr(
        "easymanet.image.get_partition2_wipe_range",
        lambda _d: (10, 2050),
    )
    monkeypatch.setattr("easymanet.image.unmount_disk", lambda _d: None)
    monkeypatch.setattr("easymanet.image._tool_path", lambda name: name)
    monkeypatch.setattr("easymanet.image.subprocess.run", emulate_dd)

    _clear_stale_overlay(
        str(device),
        0,
        device_identity=identity,
        output_identity=identity,
    )

    written = device.read_bytes()
    assert len(dd_calls) == 3
    assert written[:10] == b"x" * 10
    assert written[10:2060] == b"\x00" * 2050
    assert written[2060:] == b"x" * (4096 - 2060)


def test_clear_stale_overlay_rejects_replacement_during_layout_reread(
    monkeypatch, tmp_path
):
    original = tmp_path / "original-device"
    replacement = tmp_path / "replacement-device"
    selected = tmp_path / "selected-device"
    original.write_bytes(b"original")
    replacement.write_bytes(b"replacement")
    selected.symlink_to(original)
    identity = capture_device_identity(str(selected))

    def replace_during_reread(_device):
        selected.unlink()
        selected.symlink_to(replacement)

    monkeypatch.setattr(
        "easymanet.image._reread_partition_table",
        replace_during_reread,
    )
    monkeypatch.setattr(
        "easymanet.image.get_partition2_wipe_range",
        lambda _d: pytest.fail("replacement layout must not be queried"),
    )
    monkeypatch.setattr(
        "easymanet.image.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("replacement device must not be zeroed"),
    )

    with pytest.raises(FlashError, match="Device identity changed"):
        _clear_stale_overlay(
            str(selected),
            0,
            device_identity=identity,
            output_identity=identity,
        )


def test_dd_device_path_uses_raw_disk_on_macos(monkeypatch):
    monkeypatch.setattr("easymanet.image.is_macos", lambda: True)

    assert _dd_device_path("/dev/disk4") == "/dev/rdisk4"
    assert _dd_device_path("/tmp/disk.img") == "/tmp/disk.img"


def test_stream_dd_device_path_uses_buffered_disk_on_macos(monkeypatch):
    monkeypatch.setattr("easymanet.image.is_macos", lambda: True)

    assert _stream_dd_device_path("/dev/disk4") == "/dev/disk4"
    assert _stream_dd_device_path("/dev/rdisk4") == "/dev/disk4"


def test_dd_device_path_keeps_device_on_non_macos(monkeypatch):
    monkeypatch.setattr("easymanet.image.is_macos", lambda: False)

    assert _dd_device_path("/dev/disk4") == "/dev/disk4"


def test_clear_stale_overlay_skips_when_image_covers_region(monkeypatch, tmp_path):
    device = tmp_path / "device"
    device.write_bytes(b"\x00" * 8192)
    identity = capture_device_identity(str(device))
    monkeypatch.setattr(
        "easymanet.image.get_partition2_wipe_range",
        lambda _d: (1024, 2048),
    )
    monkeypatch.setattr("easymanet.image._reread_partition_table", lambda _d: None)

    def fake_run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "dd":
            raise AssertionError("dd should not run")
        return subprocess_completed()

    monkeypatch.setattr("easymanet.image.subprocess.run", fake_run)

    events = []
    _clear_stale_overlay(
        str(device),
        4096,
        device_identity=identity,
        output_identity=identity,
        emit=events.append,
    )
    assert events[-1]["type"] == "overlay_wipe_skipped"
    assert "Skipping stale overlay wipe" in events[-1]["message"]


def test_clear_stale_overlay_raises_when_no_partition_layout(monkeypatch, tmp_path):
    device = tmp_path / "device"
    device.write_bytes(b"\x00" * 8192)
    identity = capture_device_identity(str(device))
    monkeypatch.setattr("easymanet.image.get_partition2_wipe_range", lambda _d: None)
    monkeypatch.setattr("easymanet.image._reread_partition_table", lambda _d: None)
    monkeypatch.setattr("easymanet.image.subprocess.run", lambda *a, **k: subprocess_completed())

    with pytest.raises(FlashError, match="stale OpenWrt overlay"):
        _clear_stale_overlay(
            str(device),
            64,
            device_identity=identity,
            output_identity=identity,
        )


def _patch_flash_safety(monkeypatch, tmp_path):
    device = tmp_path / "fake-disk"
    device.write_bytes(b"\x00" * 65536)

    monkeypatch.setattr(
        "easymanet.image.assert_flash_allowed",
        lambda _d, force=False: DiskInfo(str(device), removable=True),
    )
    monkeypatch.setattr("easymanet.image.unmount_disk", lambda _d: None)
    monkeypatch.setattr("easymanet.image.get_partition2_wipe_range", lambda _d: (8192, 4096))
    monkeypatch.setattr("easymanet.image._reread_partition_table", lambda _d: None)
    return device


def test_flash_image_dry_run_emits_disk_details(monkeypatch, tmp_path):
    device = _patch_flash_safety(monkeypatch, tmp_path)
    image = tmp_path / "firmware.img"
    image.write_bytes(b"FLASH" * 64)
    events = []

    flash_image(str(device), str(image), dry_run=True, force=True, emit=events.append)

    assert events == [
        {
            "type": "disk_details",
            "message": f"Device: {device}",
            "device": str(device),
            "model": "",
            "size_human": "0.0 MB",
            "mounted": [],
            "removable": True,
        }
    ]


@REAL_DD_TEST
def test_write_raw_via_dd_writes_payload(tmp_path):
    device = tmp_path / "disk.img"
    device.write_bytes(b"\x00" * 4096)
    image = tmp_path / "firmware.img"
    payload = b"EASYMANET-RAW-IMAGE" * 32
    image.write_bytes(payload)

    image_fd = os.open(image, os.O_RDONLY)
    device_fd = os.open(device, os.O_WRONLY)
    try:
        _write_raw_via_dd(image_fd, device_fd)
    finally:
        os.close(device_fd)
        os.close(image_fd)

    written = device.read_bytes()
    assert written[: len(payload)] == payload


@REAL_DD_TEST
def test_write_gz_via_dd_writes_decompressed_payload(tmp_path):
    device = tmp_path / "disk.img"
    device.write_bytes(b"\x00" * 4096)
    image = tmp_path / "firmware.img.gz"
    payload = b"EASYMANET-GZ-IMAGE" * 32
    with gzip.open(image, "wb") as handle:
        handle.write(payload)

    image_fd = os.open(image, os.O_RDONLY)
    device_fd = os.open(device, os.O_WRONLY)
    try:
        _write_gz_via_dd(image_fd, device_fd)
    finally:
        os.close(device_fd)
        os.close(image_fd)

    written = device.read_bytes()
    assert written[: len(payload)] == payload


@REAL_DD_TEST
def test_flash_image_writes_raw_file(monkeypatch, tmp_path):
    device = _patch_flash_safety(monkeypatch, tmp_path)
    image = tmp_path / "firmware.img"
    payload = b"FLASH-RAW" * 128
    image.write_bytes(payload)

    flash_image(str(device), str(image), force=True, skip_overlay_wipe=True)

    assert device.read_bytes()[: len(payload)] == payload


def test_flash_image_passes_retained_identity_to_overlay_wipe(monkeypatch, tmp_path):
    device = _patch_flash_safety(monkeypatch, tmp_path)
    image = tmp_path / "firmware.img"
    image.write_bytes(b"FLASH" * 64)
    unmount_calls = []
    overlay_calls = []

    monkeypatch.setattr(
        "easymanet.image.unmount_disk",
        lambda d: unmount_calls.append(d),
    )
    monkeypatch.setattr("easymanet.image._write_raw_via_dd", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "easymanet.image._clear_stale_overlay",
        lambda *args, **kwargs: overlay_calls.append((args, kwargs)),
    )
    monkeypatch.setattr("os.sync", lambda: None)

    flash_image(str(device), str(image), force=True)

    assert unmount_calls == [str(device)]
    assert overlay_calls[0][0] == (str(device), image.stat().st_size)
    assert overlay_calls[0][1]["device_identity"].path == str(device)
    assert overlay_calls[0][1]["output_identity"].path == str(device)


def test_flash_image_wraps_initial_unmount_failure(monkeypatch, tmp_path):
    device = _patch_flash_safety(monkeypatch, tmp_path)
    image = tmp_path / "firmware.img"
    image.write_bytes(b"FLASH" * 64)

    def fail_unmount(_device):
        raise RuntimeError("target is busy")

    def unexpected_write(*_args):
        raise AssertionError("flash should not write after unmount failure")

    monkeypatch.setattr("easymanet.image.unmount_disk", fail_unmount)
    monkeypatch.setattr("easymanet.image._write_raw_via_dd", unexpected_write)

    with pytest.raises(FlashError, match="Failed to unmount"):
        flash_image(str(device), str(image), force=True, skip_overlay_wipe=True)


def test_flash_image_rejects_device_replacement_after_unmount(monkeypatch, tmp_path):
    original = tmp_path / "original-disk"
    replacement = tmp_path / "replacement-disk"
    selected = tmp_path / "selected-disk"
    image = tmp_path / "firmware.img"
    original.write_bytes(b"original")
    replacement.write_bytes(b"replacement")
    selected.symlink_to(original)
    image.write_bytes(b"FLASH" * 64)

    monkeypatch.setattr(
        "easymanet.image.assert_flash_allowed",
        lambda _device, force=False: DiskInfo(str(selected), removable=True),
    )

    def replace_selected_path(_device):
        selected.unlink()
        selected.symlink_to(replacement)

    monkeypatch.setattr("easymanet.image.unmount_disk", replace_selected_path)
    monkeypatch.setattr(
        "easymanet.image._write_raw_via_dd",
        lambda *_args, **_kwargs: pytest.fail("replacement device must not be written"),
    )

    with pytest.raises(FlashError, match="Device identity changed"):
        flash_image(str(selected), str(image), force=True, skip_overlay_wipe=True)

    assert original.read_bytes() == b"original"
    assert replacement.read_bytes() == b"replacement"


def test_flash_image_rejects_expected_sha_before_safety_or_write(monkeypatch, tmp_path):
    image = tmp_path / "firmware.img"
    image.write_bytes(b"verified bytes")

    monkeypatch.setattr(
        "easymanet.image._check_device_safety",
        lambda *_args, **_kwargs: pytest.fail("disk safety must not run"),
    )
    monkeypatch.setattr(
        "easymanet.image._write_raw_via_dd",
        lambda *_args, **_kwargs: pytest.fail("mismatched image must not be written"),
    )

    with pytest.raises(FlashError, match="SHA-256 mismatch"):
        flash_image(
            "/dev/disk4",
            str(image),
            expected_sha256=hashlib.sha256(b"other bytes").hexdigest(),
        )


def test_flash_image_writes_opened_verified_image_after_path_replacement(
    monkeypatch, tmp_path
):
    device = _patch_flash_safety(monkeypatch, tmp_path)
    image = tmp_path / "firmware.img"
    verified_payload = b"verified image payload"
    replacement_payload = b"replacement image payload"
    image.write_bytes(verified_payload)
    expected_sha256 = hashlib.sha256(verified_payload).hexdigest()
    written = []

    def replace_image_after_open(device_path, force=False):
        checked = _check_device_safety(device_path, force=force)
        image.unlink()
        image.write_bytes(replacement_payload)
        return checked

    def capture_opened_image(image_fd, _device_fd, **_kwargs):
        written.append(os.pread(image_fd, 4096, 0))

    monkeypatch.setattr(
        "easymanet.image._check_device_safety",
        replace_image_after_open,
    )
    monkeypatch.setattr("easymanet.image._write_raw_via_dd", capture_opened_image)
    monkeypatch.setattr("easymanet.image.os.sync", lambda: None)

    flash_image(
        str(device),
        str(image),
        force=True,
        skip_overlay_wipe=True,
        expected_sha256=expected_sha256,
    )

    assert written == [verified_payload]
    assert image.read_bytes() == replacement_payload


def test_finish_flash_raises_when_eject_fails(monkeypatch, tmp_path):
    device = tmp_path / "disk"
    device.write_bytes(b"disk")
    identity = capture_device_identity(str(device))
    monkeypatch.setattr("easymanet.image.os.sync", lambda: None)

    def fail_eject(_device):
        raise RuntimeError("eject failed")

    monkeypatch.setattr("easymanet.image.eject_disk", fail_eject)

    events = []
    with pytest.raises(FlashError, match="Failed to eject"):
        finish_flash(
            str(device),
            device_identity=identity,
            emit=events.append,
        )

    messages = [event["message"] for event in events]
    assert any(f"eject {device} manually" in message for message in messages)
    assert "Safe to remove." not in messages


def test_finish_flash_raises_when_eject_times_out(monkeypatch, tmp_path):
    device = tmp_path / "disk"
    device.write_bytes(b"disk")
    identity = capture_device_identity(str(device))
    monkeypatch.setattr("easymanet.image.os.sync", lambda: None)

    def fail_eject(_device):
        raise subprocess.TimeoutExpired(["eject", "/dev/disk4"], timeout=30)

    monkeypatch.setattr("easymanet.image.eject_disk", fail_eject)

    events = []
    with pytest.raises(FlashError, match="Failed to eject"):
        finish_flash(
            str(device),
            device_identity=identity,
            emit=events.append,
        )

    messages = [event["message"] for event in events]
    assert any(f"eject {device} manually" in message for message in messages)
    assert "Safe to remove." not in messages


def test_finish_flash_no_eject_unmounts_before_reporting_safe(monkeypatch, tmp_path):
    device = tmp_path / "disk"
    device.write_bytes(b"disk")
    identity = capture_device_identity(str(device))
    calls = []
    monkeypatch.setattr("easymanet.image.os.sync", lambda: calls.append("sync"))
    monkeypatch.setattr(
        "easymanet.image.unmount_disk",
        lambda device: calls.append(("unmount", device)),
    )
    events = []

    result = finish_flash(
        str(device),
        device_identity=identity,
        eject=False,
        emit=events.append,
    )

    assert result is None
    assert calls == ["sync", ("unmount", str(device))]
    assert [event["type"] for event in events] == ["unmount_started", "safe_to_remove"]


def test_finish_flash_no_eject_propagates_unmount_failure(monkeypatch, tmp_path):
    device = tmp_path / "disk"
    device.write_bytes(b"disk")
    identity = capture_device_identity(str(device))
    monkeypatch.setattr("easymanet.image.os.sync", lambda: None)
    monkeypatch.setattr(
        "easymanet.image.unmount_disk",
        lambda _device: (_ for _ in ()).throw(RuntimeError("busy")),
    )
    events = []

    with pytest.raises(FlashError, match="Failed to unmount"):
        finish_flash(
            str(device),
            device_identity=identity,
            eject=False,
            emit=events.append,
        )

    assert [event["type"] for event in events] == [
        "unmount_started",
        "unmount_failed",
    ]
    assert all(event["type"] != "safe_to_remove" for event in events)


@pytest.mark.parametrize("eject", [True, False])
def test_finish_flash_rejects_device_replacement_before_cleanup(
    monkeypatch, tmp_path, eject
):
    original = tmp_path / "original-disk"
    replacement = tmp_path / "replacement-disk"
    selected = tmp_path / "selected-disk"
    original.write_bytes(b"original")
    replacement.write_bytes(b"replacement")
    selected.symlink_to(original)
    identity = capture_device_identity(str(selected))

    def replace_during_sync():
        selected.unlink()
        selected.symlink_to(replacement)

    monkeypatch.setattr("easymanet.image.os.sync", replace_during_sync)
    monkeypatch.setattr(
        "easymanet.image.eject_disk",
        lambda _device: pytest.fail("replacement target must not be ejected"),
    )
    monkeypatch.setattr(
        "easymanet.image.unmount_disk",
        lambda _device: pytest.fail("replacement target must not be unmounted"),
    )

    with pytest.raises(FlashError, match="Device identity changed"):
        finish_flash(
            str(selected),
            device_identity=identity,
            eject=eject,
        )


@REAL_DD_TEST
def test_flash_image_writes_gzip_file(monkeypatch, tmp_path):
    device = _patch_flash_safety(monkeypatch, tmp_path)
    image = tmp_path / "firmware.img.gz"
    payload = b"FLASH-GZ" * 128
    with gzip.open(image, "wb") as handle:
        handle.write(payload)

    flash_image(str(device), str(image), force=True, skip_overlay_wipe=True)

    assert device.read_bytes()[: len(payload)] == payload


def test_write_gz_via_dd_accepts_gzip_exit_code_2(monkeypatch, tmp_path):
    image = tmp_path / "firmware.img.gz"
    with gzip.open(image, "wb") as handle:
        handle.write(b"payload")
    with image.open("ab") as handle:
        handle.write(b'{"metadata": "trailer"}')

    class FakeProc:
        def __init__(self, returncode, stdout=None):
            self.returncode = returncode
            self.stdout = stdout

        def communicate(self):
            return ("", "")

        def wait(self):
            return self.returncode

    gzip_stdout = io.BytesIO(b"payload")
    procs = [FakeProc(2, gzip_stdout), FakeProc(0)]
    popen_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        if cmd[0] == "gzip":
            kwargs["stderr"].write(b"gzip: trailing garbage ignored\n")
            return procs[0]
        return procs[1]

    monkeypatch.setattr("easymanet.image.is_macos", lambda: False)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("easymanet.image._tool_path", lambda name: name)

    image_fd = os.open(image, os.O_RDONLY)
    try:
        _write_gz_via_dd(image_fd, 42)
    finally:
        os.close(image_fd)

    assert popen_calls[0][0] == ["gzip", "-dc"]
    assert popen_calls[0][1]["stdin"] == image_fd
    assert popen_calls[0][1]["stdout"] is subprocess.PIPE
    assert popen_calls[1] == (
        ["dd", "bs=16M", "status=progress"],
        {
            "stdin": gzip_stdout,
            "stdout": 42,
            "stderr": subprocess.PIPE,
            "text": True,
        },
    )
    assert gzip_stdout.closed is True


def test_write_gz_via_dd_uses_unpadded_buffered_stream_on_macos(monkeypatch, tmp_path):
    image = tmp_path / "firmware.img.gz"
    with gzip.open(image, "wb") as handle:
        handle.write(b"payload")

    import io

    class FakeProc:
        def __init__(self, returncode, stdout=None):
            self.returncode = returncode
            self.stdout = stdout
            self.killed = False

        def communicate(self):
            return (b"", b"")

        def wait(self):
            return self.returncode

        def kill(self):
            self.killed = True

    full_chunk = b"a" * (1024 * 1024)
    tail = b"tail"

    class ShortReadStream:
        def __init__(self, chunks):
            self.chunks = list(chunks)

        def read(self, _size):
            if not self.chunks:
                return b""
            return self.chunks.pop(0)

    gzip_stdout = ShortReadStream([full_chunk, tail])
    procs = [FakeProc(0, gzip_stdout)]
    popen_calls = []
    writes = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        if cmd[0] == "gzip":
            return procs[0]
        raise AssertionError(f"dd should not run on macOS gzip streams: {cmd}")

    def fake_write(fd, payload) -> int:
        assert fd == 42
        writes.append(bytes(payload))
        if len(writes) == 1:
            return len(payload) // 2
        return len(payload)

    monkeypatch.setattr("easymanet.image.is_macos", lambda: True)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("easymanet.image._tool_path", lambda name: name)
    monkeypatch.setattr("easymanet.image.tempfile.TemporaryFile", _memory_tempfile)
    monkeypatch.setattr("easymanet.image.os.write", fake_write)

    image_fd = os.open(image, os.O_RDONLY)
    try:
        _write_gz_via_dd(image_fd, 42)
    finally:
        os.close(image_fd)

    assert len(popen_calls) == 1
    assert popen_calls[0][0] == ["gzip", "-dc"]
    assert popen_calls[0][1]["stdin"] == image_fd
    assert popen_calls[0][1]["stdout"] is subprocess.PIPE
    assert popen_calls[0][1]["stderr"] is not subprocess.DEVNULL
    assert writes == [full_chunk, full_chunk[len(full_chunk) // 2 :], tail]
    assert len(writes[-1]) < 512


def test_write_gz_via_dd_accepts_gzip_exit_code_2_on_macos(monkeypatch, tmp_path):
    image = tmp_path / "firmware.img.gz"
    with gzip.open(image, "wb") as handle:
        handle.write(b"payload")

    import io

    class FakeProc:
        def __init__(self, returncode, stdout=None):
            self.returncode = returncode
            self.stdout = stdout
            self.killed = False

        def communicate(self):
            return (b"", b"gzip: trailing garbage ignored\n")

        def wait(self):
            return self.returncode

        def kill(self):
            self.killed = True

    gzip_stdout = io.BytesIO(b"payload")
    procs = [FakeProc(2, stdout=gzip_stdout)]

    def fake_popen(cmd, **kwargs):
        if cmd[0] == "gzip":
            kwargs["stderr"].write(b"gzip: trailing garbage ignored\n")
            return procs[0]
        raise AssertionError(f"dd should not run on macOS gzip streams: {cmd}")

    writes = []

    monkeypatch.setattr("easymanet.image.is_macos", lambda: True)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("easymanet.image._tool_path", lambda name: name)
    monkeypatch.setattr("easymanet.image.tempfile.TemporaryFile", _memory_tempfile)
    monkeypatch.setattr(
        "easymanet.image.os.write",
        lambda _fd, payload: writes.append(bytes(payload)) or len(payload),
    )

    image_fd = os.open(image, os.O_RDONLY)
    try:
        _write_gz_via_dd(image_fd, 42)
    finally:
        os.close(image_fd)

    assert writes == [b"payload"]


def test_write_gz_via_dd_reports_macos_buffered_write_failure(monkeypatch, tmp_path):
    image = tmp_path / "firmware.img.gz"
    with gzip.open(image, "wb") as handle:
        handle.write(b"payload")

    import io

    class FakeProc:
        def __init__(self, returncode, stdout=None):
            self.returncode = returncode
            self.stdout = stdout
            self.killed = False
            self.communicated = False

        def communicate(self):
            self.communicated = True
            return (b"", b"")

        def kill(self):
            self.killed = True

    gzip_stdout = io.BytesIO(b"payload")
    proc = FakeProc(-13, stdout=gzip_stdout)

    def fake_popen(cmd, **_kwargs):
        if cmd[0] == "gzip":
            return proc
        raise AssertionError(f"dd should not run on macOS gzip streams: {cmd}")

    monkeypatch.setattr("easymanet.image.is_macos", lambda: True)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("easymanet.image._tool_path", lambda name: name)
    monkeypatch.setattr("easymanet.image.tempfile.TemporaryFile", _memory_tempfile)
    monkeypatch.setattr(
        "easymanet.image.os.write",
        lambda _fd, _payload: (_ for _ in ()).throw(OSError("raw write failed")),
    )

    with pytest.raises(OSError, match="raw write failed"):
        image_fd = os.open(image, os.O_RDONLY)
        try:
            _write_gz_via_dd(image_fd, 42)
        finally:
            os.close(image_fd)

    assert proc.killed is True
    assert proc.communicated is True


def test_write_gz_via_dd_reports_macos_gzip_stderr(monkeypatch, tmp_path):
    image = tmp_path / "firmware.img.gz"
    with gzip.open(image, "wb") as handle:
        handle.write(b"payload")

    import io

    class FakeProc:
        def __init__(self):
            self.returncode = 1
            self.stdout = io.BytesIO(b"")

        def communicate(self):
            return (b"", b"")

    def fake_popen(_cmd, **kwargs):
        kwargs["stderr"].write(b"gzip: corrupt input\n")
        kwargs["stderr"].flush()
        return FakeProc()

    monkeypatch.setattr("easymanet.image.is_macos", lambda: True)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("easymanet.image._tool_path", lambda name: name)
    monkeypatch.setattr("easymanet.image.tempfile.TemporaryFile", _memory_tempfile)
    monkeypatch.setattr("easymanet.image.os.write", lambda _fd, payload: len(payload))

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        image_fd = os.open(image, os.O_RDONLY)
        try:
            _write_gz_via_dd(image_fd, 42)
        finally:
            os.close(image_fd)

    assert "gzip: corrupt input" in exc_info.value.stderr


def test_write_raw_via_dd_uses_macos_dd_block_suffix(monkeypatch, tmp_path):
    image = tmp_path / "firmware.img"
    image.write_bytes(b"payload")
    run_calls = []

    def fake_run(cmd, **kwargs):
        run_calls.append((cmd, kwargs))

    monkeypatch.setattr("easymanet.image.is_macos", lambda: True)
    monkeypatch.setattr("easymanet.image.subprocess.run", fake_run)
    monkeypatch.setattr("easymanet.image._tool_path", lambda name: name)

    image_fd = os.open(image, os.O_RDONLY)
    try:
        _write_raw_via_dd(image_fd, 42)
    finally:
        os.close(image_fd)

    assert run_calls == [
        (
            ["dd", "bs=16m", "status=progress"],
            {"check": True, "stdin": image_fd, "stdout": 42},
        )
    ]


def test_run_dd_with_progress_emits_parsed_byte_count(monkeypatch):
    import io

    class FakeProc:
        stderr = io.StringIO("1048576 bytes transferred\n")

        def wait(self):
            return 0

    monkeypatch.setattr("easymanet.image.subprocess.Popen", lambda *_a, **_k: FakeProc())
    events = []

    _run_dd_with_progress(["dd", "if=image", "of=device"], emit=events.append)

    assert events == [
        {
            "type": "dd_progress",
            "message": "1048576 bytes transferred",
            "raw": "1048576 bytes transferred",
            "bytes": 1048576,
        }
    ]


def test_check_device_safety_requires_force_for_blocking_disk(monkeypatch, tmp_path):
    from easymanet import disks

    device = tmp_path / "device"
    device.write_bytes(b"device")
    disk = disks.DiskInfo(device=str(device), is_system=True)

    def fake_assert(device, force=False):
        if not force:
            raise ValueError("Use --force to override.")
        return disk

    monkeypatch.setattr("easymanet.image.assert_flash_allowed", fake_assert)

    with pytest.raises(FlashError, match="--force"):
        _check_device_safety(str(device), force=False)

    checked_disk, identity = _check_device_safety(str(device), force=True)
    assert checked_disk is disk
    assert identity.path == str(device)


def test_check_device_safety_binds_metadata_to_same_device_instance(monkeypatch, tmp_path):
    original = tmp_path / "original-device"
    replacement = tmp_path / "replacement-device"
    selected = tmp_path / "selected-device"
    original.write_bytes(b"original")
    replacement.write_bytes(b"replacement")
    selected.symlink_to(original)

    def replace_during_safety_check(_device, force=False):
        selected.unlink()
        selected.symlink_to(replacement)
        return DiskInfo(device=str(selected), removable=True)

    monkeypatch.setattr(
        "easymanet.image.assert_flash_allowed",
        replace_during_safety_check,
    )

    with pytest.raises(FlashError, match="Device identity changed"):
        _check_device_safety(str(selected), force=True)
