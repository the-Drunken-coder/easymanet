"""Tests for image validation before flashing."""

import gzip

import pytest

from easymanet.image import (
    FlashError,
    _check_image,
    _clear_stale_overlay,
    _written_image_bytes,
)


def test_check_image_accepts_valid_gzip(tmp_path):
    image = tmp_path / "openmanet.img.gz"
    with gzip.open(image, "wb") as f:
        f.write(b"image-bytes")

    assert _check_image(str(image)) == image


def test_check_image_accepts_openwrt_trailing_metadata(tmp_path):
    image = tmp_path / "openmanet.img.gz"
    with gzip.open(image, "wb") as f:
        f.write(b"image-bytes")
    with image.open("ab") as f:
        f.write(b'{"metadata": "openwrt sysupgrade trailer"}')

    assert _check_image(str(image)) == image


def test_written_image_bytes_counts_decompressed_payload_with_trailing_metadata(tmp_path):
    payload = b"image-bytes"
    image = tmp_path / "openmanet.img.gz"
    with gzip.open(image, "wb") as f:
        f.write(payload)
    with image.open("ab") as f:
        f.write(b'{"metadata": "openwrt sysupgrade trailer"}')

    assert _written_image_bytes(image) == len(payload)
    assert _written_image_bytes(image) < image.stat().st_size


def test_clear_stale_overlay_skips_trailing_metadata_gzip_when_payload_covers_region(
    monkeypatch, capsys, tmp_path
):
    payload = b"x" * 4096
    image = tmp_path / "openmanet.img.gz"
    with gzip.open(image, "wb") as f:
        f.write(payload)
    with image.open("ab") as f:
        f.write(b'{"metadata": "openwrt sysupgrade trailer"}')

    monkeypatch.setattr(
        "easymanet.image.get_partition2_wipe_range",
        lambda _d: (1024, 2048),
    )
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("dd should not run")),
    )

    _clear_stale_overlay("/dev/disk4", image)
    captured = capsys.readouterr()
    assert "Skipping stale overlay wipe" in captured.out


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

    def fake_run(cmd, check):
        calls.append((cmd, check))

    tail_start = 138412032
    wipe_bytes = 4500000000
    image = tmp_path / "openmanet.img"
    image.write_bytes(b"x" * 64)

    def fake_wipe_range(device):
        assert device == "/dev/disk4"
        return (tail_start, wipe_bytes)

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("easymanet.image.get_partition2_wipe_range", fake_wipe_range)
    monkeypatch.setattr("easymanet.image._written_image_bytes", lambda _img: 64)

    _clear_stale_overlay("/dev/disk4", image)

    assert len(calls) == 1
    cmd, check = calls[0]
    assert check is True
    assert cmd[0] == "dd"
    assert "if=/dev/zero" in cmd
    assert "of=/dev/disk4" in cmd
    assert "bs=512" in cmd
    start_bytes = max(tail_start, 64)
    adjusted_wipe = wipe_bytes - (start_bytes - tail_start)
    sector_bytes = 512
    expected_seek = (start_bytes + sector_bytes - 1) // sector_bytes
    aligned_start = expected_seek * sector_bytes
    span_bytes = adjusted_wipe + (aligned_start - start_bytes)
    expected_count = max(1, (span_bytes + sector_bytes - 1) // sector_bytes)
    assert f"seek={expected_seek}" in cmd
    assert f"count={expected_count}" in cmd


def test_clear_stale_overlay_skips_when_image_covers_region(monkeypatch, capsys, tmp_path):
    image = tmp_path / "openmanet.img"
    image.write_bytes(b"x")

    monkeypatch.setattr(
        "easymanet.image.get_partition2_wipe_range",
        lambda _d: (1024, 2048),
    )
    monkeypatch.setattr("easymanet.image._written_image_bytes", lambda _img: 4096)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("dd should not run")),
    )

    _clear_stale_overlay("/dev/disk4", image)
    captured = capsys.readouterr()
    assert "Skipping stale overlay wipe" in captured.out


def test_clear_stale_overlay_skips_when_no_partition_layout(monkeypatch, capsys, tmp_path):
    image = tmp_path / "openmanet.img"
    image.write_bytes(b"x")
    monkeypatch.setattr("easymanet.image.get_partition2_wipe_range", lambda _d: None)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("dd should not run")))

    _clear_stale_overlay("/dev/disk4", image)
    captured = capsys.readouterr()
    assert "skipping stale overlay wipe" in captured.out


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
