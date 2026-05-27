"""Tests for image validation before flashing."""

import gzip

import pytest

from easymanet.image import FlashError, _check_image, _clear_stale_overlay


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


def test_check_image_rejects_corrupt_gzip(tmp_path):
    image = tmp_path / "openmanet.img.gz"
    with gzip.open(image, "wb") as f:
        f.write(b"image-bytes")
    data = image.read_bytes()
    image.write_bytes(data[:-8])

    with pytest.raises(FlashError, match="Invalid gzip-compressed image"):
        _check_image(str(image))


def test_clear_stale_overlay_uses_partition_offset(monkeypatch):
    calls = []

    def fake_run(cmd, check):
        calls.append((cmd, check))

    def fake_wipe_range(device):
        assert device == "/dev/disk4"
        return (138412032, 4500000000)

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("easymanet.image.get_partition2_wipe_range", fake_wipe_range)

    _clear_stale_overlay("/dev/disk4")

    assert len(calls) == 1
    cmd, check = calls[0]
    assert check is True
    assert "dd" in cmd
    assert "if=/dev/zero" in cmd
    assert "of=/dev/disk4" in cmd
    seek_args = [arg for arg in cmd if arg.startswith("seek=")]
    assert len(seek_args) == 1
    assert int(seek_args[0].split("=", 1)[1]) > 0


def test_clear_stale_overlay_skips_when_no_partition_layout(monkeypatch, capsys):
    monkeypatch.setattr("easymanet.image.get_partition2_wipe_range", lambda _d: None)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("dd should not run")))

    _clear_stale_overlay("/dev/disk4")
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
