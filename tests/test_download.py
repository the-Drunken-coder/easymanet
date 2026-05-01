"""Tests for cached image selection."""

import gzip
import json

from easymanet import download


def _write_gzip(path, payload=b"image-bytes", corrupt=False, trailing=b""):
    with gzip.open(path, "wb") as f:
        f.write(payload)
    if corrupt:
        path.write_bytes(path.read_bytes()[:-8])
    if trailing:
        with path.open("ab") as f:
            f.write(trailing)


def test_get_cached_image_skips_corrupt_configured_image(tmp_path, monkeypatch):
    cache = tmp_path / "images"
    cache.mkdir()
    manifest = tmp_path / "images.json"
    version_file = tmp_path / "version.json"
    image = cache / "openmanet-test-rpi4-mm6108-spi.img.gz"
    _write_gzip(image, corrupt=True)

    manifest.write_text(json.dumps({
        "rpi4-mm6108-spi": {
            "url": f"https://example.invalid/{image.name}",
            "version": "test",
        }
    }))

    monkeypatch.setattr(download, "CACHE_DIR", cache)
    monkeypatch.setattr(download, "IMAGES_MANIFEST", manifest)
    monkeypatch.setattr(download, "VERSION_FILE", version_file)

    assert download.get_cached_image("rpi4-mm6108-spi") is None


def test_get_cached_image_returns_valid_matching_image(tmp_path, monkeypatch):
    cache = tmp_path / "images"
    cache.mkdir()
    manifest = tmp_path / "images.json"
    version_file = tmp_path / "version.json"
    image = cache / "openmanet-test-rpi4-mm6108-spi.img.gz"
    _write_gzip(image)

    monkeypatch.setattr(download, "CACHE_DIR", cache)
    monkeypatch.setattr(download, "IMAGES_MANIFEST", manifest)
    monkeypatch.setattr(download, "VERSION_FILE", version_file)

    assert download.get_cached_image("rpi4-mm6108-spi") == image


def test_get_cached_image_allows_openwrt_trailing_metadata(tmp_path, monkeypatch):
    cache = tmp_path / "images"
    cache.mkdir()
    manifest = tmp_path / "images.json"
    version_file = tmp_path / "version.json"
    image = cache / "openmanet-test-rpi4-mm6108-spi.img.gz"
    _write_gzip(image, trailing=b'{"metadata": "openwrt sysupgrade trailer"}')

    monkeypatch.setattr(download, "CACHE_DIR", cache)
    monkeypatch.setattr(download, "IMAGES_MANIFEST", manifest)
    monkeypatch.setattr(download, "VERSION_FILE", version_file)

    assert download.get_cached_image("rpi4-mm6108-spi") == image
