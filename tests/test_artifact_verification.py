import gzip
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "packaging" / "verify_artifacts.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("verify_artifacts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_image(path: Path, payload: bytes = b"firmware") -> None:
    with gzip.open(path, "wb") as handle:
        handle.write(payload)


def release_manifest_payload(verifier, artifact: Path) -> dict:
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return {
        "schema_version": verifier.IMAGE_RELEASE_SCHEMA_VERSION,
        "product": verifier.IMAGE_RELEASE_PRODUCT,
        "target": verifier.TARGET,
        "artifact": {
            "filename": artifact.name,
            "size_bytes": artifact.stat().st_size,
            "sha256": digest,
        },
    }


def test_release_manifest_matches_artifact(tmp_path):
    verifier = load_verifier()
    artifact = tmp_path / "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    write_image(artifact)
    manifest = tmp_path / "easymanet-image-release.json"
    manifest.write_text(json.dumps(release_manifest_payload(verifier, artifact)))

    detail = verifier.verify_release_manifest(artifact, manifest)

    assert artifact.name in detail


def test_release_manifest_rejects_artifact_mismatch(tmp_path):
    verifier = load_verifier()
    artifact = tmp_path / "image.img.gz"
    write_image(artifact)
    manifest = tmp_path / "easymanet-image-release.json"
    payload = release_manifest_payload(verifier, artifact)
    payload["artifact"]["filename"] = "other.img.gz"
    payload["artifact"]["size_bytes"] = artifact.stat().st_size + 1
    payload["artifact"]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload))

    with pytest.raises(verifier.ArtifactVerificationError) as exc_info:
        verifier.verify_release_manifest(artifact, manifest)

    assert "filename expected" in str(exc_info.value)
    assert "size_bytes expected" in str(exc_info.value)
    assert "sha256 expected" in str(exc_info.value)


def test_release_manifest_rejects_metadata_mismatch(tmp_path):
    verifier = load_verifier()
    artifact = tmp_path / "image.img.gz"
    write_image(artifact)
    manifest = tmp_path / "easymanet-image-release.json"
    payload = release_manifest_payload(verifier, artifact)
    payload["schema_version"] = 1
    payload["product"] = "other-product"
    payload["target"] = "other-target"
    manifest.write_text(json.dumps(payload))

    with pytest.raises(verifier.ArtifactVerificationError) as exc_info:
        verifier.verify_release_manifest(artifact, manifest)

    assert "schema_version expected" in str(exc_info.value)
    assert "product expected" in str(exc_info.value)
    assert "target expected" in str(exc_info.value)


def test_release_manifest_rejects_non_object_payload(tmp_path):
    verifier = load_verifier()
    artifact = tmp_path / "image.img.gz"
    write_image(artifact)
    manifest = tmp_path / "easymanet-image-release.json"
    manifest.write_text(json.dumps([]))

    with pytest.raises(verifier.ArtifactVerificationError) as exc_info:
        verifier.verify_release_manifest(artifact, manifest)

    assert "release manifest must be a JSON object" in str(exc_info.value)


def test_required_overlay_files_and_executable_modes_detect_drift(tmp_path):
    verifier = load_verifier()
    overlay = tmp_path / "overlay"
    for rel_path in verifier.REQUIRED_OVERLAY_FILES:
        path = overlay / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")

    missing = overlay / verifier.REQUIRED_OVERLAY_FILES[0]
    missing.unlink()
    with pytest.raises(verifier.ArtifactVerificationError, match="required overlay files"):
        verifier.verify_required_overlay_files(overlay)

    missing.write_text("#!/bin/sh\n")
    for rel_path in verifier.EXECUTABLE_OVERLAY_FILES:
        (overlay / rel_path).chmod(0o755)
    non_executable = overlay / verifier.EXECUTABLE_OVERLAY_FILES[0]
    non_executable.chmod(0o644)

    with pytest.raises(verifier.ArtifactVerificationError, match="not user-executable"):
        verifier.verify_overlay_executable_modes(overlay)


def test_boot_payload_fixture_stages_provision_json():
    verifier = load_verifier()

    detail = verifier.verify_boot_payload_fixture()

    assert "point01" in detail


def test_image_cache_read_only_fixture_passes():
    verifier = load_verifier()

    detail = verifier.verify_image_cache_read_only()

    assert "unchanged" in detail


def test_main_requires_artifact_and_release_manifest_pair(tmp_path, capsys):
    verifier = load_verifier()
    artifact = tmp_path / "image.img.gz"
    write_image(artifact)

    result = verifier.main(["--artifact", str(artifact)])

    captured = capsys.readouterr()
    assert result == 1
    assert "pass --artifact and --release-manifest together" in captured.err
