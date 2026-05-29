"""Tests for image validation before flashing."""

import gzip
import subprocess

import pytest

from easymanet.image import (
    FlashError,
    _check_image,
    _clear_stale_overlay,
    _write_gz_via_dd,
    _write_raw_via_dd,
    flash_image,
)


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


def test_clear_stale_overlay_skips_trailing_metadata_gzip_when_payload_covers_region(
    monkeypatch, capsys, tmp_path
):
    payload = b"x" * 4096
    image = tmp_path / "openmanet.img.gz"
    with gzip.open(image, "wb") as f:
        f.write(payload)
    with image.open("ab") as f:
        f.write(b'{"metadata": "openwrt sysupgrade trailer"}')

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

    _clear_stale_overlay("/dev/disk4", written)
    captured = capsys.readouterr()
    assert "Skipping stale overlay wipe" in captured.out


def subprocess_completed():
    class Result:
        returncode = 0

    return Result()


def test_check_image_rejects_corrupt_gzip(tmp_path):
    image = tmp_path / "openmanet.img.gz"
    with gzip.open(image, "wb") as f:
        f.write(b"image-bytes")
    data = image.read_bytes()
    image.write_bytes(data[:-8])

    with pytest.raises(FlashError, match="Invalid gzip-compressed image"):
        _check_image(str(image))


def test_clear_stale_overlay_uses_sector_aligned_dd(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, check=False, **kwargs):
        calls.append((cmd, check))

    tail_start = 138412032
    wipe_bytes = 4500000000
    written_bytes = 64

    def fake_wipe_range(device):
        assert device == "/dev/disk4"
        return (tail_start, wipe_bytes)

    monkeypatch.setattr("easymanet.image.subprocess.run", fake_run)
    monkeypatch.setattr("easymanet.image.get_partition2_wipe_range", fake_wipe_range)
    monkeypatch.setattr("easymanet.image._reread_partition_table", lambda _d: None)

    _clear_stale_overlay("/dev/disk4", written_bytes)

    dd_calls = [c for c in calls if c[0][0] == "dd"]
    assert len(dd_calls) == 1
    cmd, check = dd_calls[0]
    assert check is True
    assert "if=/dev/zero" in cmd
    assert "of=/dev/disk4" in cmd
    assert "bs=512" in cmd
    start_bytes = max(tail_start, written_bytes)
    adjusted_wipe = wipe_bytes - (start_bytes - tail_start)
    sector_bytes = 512
    expected_seek = (start_bytes + sector_bytes - 1) // sector_bytes
    aligned_start = expected_seek * sector_bytes
    span_bytes = adjusted_wipe + (aligned_start - start_bytes)
    expected_count = max(1, (span_bytes + sector_bytes - 1) // sector_bytes)
    assert f"seek={expected_seek}" in cmd
    assert f"count={expected_count}" in cmd


def test_clear_stale_overlay_skips_when_image_covers_region(monkeypatch, capsys, tmp_path):
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

    _clear_stale_overlay("/dev/disk4", 4096)
    captured = capsys.readouterr()
    assert "Skipping stale overlay wipe" in captured.out


def test_clear_stale_overlay_raises_when_no_partition_layout(monkeypatch, tmp_path):
    monkeypatch.setattr("easymanet.image.get_partition2_wipe_range", lambda _d: None)
    monkeypatch.setattr("easymanet.image._reread_partition_table", lambda _d: None)
    monkeypatch.setattr("easymanet.image.subprocess.run", lambda *a, **k: subprocess_completed())

    with pytest.raises(FlashError, match="stale OpenWrt overlay"):
        _clear_stale_overlay("/dev/disk4", 64)


def _patch_flash_safety(monkeypatch, tmp_path):
    device = tmp_path / "fake-disk"
    device.write_bytes(b"\x00" * 65536)

    monkeypatch.setattr("easymanet.image.assert_flash_allowed", lambda _d, force=False: None)
    monkeypatch.setattr("easymanet.image.lookup_device", lambda _d: None)
    monkeypatch.setattr("easymanet.image.unmount_disk", lambda _d: None)
    monkeypatch.setattr("easymanet.image.get_partition2_wipe_range", lambda _d: (8192, 4096))
    monkeypatch.setattr("easymanet.image._reread_partition_table", lambda _d: None)
    return device


def test_write_raw_via_dd_writes_payload(tmp_path):
    device = tmp_path / "disk.img"
    device.write_bytes(b"\x00" * 4096)
    image = tmp_path / "firmware.img"
    payload = b"EASYMANET-RAW-IMAGE" * 32
    image.write_bytes(payload)

    _write_raw_via_dd(str(image), str(device))

    written = device.read_bytes()
    assert written[: len(payload)] == payload


def test_write_gz_via_dd_writes_decompressed_payload(tmp_path):
    device = tmp_path / "disk.img"
    device.write_bytes(b"\x00" * 4096)
    image = tmp_path / "firmware.img.gz"
    payload = b"EASYMANET-GZ-IMAGE" * 32
    with gzip.open(image, "wb") as handle:
        handle.write(payload)

    _write_gz_via_dd(str(image), str(device))

    written = device.read_bytes()
    assert written[: len(payload)] == payload


def test_flash_image_writes_raw_file(monkeypatch, tmp_path):
    device = _patch_flash_safety(monkeypatch, tmp_path)
    image = tmp_path / "firmware.img"
    payload = b"FLASH-RAW" * 128
    image.write_bytes(payload)

    flash_image(str(device), str(image), force=True, skip_overlay_wipe=True)

    assert device.read_bytes()[: len(payload)] == payload


def test_flash_image_writes_gzip_file(monkeypatch, tmp_path):
    device = _patch_flash_safety(monkeypatch, tmp_path)
    image = tmp_path / "firmware.img.gz"
    payload = b"FLASH-GZ" * 128
    with gzip.open(image, "wb") as handle:
        handle.write(payload)

    flash_image(str(device), str(image), force=True, skip_overlay_wipe=True)

    assert device.read_bytes()[: len(payload)] == payload


def test_write_gz_via_dd_accepts_gzip_exit_code_2(monkeypatch, tmp_path):
    device = tmp_path / "disk.img"
    image = tmp_path / "firmware.img.gz"
    with gzip.open(image, "wb") as handle:
        handle.write(b"payload")
    with image.open("ab") as handle:
        handle.write(b'{"metadata": "trailer"}')

    import io

    class FakeProc:
        def __init__(self, returncode, stdout=None):
            self.returncode = returncode
            self.stdout = stdout

        def wait(self):
            return self.returncode

    gzip_stdout = io.BytesIO(b"payload")
    procs = [FakeProc(2, gzip_stdout), FakeProc(0)]

    def fake_popen(cmd, **kwargs):
        if cmd[0] == "gzip":
            return procs[0]
        return procs[1]

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    _write_gz_via_dd(str(image), str(device))


def test_check_device_safety_requires_force_for_blocking_disk(monkeypatch):
    from easymanet import disks
    from easymanet.image import _check_device_safety

    disk = disks.DiskInfo(device="/dev/sda", is_system=True)

    def fake_assert(device, force=False):
        if not force:
            raise ValueError("Use --force to override.")
        return disk

    monkeypatch.setattr("easymanet.image.assert_flash_allowed", fake_assert)

    with pytest.raises(FlashError, match="--force"):
        _check_device_safety("/dev/sda", force=False)

    _check_device_safety("/dev/sda", force=True)
