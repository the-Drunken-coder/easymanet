"""Tests for image validation before flashing."""

import gzip

import pytest

from easymanet.image import FlashError, _check_image


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
