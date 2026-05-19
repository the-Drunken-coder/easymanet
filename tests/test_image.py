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


def test_clear_stale_overlay_zeroes_full_writable_partition(monkeypatch):
    calls = []

    def fake_run(cmd, check):
        calls.append((cmd, check))

    monkeypatch.setattr("subprocess.run", fake_run)

    _clear_stale_overlay("/dev/disk4")

    # Must cover all of OpenMANET partition 2 (~4.3 GB) so the f2fs overlay,
    # not just the squashfs, gets wiped. 16 MiB * 288 = 4.5 GiB.
    assert calls == [
        (
            [
                "dd",
                "if=/dev/zero",
                "of=/dev/disk4",
                "bs=16m",
                "count=288",
                "status=progress",
            ],
            True,
        )
    ]
