import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from easymanet_desktop import bridge
from easymanet_desktop import mesh
from easymanet_desktop import payloads
from easymanet_desktop import server
from easymanet import flash
from easymanet.flash import FlashErrorCode, FlashEvent
from easymanet.workspace import WORKSPACE_ENV, ensure_workspace


def _write_redaction_fleet(path, raw_values):
    path.write_text(
        f"""version: 1

mesh:
  id: redaction-test
  password: "{raw_values["mesh"]}"
  channel: 42
  bandwidth_mhz: 2
  country: US

defaults:
  target: rpi4-mm6108-spi

  local_ap:
    enabled: true
    password: "{raw_values["local_ap"]}"

  management:
    root_password_hash: ""
    ssh_authorized_keys:
      - "{raw_values["ssh_key"]}"

  gateway:
    wifi:
      enabled: false
      ssid: "redaction-uplink"
      password: "{raw_values["gateway_wifi"]}"
      encryption: psk2

nodes:
  gate01:
    role: gate
    hostname: gate01
    ip: 10.41.1.1

    local_ap:
      ssid: gate01-local

    gateway:
      enabled: true
      uplink_interface: wifi
      wifi:
        enabled: true
"""
    )


def test_desktop_validate_payload_returns_nodes():
    payload = payloads.validate_payload(
        {
            "config": "examples/three-node-field-mesh.yml",
            "node": "point01",
        }
    )

    assert payload["ok"] is True
    assert "point01" in payload["nodes"]
    assert payload["node_roles"]["gate01"] == "gate"
    assert payload["node_roles"]["point01"] == "point"
    assert payload["node_access"]["gate01"]["local_ap_ssid"] == "gate01-local"
    assert payload["node_access"]["gate01"]["management_ip"] == "10.41.254.1"


def test_node_access_preserves_nodes_when_one_model_fails(monkeypatch):
    manifest = payloads.load_manifest("examples/three-node-field-mesh.yml")
    original_resolve = payloads.resolve_node_model

    def fake_resolve_node_model(current_manifest, node_name):
        if node_name == "point01":
            raise ValueError("broken node")
        return original_resolve(current_manifest, node_name)

    monkeypatch.setattr(payloads, "resolve_node_model", fake_resolve_node_model)

    access = payloads.node_access(manifest)

    assert set(access) == set(manifest.node_names())
    assert access["point01"] == {
        "role": "",
        "local_ap_enabled": False,
        "local_ap_ssid": "",
        "management_ip": "10.41.254.1",
    }
    assert access["gate01"]["role"] == "gate"


def test_desktop_state_reads_configured_images_and_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    (workspace / "Fleets" / "field.yml").write_text(
        Path("examples/three-node-field-mesh.yml").read_text()
    )
    cache = tmp_path / "images"
    manifest = tmp_path / "images.json"
    cache.mkdir()
    manifest.write_text(
        '{"rpi4-mm6108-spi": {"version": "1.6.5", "sha256": "%s"}}' % ("a" * 64)
    )

    monkeypatch.setattr(payloads, "cache_dir", lambda: cache)
    monkeypatch.setattr(payloads, "images_manifest_path", lambda: manifest)

    payload = payloads.state_payload()

    assert payload["ok"] is True
    assert payload["workspace"]["root"] == str(workspace)
    assert payload["workspace"]["fleet_files"][0]["relative_path"] == "field.yml"
    assert payload["image_cache_dir"] == str(cache)
    assert payload["images"]["rpi4-mm6108-spi"]["version"] == "1.6.5"


def test_image_update_payload_reports_newer_official_release(monkeypatch):
    monkeypatch.setattr(
        payloads,
        "state_payload",
        lambda: {
            "ok": True,
            "images": {
                "rpi4-mm6108-spi": {
                    "version": "images-v0.2.6",
                    "cached_path": "/tmp/openmanet.img.gz",
                    "cached_sha256": "a" * 64,
                }
            },
        },
    )
    monkeypatch.setattr(
        payloads,
        "check_latest_version",
        lambda _target: SimpleNamespace(
            version="images-v0.2.7",
            url="https://example.test/openmanet.img.gz",
            sha256="b" * 64,
            trust_status="verification-pending",
            source="official",
            channel="stable",
            release_tag="images-v0.2.7",
            image_status="current",
            manifest_url="https://example.test/easymanet-image-release.json",
            warnings=(),
        ),
    )

    payload = payloads.image_update_payload(check_latest=True)
    update = payload["updates"]["rpi4-mm6108-spi"]

    assert payload["ok"] is True
    assert update["status"] == "outdated"
    assert update["update_available"] is True
    assert update["current_version"] == "images-v0.2.6"
    assert update["latest_version"] == "images-v0.2.7"
    assert update["latest_sha256"] == "b" * 64


def test_image_update_payload_uses_local_state_by_default(monkeypatch):
    monkeypatch.setattr(
        payloads,
        "state_payload",
        lambda: {
            "ok": True,
            "images": {
                "rpi4-mm6108-spi": {
                    "version": "images-v0.2.6",
                    "cached_path": "/tmp/openmanet.img.gz",
                    "cached_sha256": "",
                }
            },
        },
    )
    monkeypatch.setattr(
        payloads,
        "check_latest_version",
        lambda _target: pytest.fail("default image update payload must stay local-only"),
    )

    update = payloads.image_update_payload()["updates"]["rpi4-mm6108-spi"]

    assert update["status"] == "cached"
    assert update["update_available"] is False
    assert update["current_version"] == "images-v0.2.6"
    assert update["cached_path"] == "/tmp/openmanet.img.gz"
    assert "latest_version" not in update


def test_image_update_payload_reports_version_only_cache_as_outdated(monkeypatch):
    monkeypatch.setattr(
        payloads,
        "state_payload",
        lambda: {
            "ok": True,
            "images": {
                "rpi4-mm6108-spi": {
                    "version": "images-v0.2.6",
                    "cached_path": "/tmp/openmanet.img.gz",
                    "cached_sha256": "",
                }
            },
        },
    )
    monkeypatch.setattr(
        payloads,
        "check_latest_version",
        lambda _target: SimpleNamespace(
            version="images-v0.2.7",
            url="https://example.test/openmanet.img.gz",
            sha256="b" * 64,
            trust_status="verification-pending",
            source="official",
            channel="stable",
            release_tag="images-v0.2.7",
            image_status="current",
            manifest_url="https://example.test/easymanet-image-release.json",
            warnings=(),
        ),
    )

    update = payloads.image_update_payload(check_latest=True)["updates"]["rpi4-mm6108-spi"]

    assert update["status"] == "outdated"
    assert update["update_available"] is True
    assert update["current_sha256"] == ""


def test_image_update_payload_marks_unverified_cache_as_outdated(monkeypatch):
    monkeypatch.setattr(
        payloads,
        "state_payload",
        lambda: {
            "ok": True,
            "images": {
                "rpi4-mm6108-spi": {
                    "cached_path": "/tmp/openmanet.img.gz",
                    "cached_sha256": "",
                }
            },
        },
    )
    monkeypatch.setattr(
        payloads,
        "check_latest_version",
        lambda _target: SimpleNamespace(
            version="images-v0.2.7",
            url="https://example.test/openmanet.img.gz",
            sha256="b" * 64,
            trust_status="verification-pending",
            source="official",
            channel="stable",
            release_tag="images-v0.2.7",
            image_status="current",
            manifest_url="https://example.test/easymanet-image-release.json",
            warnings=(),
        ),
    )

    update = payloads.image_update_payload(check_latest=True)["updates"]["rpi4-mm6108-spi"]

    assert update["status"] == "outdated"
    assert update["update_available"] is True
    assert update["current_version"] == ""
    assert update["current_sha256"] == ""


def test_image_update_payload_reports_display_only_cache_as_missing(monkeypatch):
    monkeypatch.setattr(
        payloads,
        "state_payload",
        lambda: {
            "ok": True,
            "images": {
                "rpi4-mm6108-spi": {
                    "version": "images-v0.2.6",
                    "cached_path": "/tmp/openmanet.img.gz",
                    "cached_sha256": "",
                    "cache_present": False,
                }
            },
        },
    )
    monkeypatch.setattr(
        payloads,
        "check_latest_version",
        lambda _target: SimpleNamespace(
            version="images-v0.2.7",
            url="https://example.test/openmanet.img.gz",
            sha256="b" * 64,
            trust_status="verification-pending",
            source="official",
            channel="stable",
            release_tag="images-v0.2.7",
            image_status="current",
            manifest_url="https://example.test/easymanet-image-release.json",
            warnings=(),
        ),
    )

    update = payloads.image_update_payload(check_latest=True)["updates"]["rpi4-mm6108-spi"]

    assert update["status"] == "missing"
    assert update["update_available"] is True
    assert update["cached_path"] == "/tmp/openmanet.img.gz"
    assert update["cache_present"] is False


def test_install_image_update_downloads_latest_release(monkeypatch, tmp_path):
    image = tmp_path / "openmanet.img.gz"
    state = {
        "ok": True,
        "images": {
            "rpi4-mm6108-spi": {
                "version": "images-v0.2.6",
                "cached_path": str(image),
                "cached_sha256": "a" * 64,
            }
        },
    }
    latest = SimpleNamespace(
        version="images-v0.2.7",
        url="https://example.test/openmanet.img.gz",
        sha256="b" * 64,
        trust={"source": "official", "status": "verification-pending"},
        trust_status="verification-pending",
        source="official",
        channel="stable",
        release_tag="images-v0.2.7",
        image_status="current",
        manifest_url="https://example.test/easymanet-image-release.json",
        warnings=(),
    )
    monkeypatch.setattr(payloads, "state_payload", lambda: state)
    monkeypatch.setattr(payloads, "check_latest_version", lambda _target: latest)

    def fake_download_image(target, version, url, sha256, *, force, trust) -> Path:
        assert target == "rpi4-mm6108-spi"
        assert version == "images-v0.2.7"
        assert url == latest.url
        assert sha256 == latest.sha256
        assert force is True
        assert trust == latest.trust
        state["images"]["rpi4-mm6108-spi"].update(
            version="images-v0.2.7",
            cached_sha256="b" * 64,
        )
        return image

    monkeypatch.setattr(payloads, "download_image", fake_download_image)

    result = payloads.install_image_update_payload(target="rpi4-mm6108-spi")

    assert result["ok"] is True
    assert result["installed"] is True
    assert result["version"] == "images-v0.2.7"
    assert result["update"]["status"] == "current"
    assert result["update"]["update_available"] is False


def test_install_image_update_downloads_version_only_outdated_cache(monkeypatch, tmp_path):
    image = tmp_path / "openmanet.img.gz"
    state = {
        "ok": True,
        "images": {
            "rpi4-mm6108-spi": {
                "version": "images-v0.2.6",
                "cached_path": str(image),
                "cached_sha256": "",
            }
        },
    }
    latest = SimpleNamespace(
        version="images-v0.2.7",
        url="https://example.test/openmanet.img.gz",
        sha256="b" * 64,
        trust={},
        trust_status="verification-pending",
        source="official",
        channel="stable",
        release_tag="images-v0.2.7",
        image_status="current",
        manifest_url="https://example.test/easymanet-image-release.json",
        warnings=(),
    )
    downloads = []
    monkeypatch.setattr(payloads, "state_payload", lambda: state)
    monkeypatch.setattr(payloads, "check_latest_version", lambda _target: latest)

    def fake_download_image(target, version, url, sha256, *, force, trust) -> Path:
        downloads.append((target, version, url, sha256, force, trust))
        state["images"]["rpi4-mm6108-spi"].update(
            version="images-v0.2.7",
            cached_sha256="b" * 64,
        )
        return image

    monkeypatch.setattr(payloads, "download_image", fake_download_image)

    result = payloads.install_image_update_payload(target="rpi4-mm6108-spi")

    assert result["ok"] is True
    assert result["installed"] is True
    assert result["version"] == "images-v0.2.7"
    assert result["update"]["status"] == "current"
    assert result["update"]["update_available"] is False
    assert downloads == [
        (
            "rpi4-mm6108-spi",
            "images-v0.2.7",
            "https://example.test/openmanet.img.gz",
            "b" * 64,
            True,
            {},
        )
    ]


def test_install_image_update_downloads_display_only_current_cache(monkeypatch, tmp_path):
    image = tmp_path / "openmanet.img.gz"
    state = {
        "ok": True,
        "images": {
            "rpi4-mm6108-spi": {
                "version": "images-v0.2.7",
                "cached_path": str(image),
                "cached_sha256": "b" * 64,
                "cache_present": False,
            }
        },
    }
    latest = SimpleNamespace(
        version="images-v0.2.7",
        url="https://example.test/openmanet.img.gz",
        sha256="b" * 64,
        trust={},
        trust_status="verification-pending",
        source="official",
        channel="stable",
        release_tag="images-v0.2.7",
        image_status="current",
        manifest_url="https://example.test/easymanet-image-release.json",
        warnings=(),
    )
    downloads = []
    monkeypatch.setattr(payloads, "state_payload", lambda: state)
    monkeypatch.setattr(payloads, "check_latest_version", lambda _target: latest)

    def fake_download_image(target, version, url, sha256, *, force, trust) -> Path:
        downloads.append((target, version, url, sha256, force, trust))
        state["images"]["rpi4-mm6108-spi"]["cache_present"] = True
        return image

    monkeypatch.setattr(payloads, "download_image", fake_download_image)

    result = payloads.install_image_update_payload(target="rpi4-mm6108-spi")

    assert result["ok"] is True
    assert result["installed"] is True
    assert result["update"]["status"] == "current"
    assert downloads == [
        (
            "rpi4-mm6108-spi",
            "images-v0.2.7",
            "https://example.test/openmanet.img.gz",
            "b" * 64,
            True,
            {},
        )
    ]


def test_install_image_update_rejects_unknown_target(monkeypatch):
    monkeypatch.setattr(payloads, "state_payload", lambda: {"ok": True, "images": {}})

    result = payloads.install_image_update_payload(target="rpi4-mm6108-spi")

    assert result == {"ok": False, "errors": ["Unknown image target: rpi4-mm6108-spi"]}


def test_install_image_update_reports_latest_lookup_failure(monkeypatch):
    monkeypatch.setattr(
        payloads,
        "state_payload",
        lambda: {"ok": True, "images": {"rpi4-mm6108-spi": {"version": "images-v0.2.6"}}},
    )
    monkeypatch.setattr(payloads, "check_latest_version", lambda _target: None)

    result = payloads.install_image_update_payload(target="rpi4-mm6108-spi")

    assert result == {"ok": False, "errors": ["Could not check the latest image release."]}


def test_install_image_update_requires_sha256(monkeypatch):
    monkeypatch.setattr(
        payloads,
        "state_payload",
        lambda: {"ok": True, "images": {"rpi4-mm6108-spi": {"version": "images-v0.2.6"}}},
    )
    monkeypatch.setattr(
        payloads,
        "check_latest_version",
        lambda _target: SimpleNamespace(
            version="images-v0.2.7",
            url="https://example.test/openmanet.img.gz",
            sha256="",
        ),
    )
    monkeypatch.setattr(
        payloads,
        "download_image",
        lambda *args, **kwargs: pytest.fail("download_image should not be called"),
    )

    result = payloads.install_image_update_payload(target="rpi4-mm6108-spi")

    assert result == {
        "ok": False,
        "errors": ["No SHA-256 checksum found for target 'rpi4-mm6108-spi'."],
    }


def test_desktop_state_reports_cached_image_hash_without_manifest(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    cache = tmp_path / "images"
    cache.mkdir()
    image = cache / "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    image.write_bytes(b"firmware")
    version_file = tmp_path / "version.json"
    version_file.write_text(json.dumps({"rpi4-mm6108-spi": "1.6.5"}))

    monkeypatch.setattr(payloads, "cache_dir", lambda: cache)
    monkeypatch.setattr(payloads, "images_manifest_path", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(payloads, "version_file_path", lambda: version_file)

    payload = payloads.state_payload()
    entry = payload["images"]["rpi4-mm6108-spi"]

    assert entry["version"] == "1.6.5"
    assert entry["cached_path"] == str(image)
    assert entry["cache_present"] is False
    assert entry["cached_size_bytes"] == len(b"firmware")
    assert entry["cached_sha256"] == hashlib.sha256(b"firmware").hexdigest()


def test_desktop_state_verifies_version_metadata_cache_without_manifest(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    cache = workspace / "Images"
    image = cache / "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    other = cache / "backup-rpi4-mm6108-spi.img.gz"
    with gzip.open(image, "wb") as handle:
        handle.write(b"firmware")
    other.write_bytes(image.read_bytes())
    other.touch()
    expected_sha256 = hashlib.sha256(image.read_bytes()).hexdigest()
    (cache / "version.json").write_text(
        json.dumps(
            {
                "rpi4-mm6108-spi": {
                    "version": "images-v0.2.8",
                    "sha256": expected_sha256,
                    "url": f"https://example.test/{image.name}",
                    "trust_status": "verified",
                    "source": "official",
                    "image_status": "current",
                }
            }
        )
    )

    entry = payloads.state_payload()["images"]["rpi4-mm6108-spi"]

    assert entry["cached_path"] == str(image)
    assert entry["cache_present"] is True
    assert entry["version"] == "images-v0.2.8"
    assert entry["trust_status"] == "verified"
    assert entry["cached_sha256"] == expected_sha256


def test_desktop_state_uses_manifest_cache_when_version_metadata_is_stale(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    cache = workspace / "Images"
    image = cache / "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    with gzip.open(image, "wb") as handle:
        handle.write(b"firmware")
    expected_sha256 = hashlib.sha256(image.read_bytes()).hexdigest()
    url = f"https://example.test/{image.name}"
    (cache / "images.json").write_text(
        json.dumps(
            {
                "rpi4-mm6108-spi": {
                    "version": "images-v0.2.9",
                    "sha256": expected_sha256,
                    "url": url,
                }
            }
        )
    )
    (cache / "version.json").write_text(
        json.dumps(
            {
                "rpi4-mm6108-spi": {
                    "version": "images-v0.2.8",
                    "sha256": "a" * 64,
                    "url": url,
                }
            }
        )
    )

    entry = payloads.state_payload()["images"]["rpi4-mm6108-spi"]

    assert image.exists()
    assert entry["cached_path"] == str(image)
    assert entry["cache_present"] is True
    assert entry["version"] == "images-v0.2.9"
    assert entry["cached_sha256"] == expected_sha256


def test_desktop_state_does_not_delete_cache_with_stale_version_metadata(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    cache = workspace / "Images"
    image = cache / "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    with gzip.open(image, "wb") as handle:
        handle.write(b"firmware")
    (cache / "version.json").write_text(
        json.dumps(
            {
                "rpi4-mm6108-spi": {
                    "version": "images-v0.2.8",
                    "sha256": "a" * 64,
                    "url": f"https://example.test/{image.name}",
                }
            }
        )
    )

    entry = payloads.state_payload()["images"]["rpi4-mm6108-spi"]

    assert image.exists()
    assert entry["cached_path"] == ""
    assert entry["cache_present"] is False


def test_desktop_state_does_not_pair_version_hash_with_fallback_cache(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    cache = tmp_path / "images"
    cache.mkdir()
    image = cache / "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    with image.open("wb") as handle:
        handle.truncate(payloads.DISPLAY_CACHE_HASH_LIMIT_BYTES + 1)
    version_file = tmp_path / "version.json"
    version_file.write_text(
        json.dumps({"rpi4-mm6108-spi": {"version": "1.6.5", "sha256": "b" * 64}})
    )

    monkeypatch.setattr(payloads, "cache_dir", lambda: cache)
    monkeypatch.setattr(payloads, "images_manifest_path", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(payloads, "version_file_path", lambda: version_file)
    monkeypatch.setattr(
        payloads,
        "image_sha256",
        lambda _path: (_ for _ in ()).throw(AssertionError("large cache should not be hashed")),
    )

    entry = payloads.state_payload()["images"]["rpi4-mm6108-spi"]

    assert entry["cached_path"] == ""
    assert entry["cache_present"] is False
    assert "cached_size_bytes" not in entry
    assert "cached_sha256" not in entry


def test_desktop_state_ignores_non_string_cached_metadata_hash(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    cache = tmp_path / "images"
    cache.mkdir()
    image = cache / "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    image.write_bytes(b"firmware")
    manifest = tmp_path / "images.json"
    manifest.write_text(json.dumps({"rpi4-mm6108-spi": {"sha256": 123}}))

    monkeypatch.setattr(payloads, "cache_dir", lambda: cache)
    monkeypatch.setattr(payloads, "images_manifest_path", lambda: manifest)
    monkeypatch.setattr(payloads, "version_file_path", lambda: tmp_path / "missing-version.json")

    entry = payloads.state_payload()["images"]["rpi4-mm6108-spi"]

    assert entry["cache_present"] is False
    assert entry["cached_sha256"] == hashlib.sha256(b"firmware").hexdigest()


def test_desktop_state_discovers_cache_for_malformed_manifest_hash(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    cache = tmp_path / "images"
    cache.mkdir()
    image = cache / "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    image.write_bytes(b"firmware")
    manifest = tmp_path / "images.json"
    manifest.write_text(json.dumps({"rpi4-mm6108-spi": {"sha256": "not-a-sha"}}))

    monkeypatch.setattr(payloads, "cache_dir", lambda: cache)
    monkeypatch.setattr(payloads, "images_manifest_path", lambda: manifest)
    monkeypatch.setattr(payloads, "version_file_path", lambda: tmp_path / "missing-version.json")

    entry = payloads.state_payload()["images"]["rpi4-mm6108-spi"]

    assert entry["cached_path"] == str(image)
    assert entry["cache_present"] is False
    assert entry["cached_sha256"] == hashlib.sha256(b"firmware").hexdigest()


def test_desktop_state_skips_hashing_large_unversioned_cache(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    cache = tmp_path / "images"
    cache.mkdir()
    image = cache / "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    with image.open("wb") as handle:
        handle.truncate(payloads.DISPLAY_CACHE_HASH_LIMIT_BYTES + 1)

    monkeypatch.setattr(payloads, "cache_dir", lambda: cache)
    monkeypatch.setattr(payloads, "images_manifest_path", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(payloads, "version_file_path", lambda: tmp_path / "missing-version.json")
    monkeypatch.setattr(
        payloads,
        "image_sha256",
        lambda _path: (_ for _ in ()).throw(AssertionError("large cache should not be hashed")),
    )

    entry = payloads.state_payload()["images"]["rpi4-mm6108-spi"]

    assert entry["cache_present"] is False
    assert entry["cached_size_bytes"] == payloads.DISPLAY_CACHE_HASH_LIMIT_BYTES + 1
    assert entry["cached_sha256"] == ""


def test_desktop_validate_resolves_workspace_fleet_name(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    fleet = workspace / "Fleets" / "field.yml"
    fleet.write_text(Path("examples/three-node-field-mesh.yml").read_text())

    payload = payloads.validate_payload({"config": "field", "node": "point01"})

    assert payload["ok"] is True
    assert payload["config_path"] == str(fleet)
    assert "point01" in payload["nodes"]


def test_desktop_resolve_config_rejects_non_yaml_file(tmp_path):
    config = tmp_path / "notes.txt"
    config.write_text("not: fleet\n")

    payload = payloads.resolve_config_payload(config=str(config))

    assert payload["ok"] is False
    assert payload["errors"] == ["Fleet config file must be .yml or .yaml"]
    assert payload["config_path"] == str(config)


def test_desktop_disks_payload_serializes_unmounted_disks(monkeypatch):
    monkeypatch.setattr(payloads, "check_platform", lambda: None)
    monkeypatch.setattr(
        payloads,
        "list_disks",
        lambda include_all=False: [
            SimpleNamespace(
                device="/dev/disk4",
                model="USB",
                size_human="8 GB",
                removable=True,
                mounted=["/Volumes/BOOT"],
                warnings=[],
            ),
            SimpleNamespace(
                device="/dev/disk5",
                model="Unmounted USB",
                size_human="16 GB",
                removable=True,
                mounted=[],
                warnings=[],
            ),
        ],
    )

    payload = payloads.disks_payload(include_all=False)

    assert payload["ok"] is True
    assert [disk["device"] for disk in payload["disks"]] == ["/dev/disk4", "/dev/disk5"]
    assert payload["disks"][0]["removable"] is True
    assert payload["disks"][0]["mounted"] == ["/Volumes/BOOT"]
    assert payload["disks"][0]["warnings"] == []
    assert payload["disks"][1]["mounted"] == []


def test_desktop_mesh_discovery_uses_gateway_topology_api(monkeypatch):
    monkeypatch.setattr(mesh, "_arp_hosts", lambda: [])
    monkeypatch.setattr(mesh, "_local_subnet_hosts", lambda: [])

    def fake_probe(candidate):
        if candidate.node == "gate01" and candidate.host == "gate01.local":
            return {
                **candidate.to_dict(),
                "ok": True,
                "status": "connected",
                "hostname": "gate01",
                "role": "gate",
                "node_ip": "10.41.1.1",
                "summary": "gate01 / gate / 10.41.1.1",
            }
        return {**candidate.to_dict(), "ok": False, "status": "api_unreachable"}

    def fake_topology(gateway):
        assert gateway["hostname"] == "gate01"
        return {
            "ok": True,
            "generated_at": "2026-06-13T00:00:00Z",
            "nodes": [
                {"name": "gate01", "role": "gate", "ip": "10.41.1.1", "status": "online"},
                {"name": "point01", "role": "point", "ip": "10.41.2.1", "status": "online"},
            ],
            "links": [
                {"source": "gate01", "target": "point01", "status": "resolved"},
            ],
            "warnings": [],
        }

    payload = mesh.mesh_discover_payload(
        {"config": "examples/three-node-field-mesh.yml", "scanSubnet": False},
        probe=fake_probe,
        topology_fetcher=fake_topology,
    )

    assert payload["ok"] is True
    assert payload["candidates_checked"] >= 3
    assert payload["gateway"]["hostname"] == "gate01"
    assert [node["name"] for node in payload["nodes"]] == ["gate01", "point01"]
    assert payload["links"][0]["target"] == "point01"
    assert payload["seen"][0]["hostname"] == "gate01"


def test_desktop_mesh_discovery_tries_next_gateway_after_topology_failure(monkeypatch):
    monkeypatch.setattr(mesh, "_arp_hosts", lambda: [])
    monkeypatch.setattr(mesh, "_local_subnet_hosts", lambda: [])

    gateways = {
        "10.41.254.1": "gate01",
        "manet01.local": "gate02",
    }

    def fake_probe(candidate):
        hostname = gateways.get(candidate.host)
        if hostname:
            return {
                **candidate.to_dict(),
                "ok": True,
                "status": "connected",
                "hostname": hostname,
                "role": "gate",
                "host": candidate.host,
            }
        return {**candidate.to_dict(), "ok": False, "status": "api_unreachable"}

    attempts: list[str] = []

    def fake_topology(gateway):
        attempts.append(gateway["host"])
        if gateway["host"] == "10.41.254.1":
            return {"ok": False, "code": "api_error", "errors": ["topology failed"]}
        return {
            "ok": True,
            "generated_at": "2026-06-13T00:00:00Z",
            "nodes": [{"name": "gate02", "role": "gate", "status": "online"}],
            "links": [],
            "warnings": [],
        }

    payload = mesh.mesh_discover_payload(
        {"config": "", "scanSubnet": False},
        probe=fake_probe,
        topology_fetcher=fake_topology,
    )

    assert payload["ok"] is True
    assert payload["gateway"]["hostname"] == "gate02"
    assert attempts == ["10.41.254.1", "manet01.local"]


def test_desktop_mesh_discovery_string_false_does_not_scan_subnet(monkeypatch):
    monkeypatch.setattr(mesh, "_arp_hosts", lambda: [])
    monkeypatch.setattr(
        mesh,
        "_local_subnet_hosts",
        lambda: (_ for _ in ()).throw(AssertionError("subnet scan should stay disabled")),
    )

    payload = mesh.mesh_discover_payload(
        {"config": "", "scanSubnet": "false"},
        probe=lambda candidate: {**candidate.to_dict(), "ok": False, "status": "api_unreachable"},
    )

    assert payload["ok"] is False
    assert payload["scan_subnet"] is False


def test_desktop_mesh_candidates_skip_bare_fleet_hostnames(monkeypatch):
    monkeypatch.setattr(mesh, "_arp_hosts", lambda: [])
    monkeypatch.setattr(mesh, "_local_subnet_hosts", lambda: [])

    candidates, warnings = mesh.mesh_candidates(
        config="examples/three-node-field-mesh.yml",
        scan_subnet=False,
    )

    assert warnings == []
    hosts = {candidate.host for candidate in candidates}
    assert "gate01" not in hosts
    assert "gate01.local" in hosts


def test_desktop_mesh_discovery_reports_missing_gateway_api(monkeypatch):
    monkeypatch.setattr(mesh, "_arp_hosts", lambda: [])
    monkeypatch.setattr(mesh, "_local_subnet_hosts", lambda: [])

    payload = mesh.mesh_discover_payload(
        {"config": "examples/three-node-field-mesh.yml", "scanSubnet": False},
        probe=lambda candidate: {**candidate.to_dict(), "ok": False, "status": "api_unreachable"},
    )

    assert payload["ok"] is False
    assert payload["code"] == "gateway_api_not_found"
    assert "topology API" in payload["errors"][0]
    assert payload["nodes"] == []


def test_desktop_bridge_validate_outputs_json(capsys):
    exit_code = bridge.main(
        [
            "validate",
            "--config",
            "examples/three-node-field-mesh.yml",
            "--node",
            "point01",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert "point01" in payload["nodes"]


def test_desktop_bridge_mesh_discover_outputs_json(monkeypatch, capsys):
    monkeypatch.setattr(
        bridge,
        "mesh_discover_payload",
        lambda payload: {"ok": True, "radios": [], "received": payload},
    )

    exit_code = bridge.main(
        [
            "mesh-discover",
            "--config",
            "examples/three-node-field-mesh.yml",
            "--scan-subnet",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["received"]["scan_subnet"] is True


def test_desktop_bridge_support_bundle_outputs_json(monkeypatch, capsys, tmp_path):
    output = tmp_path / "support.zip"
    boot = tmp_path / "boot"
    captured_kwargs = {}

    class FakeSupportBundleResult:
        def to_dict(self):
            return {"ok": True, "path": str(output), "files": ["support-bundle.json"], "redactions": []}

    def fake_create_support_bundle(**kwargs):
        captured_kwargs.update(kwargs)
        return FakeSupportBundleResult()

    monkeypatch.setattr(bridge, "create_support_bundle", fake_create_support_bundle)

    exit_code = bridge.main(
        [
            "support-bundle",
            "--config",
            "field",
            "--node",
            "point01",
            "--boot-report",
            str(boot),
            "--output",
            str(output),
            "--include-disks",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["path"] == str(output)
    assert captured_kwargs == {
        "config": "field",
        "node": "point01",
        "boot_report": str(boot),
        "output": str(output),
        "include_disks": True,
    }


def test_desktop_server_bool_payload_parses_false_strings():
    assert server._bool_payload(True) is True
    assert server._bool_payload("true") is True
    assert server._bool_payload("1") is True
    assert server._bool_payload(1) is True
    assert server._bool_payload("false") is False
    assert server._bool_payload("0") is False
    assert server._bool_payload("no") is False
    assert server._bool_payload(0) is False
    assert server._bool_payload(None) is False
    assert server._bool_payload("") is False
    assert server._bool_payload("FALSE") is False
    assert server._bool_payload("TRUE") is True
    assert server._bool_payload("Yes") is True
    assert server._bool_payload("No") is False


def test_desktop_bridge_support_bundle_reports_errors(monkeypatch, capsys):
    def fail_create_support_bundle(**_kwargs):
        raise ValueError("support export failed")

    monkeypatch.setattr(bridge, "create_support_bundle", fail_create_support_bundle)

    exit_code = bridge.main(["support-bundle"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": False, "errors": ["support export failed"]}


def test_desktop_bridge_diagnostics_outputs_json(monkeypatch, capsys):
    monkeypatch.setattr(
        bridge,
        "run_diagnostics",
        lambda config="": {"ok": True, "summary": "EasyMANET Diagnostics\n", "config": config},
    )

    exit_code = bridge.main(
        [
            "diagnostics-run",
            "--config",
            "examples/three-node-field-mesh.yml",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["config"] == "examples/three-node-field-mesh.yml"


def test_desktop_bridge_diagnostics_failure_outputs_json(monkeypatch, capsys):
    def fail_diagnostics(config=""):
        raise OSError(f"cannot read {config}")

    monkeypatch.setattr(bridge, "run_diagnostics", fail_diagnostics)

    exit_code = bridge.main(["diagnostics-run", "--config", "missing.yml"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "cannot read missing.yml" in payload["errors"][0]


def test_desktop_bridge_diagnostics_bundle_outputs_json(tmp_path, monkeypatch, capsys):
    bundle = tmp_path / "support.zip"
    monkeypatch.setattr(
        bridge,
        "export_support_bundle",
        lambda config="": {"ok": True, "bundle_path": str(bundle), "config": config},
    )

    exit_code = bridge.main(["diagnostics-bundle", "--config", "field"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["bundle_path"] == str(bundle)


def test_desktop_bridge_diagnostics_bundle_failure_outputs_json(monkeypatch, capsys):
    monkeypatch.setattr(
        bridge,
        "export_support_bundle",
        lambda config="": {"ok": False, "errors": [f"bundle failed for {config}"]},
    )

    exit_code = bridge.main(["diagnostics-bundle", "--config", "field"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["errors"] == ["bundle failed for field"]


def test_desktop_bridge_diagnostics_import_outputs_json(monkeypatch, capsys):
    monkeypatch.setattr(
        bridge,
        "import_boot_report",
        lambda source: {"ok": True, "imported": [source]},
    )

    exit_code = bridge.main(["diagnostics-import-boot-report", "--source", "/Volumes/boot"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == ["/Volumes/boot"]


def test_desktop_bridge_diagnostics_import_failure_outputs_json(monkeypatch, capsys):
    monkeypatch.setattr(
        bridge,
        "import_boot_report",
        lambda source: {"ok": False, "errors": [f"no reports under {source}"]},
    )

    exit_code = bridge.main(["diagnostics-import-boot-report", "--source", "/Volumes/boot"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["errors"] == ["no reports under /Volumes/boot"]


def test_desktop_bridge_flash_plan_outputs_json(monkeypatch, capsys):
    calls = []

    def fake_prepare_flash_workflow(options, emit=None):
        del emit
        calls.append(options)
        return SimpleNamespace(
            to_dict=lambda include_events=False: {
                "ok": True,
                **({"events": []} if include_events else {}),
                "image": {"cached_path": "/tmp/openmanet.img.gz"},
            }
        )

    monkeypatch.setattr(bridge, "prepare_flash_workflow", fake_prepare_flash_workflow)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {"target": "rpi4-mm6108-spi", "cached_path": "/tmp/openmanet.img.gz"},
    )

    exit_code = bridge.main(
        [
            "flash-plan",
            "--config",
            "examples/three-node-field-mesh.yml",
            "--node",
            "point01",
            "--device",
            "/dev/disk4",
            "--enable-ssh",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["image"]["cached_path"] == "/tmp/openmanet.img.gz"
    assert calls[0].dry_run is True
    assert calls[0].yes is False
    assert calls[0].enable_ssh is True


def test_desktop_bridge_flash_plan_preserves_cached_image_metadata(monkeypatch):
    def fake_prepare_flash_workflow(options, emit=None):
        del options, emit
        return SimpleNamespace(
            to_dict=lambda include_events=False: {
                "ok": True,
                **({"events": []} if include_events else {}),
                "image": {
                    "path": "/tmp/openmanet.img.gz",
                    "cached_path": "/tmp/openmanet.img.gz",
                    "version": "",
                    "url": "",
                    "sha256": "",
                },
            }
        )

    monkeypatch.setattr(bridge, "prepare_flash_workflow", fake_prepare_flash_workflow)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {
            "target": "rpi4-mm6108-spi",
            "cached_path": "/tmp/openmanet.img.gz",
            "version": "test-cache",
            "url": "https://example.invalid/openmanet.img.gz",
            "sha256": "a" * 64,
        },
    )

    payload = bridge.flash_plan_payload(
        config="examples/three-node-field-mesh.yml",
        node="point01",
        device="/dev/disk4",
    )

    assert payload["image"]["cached_path"] == "/tmp/openmanet.img.gz"
    assert payload["image"]["version"] == "test-cache"
    assert payload["image"]["url"] == "https://example.invalid/openmanet.img.gz"
    assert payload["image"]["sha256"] == "a" * 64


def test_desktop_bridge_prepare_flash_streams_events_and_final_result(monkeypatch, capsys):
    calls = []

    def fake_prepare_flash_workflow(options, emit=None):
        calls.append(options)
        assert emit is not None
        emit(FlashEvent("download_completed", "Saved image", data={"path": "/tmp/openmanet.img.gz"}))
        return SimpleNamespace(
            to_dict=lambda include_events=False: {
                "ok": True,
                "code": "ok",
                "image": {"cached_path": "/tmp/openmanet.img.gz"},
                "plan": {"ssh_enabled": False},
            }
        )

    monkeypatch.setattr(bridge, "prepare_flash_workflow", fake_prepare_flash_workflow)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {"cached_path": "/tmp/openmanet.img.gz"},
    )

    exit_code = bridge.main(
        [
            "prepare-flash",
            "--config",
            "examples/three-node-field-mesh.yml",
            "--node",
            "point01",
            "--device",
            "/dev/disk4",
            "--disable-ssh",
        ]
    )

    assert exit_code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["type"] == "event"
    assert lines[0]["event_type"] == "download_completed"
    assert lines[-1]["type"] == "result"
    assert lines[-1]["ok"] is True
    assert lines[-1]["plan"]["ssh_enabled"] is False
    assert calls[0].dry_run is False
    assert calls[0].yes is True
    assert calls[0].disable_ssh is True


def test_desktop_bridge_prepare_flash_payload_redacts_provision_secrets(tmp_path, monkeypatch):
    image = tmp_path / "openmanet.img.gz"
    image.write_bytes(b"firmware")
    config = tmp_path / "redaction-fleet.yml"
    raw_values = {
        "mesh": "redaction-mesh-value",
        "local_ap": "redaction-local-ap-value",
        "gateway_wifi": "redaction-gateway-wifi-value",
        "ssh_key": "ssh-ed25519 cmVkYWN0aW9uQXV0aG9yaXplZEtleQ== redaction-key",
    }
    _write_redaction_fleet(config, raw_values)
    monkeypatch.setattr(flash, "check_platform", lambda: None)
    monkeypatch.setattr(flash, "lookup_device", lambda _device: None)
    monkeypatch.setattr(flash, "assert_flash_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {},
    )

    payload = bridge.prepare_flash_payload(
        config=str(config),
        node="gate01",
        device="/dev/disk4",
        base_image=str(image),
    )

    encoded = json.dumps(payload)
    assert payload["provision"]["mesh"]["password"] == "<redacted>"
    assert payload["provision"]["node"]["local_ap"]["password"] == "<redacted>"
    assert payload["provision"]["node"]["gateway"]["wifi"]["password"] == "<redacted>"
    assert payload["provision"]["management"]["ssh_authorized_keys"] == ["<redacted>"]
    assert "<redacted>" in encoded
    for raw_value in raw_values.values():
        assert raw_value not in encoded


def test_desktop_bridge_prepare_flash_streams_failure_result(monkeypatch, capsys):
    def fake_prepare_flash_workflow(options, emit=None):
        assert options.yes is True
        assert emit is not None
        emit(FlashEvent("error", "Image download error: network unavailable", level="error"))
        return SimpleNamespace(
            to_dict=lambda include_events=False: {
                "ok": False,
                "exit_code": 1,
                "code": FlashErrorCode.IMAGE.value,
                "errors": ["Image download error: network unavailable"],
                "image": {},
            }
        )

    monkeypatch.setattr(bridge, "prepare_flash_workflow", fake_prepare_flash_workflow)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {"target": "rpi4-mm6108-spi"},
    )

    exit_code = bridge.main(
        [
            "prepare-flash",
            "--config",
            "examples/three-node-field-mesh.yml",
            "--node",
            "point01",
            "--device",
            "/dev/disk4",
        ]
    )

    assert exit_code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["type"] == "event"
    assert lines[0]["event_type"] == "error"
    assert lines[-1]["type"] == "result"
    assert lines[-1]["ok"] is False
    assert lines[-1]["code"] == FlashErrorCode.IMAGE.value
    assert lines[-1]["errors"] == ["Image download error: network unavailable"]


def test_desktop_bridge_flash_returns_sudo_fallback_on_privilege_error(monkeypatch):
    def fake_run_flash_workflow(options, emit=None):
        del options, emit
        return SimpleNamespace(
            to_dict=lambda include_events=False: {
                "ok": False,
                "code": FlashErrorCode.PRIVILEGE_REQUIRED.value,
                "errors": ["Write access is required"],
                "image": {"cached_path": "/tmp/openmanet.img.gz", "sha256": "a" * 64},
            }
        )

    monkeypatch.setattr(bridge, "run_flash_workflow", fake_run_flash_workflow)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {"cached_path": "/tmp/openmanet.img.gz", "sha256": "a" * 64},
    )
    monkeypatch.setattr(bridge.sys, "executable", "/Applications/EasyMANET.app/Contents/Resources/backend/easymanet-bridge/easymanet-bridge")
    monkeypatch.setattr(bridge.sys, "frozen", True, raising=False)

    payload = bridge.flash_payload(
        config="/Users/example/fleet.yml",
        node="point01",
        device="/dev/disk4",
        yes=True,
    )

    assert payload["ok"] is False
    assert payload["sudo_command"].startswith("sudo ")
    assert "easymanet-bridge flash" in payload["sudo_command"]
    assert "--base-image /tmp/openmanet.img.gz --image-sha256 " + "a" * 64 in payload["sudo_command"]


def test_desktop_bridge_sudo_fallback_preserves_unverified_custom_image(monkeypatch):
    def fake_run_flash_workflow(options, emit=None):
        del options, emit
        return SimpleNamespace(
            to_dict=lambda include_events=False: {
                "ok": False,
                "code": FlashErrorCode.PRIVILEGE_REQUIRED.value,
                "errors": ["Write access is required"],
                "image": {"path": "/tmp/custom-openmanet.img.gz", "sha256": ""},
            }
        )

    monkeypatch.setattr(bridge, "run_flash_workflow", fake_run_flash_workflow)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {"cached_path": "/tmp/default.img.gz", "sha256": "b" * 64},
    )

    payload = bridge.flash_payload(
        config="/Users/example/fleet.yml",
        node="point01",
        device="/dev/disk4",
        yes=True,
    )

    assert "--base-image /tmp/custom-openmanet.img.gz" in payload["sudo_command"]
    assert "--image-sha256" not in payload["sudo_command"]


def test_desktop_bridge_flash_streams_events_and_final_result(monkeypatch, capsys):
    def fake_run_flash_workflow(options, emit=None):
        assert options.yes is True
        assert emit is not None
        emit(FlashEvent("write_started", "Writing image"))
        return SimpleNamespace(
            to_dict=lambda include_events=False: {
                "ok": True,
                "code": "ok",
                "image": {"cached_path": "/tmp/openmanet.img.gz"},
            }
        )

    monkeypatch.setattr(bridge, "run_flash_workflow", fake_run_flash_workflow)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {"cached_path": "/tmp/openmanet.img.gz"},
    )

    exit_code = bridge.main(
        [
            "flash",
            "--config",
            "examples/three-node-field-mesh.yml",
            "--node",
            "point01",
            "--device",
            "/dev/disk4",
            "--yes",
        ]
    )

    assert exit_code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["type"] == "event"
    assert lines[0]["event_type"] == "write_started"
    assert lines[-1]["type"] == "result"
    assert lines[-1]["ok"] is True
    assert "events" not in lines[-1]


def test_desktop_bridge_flash_uses_core_internal_result(monkeypatch, capsys):
    def fake_run_flash_workflow(options, emit=None):
        assert options.yes is True
        assert emit is not None
        return SimpleNamespace(
            to_dict=lambda include_events=False: {
                "ok": False,
                "exit_code": 1,
                "code": FlashErrorCode.INTERNAL.value,
                "errors": ["Unexpected flash workflow error: OSError: download failed"],
                "image": {},
            }
        )

    monkeypatch.setattr(bridge, "run_flash_workflow", fake_run_flash_workflow)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {"target": "rpi4-mm6108-spi"},
    )

    exit_code = bridge.main(
        [
            "flash",
            "--config",
            "examples/three-node-field-mesh.yml",
            "--node",
            "point01",
            "--device",
            "/dev/disk4",
            "--yes",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "result"
    assert payload["ok"] is False
    assert payload["code"] == FlashErrorCode.INTERNAL.value
    assert payload["errors"] == ["Unexpected flash workflow error: OSError: download failed"]


def test_desktop_static_supports_electron_and_http_modes():
    root = Path(__file__).resolve().parents[1]
    index = root / "apps" / "desktop" / "src" / "easymanet_desktop" / "static" / "index.html"
    static = root / "apps" / "desktop" / "src" / "easymanet_desktop" / "static"
    app_js = static / "app.js"
    render_js = static / "render.js"
    styles = static / "styles.css"
    ipc_js = root / "apps" / "desktop" / "electron" / "ipc.js"

    assert 'href="styles.css"' in index.read_text()
    for script in (
        "render.js",
        "state.js",
        "api.js",
        "fleet.js",
        "disk.js",
        "flash-ui.js",
        "mesh.js",
        "diagnostics.js",
        "app.js",
    ):
        assert f'src="{script}"' in index.read_text()
    text = "\n".join(
        (static / name).read_text()
        for name in (
            "state.js",
            "api.js",
            "fleet.js",
            "disk.js",
            "flash-ui.js",
            "mesh.js",
            "diagnostics.js",
            "app.js",
        )
    )
    assert "window.easymanet" in text
    assert "nativeApi.getState" in text
    assert "nativeApi.chooseConfig" in text
    assert "nativeApi.openFleetsFolder" in text
    assert "nativeApi.discoverMesh" in text
    assert "nativeApi.runDiagnostics" in text
    assert "nativeApi.exportDiagnosticsBundle" in text
    assert "nativeApi.importBootReport" in text
    assert "nativeApi.flashPlan" in text
    assert "nativeApi.flash" in text
    assert "nativeApi.onFlashEvent" in text
    assert "nativeApi.copyText" in text
    assert "booleanFlag(payload.includeDisks)" in ipc_js.read_text()
    assert "fleet-select" in index.read_text()
    assert "open-fleets-folder" in index.read_text()
    assert "app-shell" in index.read_text()
    assert "sidebar-nav" in index.read_text()
    assert 'data-tab-target="tab-flash"' in index.read_text()
    assert 'data-tab-target="tab-mesh"' in index.read_text()
    assert 'data-tab-target="tab-diagnostics"' in index.read_text()
    assert 'data-tab-panel' in index.read_text()
    assert "mesh-discover" in index.read_text()
    assert '<select id="mesh-config-source"' in index.read_text()
    assert "mesh-scanning" in index.read_text()
    assert "mesh-radios" in index.read_text()
    assert "mesh-output" in index.read_text()
    assert "copy-mesh-log" in index.read_text()
    assert "diagnostics-run" in index.read_text()
    assert "diagnostics-export" in index.read_text()
    assert "diagnostics-import" in index.read_text()
    assert "diagnostics-copy" in index.read_text()
    assert "mesh-ssh-user" not in index.read_text()
    assert "flash-panel" in index.read_text()
    assert "preview-flash" in index.read_text()
    assert "start-flash" in index.read_text()
    assert "copy-flash-log" in index.read_text()
    assert "export-support-bundle" in index.read_text()
    assert "include_disks: true" in text
    assert "includeDisks: true" in text
    assert 'postJson("/api/support/bundle", payload)' in text
    assert "role-default-ssh" in index.read_text()
    assert "admin-password" in index.read_text()
    assert 'value="default"' not in index.read_text()
    assert '<select id="node-name" name="node" disabled>' in index.read_text()
    assert '<input id="node-name"' not in index.read_text()
    assert "renderFleets" in text
    assert "setupTabNavigation" in text
    assert "activateTab" in text
    assert "loadNodesForSelectedFleet" in text
    assert "renderNodeOptions" in text
    assert "discoverMesh" in text
    assert "renderMeshDiscovery" in text
    assert "resetMeshDiscovery" in text
    assert "selectFleetSource" in text
    assert "syncFleetSelectElement" in text
    assert "appendMeshLog" in text
    assert "meshLogLines" in text
    assert "partial results" in text
    assert "meshDiscover.textContent = busy ? \"Scanning...\" : \"Scan Mesh\"" in text
    assert "meshScanning.hidden = !busy" in text
    assert 'meshRadios.setAttribute("aria-busy", "true")' in text
    assert "applyRoleDefaultSsh" in text
    assert "node_roles" in text
    assert "node_access" in text
    assert "flashAccessHint" in text
    assert "Join ${ssid}" not in text
    assert "local_ap_ssid ? access.local_ap_ssid" not in text
    assert "ssh_enabled === true" in text
    assert "sshNote" not in text
    assert "Connect Ethernet, then SSH to root@" in text
    assert "Connect Ethernet to the node management port." in text
    assert "includeAdminPassword" in text
    assert "adminPassword" in text
    assert "detectMacPlatform" in text
    assert "classList.toggle" in text
    assert "flash-busy" in text
    assert "startDiskWatcher" in text
    assert "refreshDisksIfChanged" in text
    assert "diskInventorySignature" in text
    assert "visibilitychange" in text
    assert "setInterval(refreshDisksIfChanged" in text
    disk_error_body = text.split("function renderDiskError(error)", 1)[1].split(
        "function showCopied",
        1,
    )[0]
    assert 'state.diskDevice = "";' in disk_error_body
    assert 'selectedDisk.textContent = "None";' in disk_error_body
    assert "renderImageState" in text
    assert "refreshImageSidebar" in text
    assert "refreshImageUpdateStatus" in text
    assert "installImageUpdate" in text
    assert 'postJson("/api/image-updates/install", { target })' in text
    assert "new image available:" in render_js.read_text()
    assert "Install Update" in render_js.read_text()
    assert "data-image-install-target" in render_js.read_text()
    assert 'type === "download_completed"' in text
    assert "exportSupportBundle" in text
    assert "updateCopyFlashLogVisibility" in text
    assert "flashPanel.hidden = true" in text
    assert "safeTone" in render_js.read_text()
    assert "meshRadioCard" in render_js.read_text()
    assert "meshTopologyView" in render_js.read_text()
    assert "meshDiscoveryMarkup" in render_js.read_text()
    assert "untrusted official" in render_js.read_text()
    assert "image.imageStatus" in render_js.read_text()
    assert "ALLOWED_TONES" in render_js.read_text()
    assert '["ok", "warn", "bad", "subtle"]' in render_js.read_text()
    assert "body.flash-busy .appbar" in styles.read_text()
    assert "mesh-scanning" in styles.read_text()
    assert "mesh-grid" in styles.read_text()
    assert "topology-view" in styles.read_text()
    assert "topology-link" in styles.read_text()
    assert "@media print" in styles.read_text()


def test_desktop_renderer_safe_tone_allows_only_expected_classes():
    root = Path(__file__).resolve().parents[1]
    render_js = root / "apps" / "desktop" / "src" / "easymanet_desktop" / "static" / "render.js"
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("node is required for renderer safety test")
    script = """
const fs = require("node:fs");
const vm = require("node:vm");
const context = { window: {} };
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
const { safeTone } = context.window.EMRender;
const valid = ["ok", "warn", "bad", "subtle"];
const invalid = ["danger", "<script>", null, undefined, "ok bad"];
process.stdout.write(JSON.stringify({
  valid: Object.fromEntries(valid.map((tone) => [tone, safeTone(tone)])),
  invalid: invalid.map((tone) => safeTone(tone)),
}));
"""
    result = subprocess.run(
        [node_bin, "-e", script, str(render_js)],
        capture_output=True,
        check=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["valid"] == {
        "ok": "ok",
        "warn": "warn",
        "bad": "bad",
        "subtle": "subtle",
    }
    assert payload["invalid"] == ["subtle"] * 5


def test_desktop_static_containment_rejects_sibling_prefix(tmp_path):
    static_root = (tmp_path / "static").resolve()
    sibling = (tmp_path / "static-backup" / "secret.txt").resolve()

    assert server._is_relative_to(static_root / "index.html", static_root)
    assert not server._is_relative_to(sibling, static_root)


def test_electron_shell_files_exist():
    root = Path(__file__).resolve().parents[1]
    electron = root / "apps" / "desktop" / "electron"
    bridge_runner = electron / "scripts" / "run-build-bridge.js"
    bridge_text = (root / "apps" / "desktop" / "src" / "easymanet_desktop" / "bridge.py").read_text()

    assert (electron / "package.json").exists()
    assert (electron / "electron-builder.yml").exists()
    for module in (
        "main.js",
        "bridge-process.js",
        "constants.js",
        "elevated-flash.js",
        "environment.js",
        "ipc.js",
        "path-utils.js",
        "preload.js",
        "stream.js",
        "util.js",
        "validation.js",
        "window.js",
    ):
        assert (electron / module).exists()
    assert bridge_runner.exists()
    electron_text = "\n".join(path.read_text() for path in electron.glob("*.js"))
    main_text = (electron / "main.js").read_text()
    assert "registerIpc()" in main_text
    assert "createWindow()" in main_text
    assert "loadFile(indexHtmlPath())" in (electron / "window.js").read_text()
    assert "contextBridge.exposeInMainWorld" in (electron / "preload.js").read_text()
    assert "easymanet:open-fleets-folder" in electron_text
    assert "easymanet:image-updates" in electron_text
    assert "easymanet:image-update-install" in electron_text
    assert "easymanet:mesh-discover" in electron_text
    assert "easymanet:diagnostics-run" in electron_text
    assert "easymanet:diagnostics-bundle" in electron_text
    assert "easymanet:diagnostics-import-boot-report" in electron_text
    assert "easymanet:flash-plan" in electron_text
    assert "easymanet:flash" in electron_text
    assert "easymanet:flash-event" in electron_text
    assert "resolveConfigPath(config, {" in electron_text
    assert "fleetPathCandidates" not in electron_text
    assert "fleetExtensions" not in electron_text
    path_utils_text = (electron / "path-utils.js").read_text()
    assert "resolveConfigPath" in path_utils_text
    assert "hasTraversalSegment" in path_utils_text
    assert "resolve-config" in path_utils_text
    validation_text = (electron / "validation.js").read_text()
    assert "Boot report source path must not contain traversal segments" in validation_text
    assert "hasTraversalSegment(source)" in validation_text
    electron_check_text = (electron / "scripts" / "check-electron.js").read_text()
    assert "resolveConfigPath(\"field\"" in electron_check_text
    assert "formatCommandFailure" in electron_check_text
    assert "failed without stdout or stderr" in electron_check_text

    assert "flashBridgeTimeoutMs" in electron_text
    assert "runBridgeStreaming" in electron_text
    assert "fullStdout" in electron_text
    assert "isDestroyed" in electron_text
    assert "runFlashWithAdministratorPrivileges" in electron_text
    assert '"sudo"' in electron_text
    assert '"-S"' in electron_text
    assert "stageElevatedFlashInputs" in electron_text
    assert "fs.chmodSync(configPath, 0o600)" in electron_text
    assert "baseImageArgs(stagedImage)" in electron_text
    assert '"prepare-flash"' in bridge_text
    assert '"prepare-flash"' in electron_text
    assert '"install-image-update"' in bridge_text
    assert '"install-image-update"' in electron_text
    assert '"ensure-image"' not in bridge_text
    assert "ensureCachedImageForElevatedFlash" not in electron_text
    assert '"ensure-image"' not in electron_text
    assert "cleanupElevatedStage(options.stage);\n      resolve({ ok: false" in electron_text
    assert "const effectiveTimeoutMs = timeoutMs + 60000" in electron_text
    assert "after ${effectiveTimeoutMs / 1000}s" in electron_text
    assert "EasyMANET Flash Helper.app" not in electron_text
    assert 'spawn(sudo.command, sudo.args' in electron_text
    assert "Mac administrator password is required for flashing" in electron_text
    assert "with administrator privileges" not in electron_text
    assert 'spawn("osascript"' not in electron_text
    assert "streamEvents" not in electron_text
    assert "copyText" in (electron / "preload.js").read_text()
    assert "getImageUpdates" in (electron / "preload.js").read_text()
    assert "installImageUpdate" in (electron / "preload.js").read_text()
    assert "discoverMesh" in (electron / "preload.js").read_text()
    assert "onFlashEvent" in (electron / "preload.js").read_text()
    assert "EASYMANET_ELECTRON_NO_SOURCE_PATHS" in electron_text
    assert "bridgeTimeoutMs" in electron_text
    assert "meshBridgeTimeoutMs" in electron_text
    assert "process.resourcesPath" in electron_text
    assert "desktop-static" in electron_text
    assert "EASYMANET_BRIDGE_BIN is a development/testing override" in electron_text
    assert "EASYMANET_ELECTRON_ALLOW_BRIDGE_OVERRIDE" in electron_text
    assert "build:backend" in (electron / "package.json").read_text()
    assert "electron-builder" in (electron / "package.json").read_text()
    runner_text = bridge_runner.read_text()
    assert 'candidates.push("python", "py")' in runner_text
    assert 'process.env.PYTHON' in runner_text
    build_text = (electron / "scripts" / "build-bridge.py").read_text()
    assert '"easymanet_cli"' not in build_text
    assert 'ROOT / "apps" / "cli" / "src"' not in build_text
