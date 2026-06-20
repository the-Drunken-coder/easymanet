from easymanet import _download_release, download
from easymanet.release_trust import PENDING_TRUST_STATUS


def test_github_release_prefers_image_release_manifest(monkeypatch):
    image_name = "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    release = {
        "tag_name": "v1",
        "assets": [
            {
                "name": "easymanet-image-release.json",
                "browser_download_url": "https://example.invalid/easymanet-image-release.json",
            },
            {
                "name": image_name,
                "browser_download_url": f"https://example.invalid/{image_name}",
            },
            {
                "name": f"{image_name}.sha256",
                "browser_download_url": f"https://example.invalid/{image_name}.sha256",
            },
            {
                "name": "easymanet-image-release.json.sigstore.json",
                "browser_download_url": "https://example.invalid/easymanet-image-release.json.sigstore.json",
            },
        ],
    }
    manifest = {
        "schema_version": 2,
        "product": "easymanet-openmanet-image",
        "channel": "stable",
        "release_tag": "v1",
        "target": "rpi4-mm6108-spi",
        "openmanet_version": "1.6.5",
        "artifact": {
            "filename": image_name,
            "sha256": "a" * 64,
        },
        "trust": {
            "expected_github_repo": "owner/repo",
            "attestation_subject_digest": f"sha256:{'a' * 64}",
            "signature_assets": [f"{image_name}.sha256", "easymanet-image-release.json.sigstore.json"],
        },
    }

    monkeypatch.setattr(_download_release, "_fetch_github_release", lambda _repo: release)
    monkeypatch.setattr(_download_release, "_fetch_release_manifest", lambda _url: manifest)

    ref = download._check_github_release("owner/repo", "rpi4-mm6108-spi")

    assert ref is not None
    assert ref.version == "v1"
    assert ref.url == f"https://example.invalid/{image_name}"
    assert ref.sha256 == "a" * 64
    assert ref.trust_status == PENDING_TRUST_STATUS
    assert ref.trust["expected_repo"] == "owner/repo"


def test_candidate_channel_discovers_prerelease_manifest(monkeypatch):
    image_name = "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    release = {
        "tag_name": "images-v0.3.0-candidate.1",
        "prerelease": True,
        "draft": False,
        "assets": [
            {
                "name": "easymanet-image-release.json",
                "browser_download_url": "https://example.invalid/easymanet-image-release.json",
            },
            {
                "name": image_name,
                "browser_download_url": f"https://example.invalid/{image_name}",
            },
            {"name": f"{image_name}.sha256"},
            {"name": "easymanet-image-release.json.sigstore.json"},
        ],
    }
    manifest = {
        "schema_version": 2,
        "product": "easymanet-openmanet-image",
        "channel": "candidate",
        "target": "rpi4-mm6108-spi",
        "artifact": {"filename": image_name, "sha256": "a" * 64},
        "trust": {
            "expected_github_repo": "owner/repo",
            "attestation_subject_digest": f"sha256:{'a' * 64}",
            "signature_assets": [f"{image_name}.sha256", "easymanet-image-release.json.sigstore.json"],
        },
    }

    monkeypatch.setattr(_download_release, "_fetch_github_releases", lambda _repo: [release])
    monkeypatch.setattr(_download_release, "_fetch_release_manifest", lambda _url: manifest)

    ref = download._check_github_release("owner/repo", "rpi4-mm6108-spi", channel="candidate")

    assert ref is not None
    assert ref.channel == "candidate"
    assert ref.release_tag == "images-v0.3.0-candidate.1"


def test_release_manifest_missing_signature_assets_is_untrusted():
    image_name = "image.img.gz"
    ref = download._image_ref_from_release_manifest(
        {
            "schema_version": 2,
            "product": "easymanet-openmanet-image",
            "channel": "stable",
            "target": "rpi4-mm6108-spi",
            "artifact": {"filename": image_name, "sha256": "a" * 64},
            "trust": {
                "expected_github_repo": "owner/repo",
                "attestation_subject_digest": f"sha256:{'a' * 64}",
                "signature_assets": ["missing.sigstore.json"],
            },
        },
        [{"name": image_name, "browser_download_url": "https://example.invalid/image.img.gz"}],
        "rpi4-mm6108-spi",
        expected_repo="owner/repo",
        manifest_url="https://example.invalid/easymanet-image-release.json",
    )

    assert ref is not None
    assert ref.trust_status == "untrusted"


def test_release_manifest_missing_required_trust_fields_is_untrusted():
    image_name = "image.img.gz"
    ref = download._image_ref_from_release_manifest(
        {
            "schema_version": 2,
            "product": "easymanet-openmanet-image",
            "channel": "stable",
            "target": "rpi4-mm6108-spi",
            "artifact": {"filename": image_name, "sha256": "a" * 64},
            "trust": {
                "signature_assets": [f"{image_name}.sha256"],
            },
        },
        [{"name": image_name, "browser_download_url": "https://example.invalid/image.img.gz"}, {"name": f"{image_name}.sha256"}],
        "rpi4-mm6108-spi",
        expected_repo="owner/repo",
        manifest_url="https://example.invalid/easymanet-image-release.json",
    )

    assert ref is not None
    assert ref.trust_status == "untrusted"


def test_release_manifest_invalid_schema_version_is_untrusted():
    image_name = "image.img.gz"
    ref = download._image_ref_from_release_manifest(
        {
            "schema_version": "v2",
            "product": "easymanet-openmanet-image",
            "channel": "stable",
            "target": "rpi4-mm6108-spi",
            "artifact": {"filename": image_name, "sha256": "a" * 64},
        },
        [{"name": image_name, "browser_download_url": "https://example.invalid/image.img.gz"}],
        "rpi4-mm6108-spi",
        expected_repo="owner/repo",
        manifest_url="https://example.invalid/easymanet-image-release.json",
    )

    assert ref is not None
    assert ref.trust_status == "untrusted"


def test_release_manifest_ignores_wrong_target():
    ref = download._image_ref_from_release_manifest(
        {
            "target": "other-target",
            "artifact": {"filename": "image.img.gz", "sha256": "a" * 64},
        },
        [{"name": "image.img.gz", "browser_download_url": "https://example.invalid/image.img.gz"}],
        "rpi4-mm6108-spi",
    )

    assert ref is None
