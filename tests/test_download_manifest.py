import json

import pytest

from easymanet import _download_release, download
from easymanet.release_trust import (
    GITHUB_ACTIONS_ISSUER,
    IMAGE_RELEASE_BUNDLE_ASSET,
    OFFICIAL_IMAGE_REPO,
    OFFICIAL_IMAGE_REPOSITORY_URI,
    OFFICIAL_IMAGE_WORKFLOW_IDENTITY,
    PENDING_TRUST_STATUS,
    UNTRUSTED_STATUS,
    trust_from_manifest,
    verify_release_manifest_bundle,
)

TARGET = "rpi4-mm6108-spi"
IMAGE_NAME = "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
STABLE_TAG = "images-v0.3.0"


def _manifest(*, channel: str = "stable", release_tag: str = STABLE_TAG) -> dict:
    return {
        "schema_version": 2,
        "product": "easymanet-openmanet-image",
        "channel": channel,
        "release_tag": release_tag,
        "status": "current",
        "target": TARGET,
        "openmanet_version": "1.6.5",
        "artifact": {
            "target": TARGET,
            "filename": IMAGE_NAME,
            "sha256": "a" * 64,
        },
        "trust": {
            "expected_github_repo": OFFICIAL_IMAGE_REPO,
            "attestation_subject_digest": f"sha256:{'a' * 64}",
            "signature_assets": [f"{IMAGE_NAME}.sha256", IMAGE_RELEASE_BUNDLE_ASSET],
        },
    }


def _release(*, tag: str = STABLE_TAG, channel: str = "stable") -> dict:
    return {
        "tag_name": tag,
        "prerelease": channel == "candidate",
        "draft": False,
        "assets": [
            {
                "name": "easymanet-image-release.json",
                "browser_download_url": "https://example.invalid/easymanet-image-release.json",
            },
            {
                "name": IMAGE_RELEASE_BUNDLE_ASSET,
                "browser_download_url": f"https://example.invalid/{IMAGE_RELEASE_BUNDLE_ASSET}",
            },
            {
                "name": IMAGE_NAME,
                "browser_download_url": f"https://example.invalid/{IMAGE_NAME}",
            },
            {
                "name": f"{IMAGE_NAME}.sha256",
                "browser_download_url": f"https://example.invalid/{IMAGE_NAME}.sha256",
            },
        ],
    }


def _trust(manifest: dict, *, channel: str = "stable", tag: str = STABLE_TAG):
    return trust_from_manifest(
        manifest,
        assets=_release(tag=tag, channel=channel)["assets"],
        expected_repo=OFFICIAL_IMAGE_REPO,
        expected_channel=channel,
        target=TARGET,
        release_tag=tag,
        manifest_url="https://example.invalid/easymanet-image-release.json",
        manifest_signature_verified=True,
    )


def test_official_release_verifies_fixed_bundle_before_accepting_manifest(monkeypatch):
    release = _release()
    manifest = _manifest()
    fetch_calls = []

    monkeypatch.setattr(_download_release, "_fetch_github_release", lambda _repo: release)

    def fake_fetch(manifest_url, bundle_url):
        fetch_calls.append((manifest_url, bundle_url))
        return manifest

    monkeypatch.setattr(_download_release, "_fetch_release_manifest", fake_fetch)

    ref = download._check_github_release(OFFICIAL_IMAGE_REPO, TARGET)

    assert ref is not None
    assert ref.version == STABLE_TAG
    assert ref.sha256 == "a" * 64
    assert ref.trust_status == PENDING_TRUST_STATUS
    assert ref.manifest_signature_verified is True
    assert fetch_calls == [
        (
            "https://example.invalid/easymanet-image-release.json",
            f"https://example.invalid/{IMAGE_RELEASE_BUNDLE_ASSET}",
        )
    ]


def test_candidate_release_requires_matching_manifest_channel_and_tag(monkeypatch):
    tag = "images-v0.3.0-candidate.1"
    release = _release(tag=tag, channel="candidate")
    monkeypatch.setattr(_download_release, "_fetch_github_releases", lambda _repo: [release])
    monkeypatch.setattr(
        _download_release,
        "_fetch_release_manifest",
        lambda _manifest_url, _bundle_url: _manifest(channel="candidate", release_tag=tag),
    )

    ref = download._check_github_release(OFFICIAL_IMAGE_REPO, TARGET, channel="candidate")

    assert ref is not None
    assert ref.channel == "candidate"
    assert ref.release_tag == tag


@pytest.mark.parametrize("failure", ["malformed bundle", "bad signature", "identity mismatch"])
def test_manifest_bundle_verification_failures_are_fail_closed(monkeypatch, failure):
    payloads = {
        "https://example.invalid/manifest": json.dumps(_manifest()).encode(),
        "https://example.invalid/bundle": b"bundle",
    }
    monkeypatch.setattr(_download_release, "_fetch_release_asset", payloads.get)
    monkeypatch.setattr(
        _download_release,
        "verify_release_manifest_bundle",
        lambda *_args: (_ for _ in ()).throw(ValueError(failure)),
    )

    assert _download_release._fetch_release_manifest(
        "https://example.invalid/manifest",
        "https://example.invalid/bundle",
    ) is None


def test_manifest_is_verified_over_exact_raw_bytes_before_json_parsing(monkeypatch):
    manifest_bytes = json.dumps(_manifest(), separators=(",", ":")).encode() + b"\n"
    bundle_bytes = b"fixed-bundle-bytes"
    payloads = {
        "https://example.invalid/manifest": manifest_bytes,
        "https://example.invalid/bundle": bundle_bytes,
    }
    verified = []
    monkeypatch.setattr(_download_release, "_fetch_release_asset", payloads.get)
    monkeypatch.setattr(
        _download_release,
        "verify_release_manifest_bundle",
        lambda manifest, bundle: verified.append((manifest, bundle)),
    )

    result = _download_release._fetch_release_manifest(
        "https://example.invalid/manifest",
        "https://example.invalid/bundle",
    )

    assert result == _manifest()
    assert verified == [(manifest_bytes, bundle_bytes)]


def test_sigstore_verifier_pins_github_workflow_identity(monkeypatch):
    constructed = []

    class ValuePolicy:
        def __init__(self, value):
            self.value = value
            constructed.append((type(self).__name__, value))

    class Identity(ValuePolicy):
        def __init__(self, *, identity):
            super().__init__(identity)

    class AllOf:
        def __init__(self, children):
            self.children = children

    class Bundle:
        @staticmethod
        def from_json(raw):
            assert raw == b"bundle"
            return "parsed-bundle"

    class Verifier:
        @staticmethod
        def production():
            return Verifier()

        def verify_artifact(self, **kwargs):
            assert kwargs["input_"] == b"manifest"
            assert kwargs["bundle"] == "parsed-bundle"
            assert isinstance(kwargs["policy"], AllOf)

    policy_types = tuple(type(name, (ValuePolicy,), {}) for name in (
        "OIDCBuildSignerURI",
        "OIDCBuildTrigger",
        "OIDCIssuerV2",
        "OIDCRunnerEnvironment",
        "OIDCSourceRepositoryRef",
        "OIDCSourceRepositoryURI",
    ))
    monkeypatch.setattr(
        "easymanet.release_trust._sigstore_components",
        lambda: (Bundle, Verifier, AllOf, Identity, *policy_types),
    )

    verify_release_manifest_bundle(b"manifest", b"bundle")

    assert ("Identity", OFFICIAL_IMAGE_WORKFLOW_IDENTITY) in constructed
    assert ("OIDCIssuerV2", GITHUB_ACTIONS_ISSUER) in constructed
    assert ("OIDCSourceRepositoryURI", OFFICIAL_IMAGE_REPOSITORY_URI) in constructed
    assert ("OIDCSourceRepositoryRef", "refs/heads/main") in constructed
    assert ("OIDCRunnerEnvironment", "github-hosted") in constructed
    assert ("OIDCBuildTrigger", "workflow_dispatch") in constructed


@pytest.mark.parametrize("status", [None, "unsafe", "superseded", "revoked", "unknown"])
def test_manifest_requires_explicit_current_disposition(status):
    manifest = _manifest()
    if status is None:
        manifest.pop("status")
    else:
        manifest["status"] = status

    assert _trust(manifest).status == UNTRUSTED_STATUS


@pytest.mark.parametrize("schema_version", [1, 3, "2", True])
def test_manifest_requires_exact_current_schema(schema_version):
    manifest = _manifest()
    manifest["schema_version"] = schema_version

    assert _trust(manifest).status == UNTRUSTED_STATUS


def test_manifest_rejects_release_tag_and_channel_mismatches():
    assert _trust(_manifest(release_tag="images-v9.9.9")).status == UNTRUSTED_STATUS
    assert _trust(_manifest(channel="candidate")).status == UNTRUSTED_STATUS


def test_manifest_requires_fixed_bundle_and_checksum_assets():
    manifest = _manifest()
    manifest["trust"]["signature_assets"] = ["other.sigstore.json"]

    trust = _trust(manifest)

    assert trust.status == UNTRUSTED_STATUS
    assert "required trust assets" in trust.warnings[0]


def test_nonofficial_github_repo_is_checksum_only(monkeypatch):
    release = _release()
    release["assets"][2]["digest"] = f"sha256:{'a' * 64}"
    monkeypatch.setattr(_download_release, "_fetch_github_release", lambda _repo: release)
    monkeypatch.setattr(
        _download_release,
        "_fetch_release_manifest",
        lambda *_args: (_ for _ in ()).throw(AssertionError("custom repo manifest must not establish official trust")),
    )

    ref = download._check_github_release("owner/repo", TARGET)

    assert ref is not None
    assert ref.source == "custom"
    assert ref.trust_status == "checksum-only"
