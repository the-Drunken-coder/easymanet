import hashlib
import json

from easymanet import __version__
from easymanet_image.release import IMAGE_RELEASE_MANIFEST, build_release_manifest, write_release_manifest


def test_build_release_manifest_records_artifact_and_provenance(tmp_path):
    artifact = tmp_path / "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    artifact.write_bytes(b"firmware")

    manifest = build_release_manifest(
        artifact=artifact,
        target="rpi4-mm6108-spi",
        openmanet_version="1.6.5",
        board="ekh-bcm2711",
        channel="stable",
        source_ref="abc123",
    )

    assert manifest["schema_version"] == 2
    assert manifest["product"] == "easymanet-openmanet-image"
    assert manifest["target"] == "rpi4-mm6108-spi"
    assert manifest["openmanet_version"] == "1.6.5"
    assert manifest["easymanet_version"] == __version__
    assert manifest["artifact"]["filename"] == artifact.name
    assert manifest["artifact"]["sha256"] == hashlib.sha256(b"firmware").hexdigest()
    assert manifest["provenance"]["monorepo_source"] == "abc123"
    assert manifest["trust"]["attestation_subject_digest"] == f"sha256:{hashlib.sha256(b'firmware').hexdigest()}"
    assert manifest["status"] == "current"


def test_write_release_manifest_outputs_json_file(tmp_path):
    artifact = tmp_path / "image.img.gz"
    artifact.write_bytes(b"firmware")

    path = write_release_manifest(
        artifact=artifact,
        output_dir=tmp_path / "dist",
        target="rpi4-mm6108-spi",
        openmanet_version="1.6.5",
        board="ekh-bcm2711",
    )

    assert path.name == IMAGE_RELEASE_MANIFEST
    payload = json.loads(path.read_text())
    assert payload["artifact"]["filename"] == "image.img.gz"
