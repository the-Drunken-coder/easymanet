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


def test_pick_release_asset_falls_back_to_pattern_match():
    release = {
        "tag_name": "1.6.5",
        "assets": [
            {
                "name": "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz",
                "browser_download_url": "https://example.com/fallback.img.gz",
            }
        ],
    }
    version, url = download._pick_release_asset(release, "rpi4-mm6108-spi")
    assert version == "1.6.5"
    assert url.endswith("fallback.img.gz")


def test_pick_release_asset_uses_fuzzy_match_when_exact_name_missing(capsys):
    release = {
        "tag_name": "2.0.0",
        "assets": [
            {
                "name": "custom-openmanet-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz",
                "browser_download_url": "https://example.com/custom.img.gz",
            }
        ],
    }
    result = download._pick_release_asset(release, "rpi4-mm6108-spi")
    assert result == ("2.0.0", "https://example.com/custom.img.gz")
    assert "Using release asset" in capsys.readouterr().out


def test_check_easymanet_update_uses_configured_repo(monkeypatch):
    payload = json.dumps({"tag_name": "v9.9.9"}).encode()

    def fake_urlopen(url, timeout=10):
        assert download.EASYMANET_GITHUB_REPO in url
        class Resp:
            def read(self):
                return payload
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return Resp()

    monkeypatch.setattr(download, "__version__", "0.1.0")
    monkeypatch.setattr(download.urllib.request, "urlopen", fake_urlopen)
    assert download.check_easymanet_update() == "9.9.9"
