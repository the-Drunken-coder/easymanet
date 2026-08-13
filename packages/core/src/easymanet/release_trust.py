"""Image release manifest trust helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from ._download_integrity import normalize_sha256

IMAGE_RELEASE_PRODUCT = "easymanet-openmanet-image"
IMAGE_RELEASE_SCHEMA_VERSION = 2
IMAGE_RELEASE_MANIFEST_ASSET = "easymanet-image-release.json"
IMAGE_RELEASE_BUNDLE_ASSET = f"{IMAGE_RELEASE_MANIFEST_ASSET}.sigstore.json"
OFFICIAL_IMAGE_REPO = "the-Drunken-coder/easymanet-images"
OFFICIAL_IMAGE_WORKFLOW = ".github/workflows/image-release.yml"
OFFICIAL_IMAGE_SIGNER_WORKFLOW = f"{OFFICIAL_IMAGE_REPO}/{OFFICIAL_IMAGE_WORKFLOW}"
OFFICIAL_IMAGE_WORKFLOW_IDENTITY = (
    f"https://github.com/{OFFICIAL_IMAGE_SIGNER_WORKFLOW}@refs/heads/main"
)
OFFICIAL_IMAGE_REPOSITORY_URI = f"https://github.com/{OFFICIAL_IMAGE_REPO}"
GITHUB_ACTIONS_ISSUER = "https://token.actions.githubusercontent.com"

OFFICIAL_TRUST_STATUS = "verified"
PENDING_TRUST_STATUS = "verification-pending"
CUSTOM_TRUST_STATUS = "checksum-only"
UNTRUSTED_STATUS = "untrusted"
ALLOWED_CHANNELS = {"stable", "candidate"}
CURRENT_IMAGE_STATUS = "current"

_STABLE_TAG_RE = re.compile(r"^images-v\d+\.\d+\.\d+$")
_CANDIDATE_TAG_RE = re.compile(r"^images-v\d+\.\d+\.\d+-candidate\.\d+$")


@dataclass(frozen=True)
class ReleaseTrust:
    status: str
    source: str
    channel: str = ""
    release_tag: str = ""
    image_status: str = ""
    manifest_url: str = ""
    manifest_schema_version: int = 0
    manifest_signature_verified: bool = False
    expected_repo: str = ""
    attestation_subject_digest: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "channel": self.channel,
            "release_tag": self.release_tag,
            "image_status": self.image_status,
            "manifest_url": self.manifest_url,
            "manifest_schema_version": self.manifest_schema_version,
            "manifest_signature_verified": self.manifest_signature_verified,
            "expected_repo": self.expected_repo,
            "attestation_subject_digest": self.attestation_subject_digest,
            "warnings": list(self.warnings),
        }


def custom_trust(*, channel: str = "", release_tag: str = "") -> ReleaseTrust:
    return ReleaseTrust(
        status=CUSTOM_TRUST_STATUS,
        source="custom",
        channel=channel,
        release_tag=release_tag,
        warnings=("Custom image is checksum-only and not an official EasyMANET release.",),
    )


def untrusted_release(reason: str, *, manifest_url: str = "", release_tag: str = "") -> ReleaseTrust:
    return ReleaseTrust(
        status=UNTRUSTED_STATUS,
        source="official",
        release_tag=release_tag,
        manifest_url=manifest_url,
        warnings=(reason,),
    )


def verify_release_manifest_bundle(manifest_bytes: bytes, bundle_bytes: bytes) -> None:
    """Verify a fixed Sigstore bundle over the exact manifest bytes."""
    (
        Bundle,
        Verifier,
        AllOf,
        Identity,
        OIDCBuildSignerURI,
        OIDCBuildTrigger,
        OIDCIssuerV2,
        OIDCRunnerEnvironment,
        OIDCSourceRepositoryRef,
        OIDCSourceRepositoryURI,
    ) = _sigstore_components()
    policy = AllOf(
        [
            Identity(identity=OFFICIAL_IMAGE_WORKFLOW_IDENTITY),
            OIDCIssuerV2(GITHUB_ACTIONS_ISSUER),
            OIDCBuildSignerURI(OFFICIAL_IMAGE_WORKFLOW_IDENTITY),
            OIDCSourceRepositoryURI(OFFICIAL_IMAGE_REPOSITORY_URI),
            OIDCSourceRepositoryRef("refs/heads/main"),
            OIDCRunnerEnvironment("github-hosted"),
            OIDCBuildTrigger("workflow_dispatch"),
        ]
    )
    bundle = Bundle.from_json(bundle_bytes)
    Verifier.production().verify_artifact(
        input_=manifest_bytes,
        bundle=bundle,
        policy=policy,
    )


def _sigstore_components() -> tuple[Any, ...]:
    from sigstore.models import Bundle
    from sigstore.verify.policy import (
        AllOf,
        Identity,
        OIDCBuildSignerURI,
        OIDCBuildTrigger,
        OIDCIssuerV2,
        OIDCRunnerEnvironment,
        OIDCSourceRepositoryRef,
        OIDCSourceRepositoryURI,
    )
    from sigstore.verify.verifier import Verifier

    return (
        Bundle,
        Verifier,
        AllOf,
        Identity,
        OIDCBuildSignerURI,
        OIDCBuildTrigger,
        OIDCIssuerV2,
        OIDCRunnerEnvironment,
        OIDCSourceRepositoryRef,
        OIDCSourceRepositoryURI,
    )


def trust_from_manifest(
    manifest: dict[str, Any],
    *,
    assets: list[dict[str, Any]],
    expected_repo: str,
    expected_channel: str,
    target: str,
    release_tag: str,
    manifest_url: str,
    manifest_signature_verified: bool,
) -> ReleaseTrust:
    if not manifest_signature_verified:
        return untrusted_release(
            "Image manifest signature was not verified.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )

    schema_version = manifest.get("schema_version")
    if type(schema_version) is not int or schema_version != IMAGE_RELEASE_SCHEMA_VERSION:
        return untrusted_release(
            f"Image manifest schema_version must be {IMAGE_RELEASE_SCHEMA_VERSION}.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )
    if manifest.get("product") != IMAGE_RELEASE_PRODUCT:
        return untrusted_release(
            "Image manifest product is not recognized.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )
    if manifest.get("target") != target:
        return untrusted_release(
            "Image manifest target does not match the requested target.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )

    channel = manifest.get("channel")
    if channel not in ALLOWED_CHANNELS or channel != expected_channel:
        return untrusted_release(
            "Image manifest channel does not match the requested release channel.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )
    manifest_release_tag = manifest.get("release_tag")
    if not isinstance(manifest_release_tag, str) or manifest_release_tag != release_tag:
        return untrusted_release(
            "Image manifest release_tag does not match the GitHub release tag.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )
    tag_pattern = _STABLE_TAG_RE if channel == "stable" else _CANDIDATE_TAG_RE
    if not tag_pattern.fullmatch(release_tag):
        return untrusted_release(
            "Image release tag is not valid for its release channel.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )

    image_status = manifest.get("status")
    if image_status != CURRENT_IMAGE_STATUS:
        return untrusted_release(
            "Image manifest status must be explicitly current.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )

    artifact = manifest.get("artifact")
    if not isinstance(artifact, dict) or artifact.get("target") != target:
        return untrusted_release(
            "Image manifest artifact target does not match the requested target.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )
    artifact_filename = artifact.get("filename")
    if not isinstance(artifact_filename, str) or not artifact_filename:
        return untrusted_release(
            "Image manifest artifact filename is missing.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )
    try:
        artifact_sha = normalize_sha256(str(artifact.get("sha256", "")))
    except ValueError:
        return untrusted_release(
            "Image manifest artifact SHA-256 is invalid.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )

    trust = manifest.get("trust")
    if not isinstance(trust, dict):
        return untrusted_release(
            "Official image manifest trust metadata is malformed.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )
    declared_repo = trust.get("expected_github_repo")
    if expected_repo != OFFICIAL_IMAGE_REPO or declared_repo != OFFICIAL_IMAGE_REPO:
        return untrusted_release(
            "Image manifest was not issued for the pinned official image repo.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )

    subject = trust.get("attestation_subject_digest")
    if not isinstance(subject, str):
        return untrusted_release(
            "Official image manifest does not declare an attestation subject digest.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )
    try:
        subject_sha = normalize_sha256(subject)
    except ValueError:
        return untrusted_release(
            "Image attestation subject digest is invalid.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )
    if subject_sha != artifact_sha:
        return untrusted_release(
            "Image attestation digest does not match the artifact SHA-256.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )

    signature_assets = trust.get("signature_assets")
    if not isinstance(signature_assets, list) or not all(
        isinstance(name, str) and name for name in signature_assets
    ):
        return untrusted_release(
            "Official image manifest signature assets are malformed.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )
    required_assets = {f"{artifact_filename}.sha256", IMAGE_RELEASE_BUNDLE_ASSET}
    if not required_assets.issubset(signature_assets):
        return untrusted_release(
            "Official image manifest does not list all required trust assets.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )
    asset_names = {asset.get("name") for asset in assets if isinstance(asset, dict)}
    missing_assets = sorted(required_assets - asset_names)
    if missing_assets:
        return untrusted_release(
            f"Official image release is missing trust assets: {', '.join(missing_assets)}.",
            manifest_url=manifest_url,
            release_tag=release_tag,
        )

    return ReleaseTrust(
        status=PENDING_TRUST_STATUS,
        source="official",
        channel=channel,
        release_tag=manifest_release_tag,
        image_status=image_status,
        manifest_url=manifest_url,
        manifest_schema_version=schema_version,
        manifest_signature_verified=True,
        expected_repo=OFFICIAL_IMAGE_REPO,
        attestation_subject_digest=f"sha256:{subject_sha}",
    )


def image_trust_payload(trust: ReleaseTrust | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(trust, ReleaseTrust):
        return trust.to_dict()
    if isinstance(trust, dict):
        return dict(trust)
    return {}
