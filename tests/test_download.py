"""Tests for cached image selection."""

import gzip
import hashlib
import io
import json
from pathlib import Path

import pytest

from easymanet import download


def _write_gzip(path, payload=b"image-bytes", corrupt=False, trailing=b""):
    with gzip.open(path, "wb") as f:
        f.write(payload)
    if corrupt:
        path.write_bytes(path.read_bytes()[:-8])
    if trailing:
        with path.open("ab") as f:
            f.write(trailing)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_get_cached_image_skips_empty_img(tmp_path, monkeypatch):
    cache = tmp_path / "images"
    cache.mkdir()
    version_file = tmp_path / "version.json"
    image = cache / "openmanet-test-rpi4-mm6108-spi.img"
    image.touch()

    monkeypatch.setattr(download, "CACHE_DIR", cache)
    monkeypatch.setattr(download, "VERSION_FILE", version_file)

    assert download.get_cached_image("rpi4-mm6108-spi") is None
    assert download._valid_cached_image(image) is False


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

    manifest.write_text(json.dumps({
        "rpi4-mm6108-spi": {
            "url": f"https://example.invalid/{image.name}",
            "version": "test",
            "sha256": _sha256(image),
        }
    }))

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
    manifest.write_text(json.dumps({
        "rpi4-mm6108-spi": {
            "url": f"https://example.invalid/{image.name}",
            "version": "test",
            "sha256": _sha256(image),
        }
    }))

    monkeypatch.setattr(download, "CACHE_DIR", cache)
    monkeypatch.setattr(download, "IMAGES_MANIFEST", manifest)
    monkeypatch.setattr(download, "VERSION_FILE", version_file)

    assert download.get_cached_image("rpi4-mm6108-spi") == image


def test_get_cached_image_ignores_file_removed_during_sort(tmp_path, monkeypatch):
    cache = tmp_path / "images"
    cache.mkdir()
    manifest = tmp_path / "images.json"
    version_file = tmp_path / "version.json"
    missing = cache / "openmanet-old-rpi4-mm6108-spi.img"
    valid = cache / "openmanet-new-rpi4-mm6108-spi.img.gz"
    missing.write_bytes(b"old")
    _write_gzip(valid)

    monkeypatch.setattr(download, "CACHE_DIR", cache)
    monkeypatch.setattr(download, "IMAGES_MANIFEST", manifest)
    monkeypatch.setattr(download, "VERSION_FILE", version_file)

    original_stat = Path.stat

    def flaky_stat(path, *args, **kwargs):
        if path == missing:
            raise FileNotFoundError(path)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky_stat)

    assert download.get_cached_image("rpi4-mm6108-spi", sha256=_sha256(valid)) == valid


def test_get_cached_image_requires_checksum(tmp_path, monkeypatch):
    cache = tmp_path / "images"
    cache.mkdir()
    manifest = tmp_path / "images.json"
    version_file = tmp_path / "version.json"
    image = cache / "openmanet-test-rpi4-mm6108-spi.img.gz"
    _write_gzip(image)

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


def test_get_cached_image_rejects_checksum_mismatch(tmp_path, monkeypatch):
    cache = tmp_path / "images"
    cache.mkdir()
    manifest = tmp_path / "images.json"
    version_file = tmp_path / "version.json"
    image = cache / "openmanet-test-rpi4-mm6108-spi.img.gz"
    _write_gzip(image)

    manifest.write_text(json.dumps({
        "rpi4-mm6108-spi": {
            "url": f"https://example.invalid/{image.name}",
            "version": "test",
            "sha256": "0" * 64,
        }
    }))

    monkeypatch.setattr(download, "CACHE_DIR", cache)
    monkeypatch.setattr(download, "IMAGES_MANIFEST", manifest)
    monkeypatch.setattr(download, "VERSION_FILE", version_file)

    assert download.get_cached_image("rpi4-mm6108-spi") is None


def test_download_image_rejects_non_https_url(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "CACHE_DIR", tmp_path / "images")
    monkeypatch.setattr(download, "VERSION_FILE", tmp_path / "version.json")

    with pytest.raises(OSError, match="Unsupported image URL scheme"):
        download.download_image("rpi4-mm6108-spi", "test", "file:///etc/passwd", "0" * 64)

    with pytest.raises(OSError, match="HTTPS"):
        download.download_image(
            "rpi4-mm6108-spi",
            "test",
            "http://example.invalid/image.img.gz",
            "0" * 64,
        )


def test_download_image_verifies_sha256(tmp_path, monkeypatch):
    payload = b"firmware-bytes"
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb") as f:
        f.write(payload)
    body = compressed.getvalue()
    expected = hashlib.sha256(body).hexdigest()

    class Resp:
        def __init__(self):
            self.headers = {"Content-Length": str(len(body))}
            self.stream = io.BytesIO(body)

        def read(self, size=-1):
            return self.stream.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(download, "CACHE_DIR", tmp_path / "images")
    monkeypatch.setattr(download, "VERSION_FILE", tmp_path / "version.json")
    monkeypatch.setattr(download.urllib.request, "urlopen", lambda *_a, **_k: Resp())

    path = download.download_image(
        "rpi4-mm6108-spi",
        "test",
        "https://example.invalid/openmanet-test-rpi4-mm6108-spi.img.gz",
        expected,
    )

    assert path.read_bytes() == body


def test_download_image_removes_file_on_sha256_mismatch(tmp_path, monkeypatch):
    payload = b"firmware-bytes"
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb") as f:
        f.write(payload)
    body = compressed.getvalue()

    class Resp:
        def __init__(self):
            self.headers = {"Content-Length": str(len(body))}
            self.stream = io.BytesIO(body)

        def read(self, size=-1):
            return self.stream.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(download, "CACHE_DIR", tmp_path / "images")
    monkeypatch.setattr(download, "VERSION_FILE", tmp_path / "version.json")
    monkeypatch.setattr(download.urllib.request, "urlopen", lambda *_a, **_k: Resp())

    with pytest.raises(OSError, match="SHA-256 mismatch"):
        download.download_image(
            "rpi4-mm6108-spi",
            "test",
            "https://example.invalid/openmanet-test-rpi4-mm6108-spi.img.gz",
            "0" * 64,
        )

    assert not (tmp_path / "images" / "openmanet-test-rpi4-mm6108-spi.img.gz").exists()


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
    result = download._pick_release_asset(release, "rpi4-mm6108-spi")
    assert result is not None
    assert result.version == "1.6.5"
    assert result.url.endswith("fallback.img.gz")


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
    assert result is not None
    assert result.version == "2.0.0"
    assert result.url == "https://example.com/custom.img.gz"
    assert "Using release asset" in capsys.readouterr().out


def test_pick_release_asset_uses_github_asset_digest():
    release = {
        "tag_name": "1.6.5",
        "assets": [
            {
                "name": "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz",
                "browser_download_url": "https://example.com/image.img.gz",
                "digest": f"sha256:{'a' * 64}",
            }
        ],
    }

    result = download._pick_release_asset(release, "rpi4-mm6108-spi")

    assert result is not None
    assert result.version == "1.6.5"
    assert result.url == "https://example.com/image.img.gz"
    assert result.sha256 == "a" * 64


def test_extract_sha256_from_checksum_text_matches_image_name():
    text = f"{'b' * 64}  openmanet.img.gz\n{'c' * 64}  other.img.gz\n"

    assert download._extract_sha256_from_checksum_text(text, "openmanet.img.gz") == "b" * 64


def test_extract_sha256_from_checksum_text_requires_exact_image_token():
    text = f"{'b' * 64}  not-openmanet.img.gz\n{'c' * 64}  other.img.gz\n"

    assert download._extract_sha256_from_checksum_text(text, "openmanet.img.gz") is None


def test_extract_sha256_from_checksum_text_accepts_star_prefixed_filename():
    text = f"{'b' * 64} *openmanet.img.gz\n"

    assert download._extract_sha256_from_checksum_text(text, "openmanet.img.gz") == "b" * 64


def test_extract_sha256_from_checksum_text_accepts_single_digest_file():
    text = f"{'b' * 64}\n"

    assert download._extract_sha256_from_checksum_text(text, "openmanet.img.gz") == "b" * 64


def test_extract_sha256_from_checksum_text_rejects_multi_digest_only_file():
    text = f"{'b' * 64}\n{'c' * 64}\n"

    assert download._extract_sha256_from_checksum_text(text, "openmanet.img.gz") is None


def test_check_latest_version_treats_invalid_configured_sha256_as_missing(
    tmp_path,
    monkeypatch,
    capsys,
):
    manifest = tmp_path / "images.json"
    manifest.write_text(json.dumps({
        "rpi4-mm6108-spi": {
            "url": "https://example.invalid/openmanet.img.gz",
            "version": "test",
            "sha256": "not-a-sha256",
        }
    }))
    monkeypatch.setattr(download, "IMAGES_MANIFEST", manifest)

    result = download.check_latest_version("rpi4-mm6108-spi")

    assert result is not None
    assert result.url == "https://example.invalid/openmanet.img.gz"
    assert result.sha256 is None
    assert "invalid SHA-256 configured" in capsys.readouterr().err


def test_check_easymanet_update_respects_env_repo(monkeypatch):
    payload = json.dumps({"tag_name": "v9.9.9"}).encode()
    monkeypatch.setenv("EASYMANET_UPDATE_REPO", "org/custom-easymanet")

    def fake_urlopen(url, timeout=10):
        assert "org/custom-easymanet" in url
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


def test_check_easymanet_update_uses_default_repo(monkeypatch):
    payload = json.dumps({"tag_name": "v9.9.9"}).encode()

    def fake_urlopen(url, timeout=10):
        assert download.easymanet_update_repo() in url
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
