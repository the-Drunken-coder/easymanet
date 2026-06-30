#!/usr/bin/env python3
"""Verify EasyMANET release artifacts without flashing hardware."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent

for source_root in (
    ROOT / "packages" / "core" / "src",
    ROOT / "packages" / "image" / "src",
    ROOT / "apps" / "desktop" / "src",
):
    source_text = str(source_root)
    if source_root.exists() and source_text not in sys.path:
        sys.path.insert(0, source_text)

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import verify_overlay_packaging
from easymanet._download_integrity import (
    image_sha256,
    normalize_sha256,
    valid_image_payload,
)
from easymanet.inject import stage_boot_payload
from easymanet.manifest import load_manifest
from easymanet_desktop.payloads import state_payload
from easymanet_image.release import IMAGE_RELEASE_SCHEMA_VERSION
from easymanet_image.release import IMAGE_RELEASE_PRODUCT

TARGET = "rpi4-mm6108-spi"
DEFAULT_FLEET = ROOT / "examples" / "three-node-field-mesh.yml"
DEFAULT_NODE = "point01"
RELEASE_MANIFEST_NAME = "easymanet-image-release.json"
OVERLAY = ROOT / "images" / "openmanet" / "provisioning" / "openwrt-overlay"
REQUIRED_OVERLAY_FILES = (
    "etc/easymanet/provision.json",
    "etc/init.d/easymanet-boot-report",
    "etc/init.d/easymanet-display-status",
    "etc/init.d/easymanet-led-status",
    "etc/init.d/easymanet-management-lan",
    "etc/uci-defaults/95-easymanet-display-status",
    "etc/uci-defaults/96-easymanet-led-status",
    "etc/uci-defaults/97-easymanet-management-lan",
    "etc/uci-defaults/98-easymanet-boot-report",
    "etc/uci-defaults/99-easymanet",
    "usr/lib/easymanet/api-lib.sh",
    "usr/lib/easymanet/api.sh",
    "usr/lib/easymanet/boot-report.sh",
    "usr/lib/easymanet/display-status.sh",
    "usr/lib/easymanet/led-status.sh",
    "usr/lib/easymanet/network.sh",
    "usr/lib/easymanet/provision-lib.sh",
    "usr/lib/easymanet/provision-runtime.sh",
    "usr/lib/easymanet/provision.sh",
    "usr/lib/easymanet/status-lib.sh",
    "www/easymanet-api/v1/identity",
    "www/easymanet-api/v1/neighbors",
    "www/easymanet-api/v1/status",
    "www/easymanet-api/v1/topology",
)
EXECUTABLE_OVERLAY_FILES = (
    "etc/init.d/easymanet-boot-report",
    "etc/init.d/easymanet-display-status",
    "etc/init.d/easymanet-led-status",
    "etc/init.d/easymanet-management-lan",
    "etc/uci-defaults/95-easymanet-display-status",
    "etc/uci-defaults/96-easymanet-led-status",
    "etc/uci-defaults/97-easymanet-management-lan",
    "etc/uci-defaults/98-easymanet-boot-report",
    "etc/uci-defaults/99-easymanet",
    "usr/lib/easymanet/api.sh",
    "usr/lib/easymanet/boot-report.sh",
    "usr/lib/easymanet/display-status.sh",
    "usr/lib/easymanet/led-status.sh",
    "usr/lib/easymanet/network.sh",
    "usr/lib/easymanet/provision.sh",
    "usr/lib/easymanet/status-lib.sh",
    "www/easymanet-api/v1/identity",
    "www/easymanet-api/v1/neighbors",
    "www/easymanet-api/v1/status",
    "www/easymanet-api/v1/topology",
)


class ArtifactVerificationError(Exception):
    """Raised when a non-hardware artifact check fails."""


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    checks: list[tuple[str, Any]] = [
        ("overlay packaging", verify_overlay_packaging_check),
        ("required overlay files", verify_required_overlay_files),
        ("overlay executable modes", verify_overlay_executable_modes),
        (
            "boot payload fixture",
            lambda: verify_boot_payload_fixture(args.fleet, args.node),
        ),
        ("image cache read-only state", verify_image_cache_read_only),
    ]
    if args.artifact or args.release_manifest:
        if not args.artifact or not args.release_manifest:
            print(
                "FAIL release manifest: pass --artifact and --release-manifest together",
                file=sys.stderr,
            )
            return 1
        checks.append(
            (
                "release manifest",
                lambda: verify_release_manifest(
                    args.artifact,
                    args.release_manifest,
                    target=args.target,
                ),
            )
        )
    else:
        print(
            "SKIP release manifest: pass --artifact IMAGE and "
            f"--release-manifest {RELEASE_MANIFEST_NAME}"
        )

    failed = False
    for label, check in checks:
        try:
            detail = check()
        except ArtifactVerificationError as exc:
            failed = True
            print(f"FAIL {label}: {exc}", file=sys.stderr)
            continue
        print(f"OK {label}: {detail}")

    if failed:
        return 1
    print("Artifact verification passed.")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        type=Path,
        help="Built .img or .img.gz artifact to compare with the release manifest.",
    )
    parser.add_argument(
        "--release-manifest",
        type=Path,
        help=f"Path to {RELEASE_MANIFEST_NAME}.",
    )
    parser.add_argument(
        "--fleet",
        type=Path,
        default=DEFAULT_FLEET,
        help="Fleet file used for the synthetic boot-payload fixture.",
    )
    parser.add_argument(
        "--node",
        default=DEFAULT_NODE,
        help="Node in --fleet used for the synthetic boot-payload fixture.",
    )
    parser.add_argument(
        "--target",
        default=TARGET,
        help="Image target expected in the release manifest.",
    )
    return parser.parse_args(argv)


def verify_overlay_packaging_check() -> str:
    try:
        missing = verify_overlay_packaging.missing_packaged_overlay_paths()
        count = len(verify_overlay_packaging.overlay_files())
    except FileNotFoundError as exc:
        raise ArtifactVerificationError(str(exc)) from exc
    if missing:
        details = "\n  ".join(missing)
        raise ArtifactVerificationError(
            "overlay files missing from pyproject.toml data-files:\n  "
            f"{details}"
        )
    return f"{count} overlay files listed in pyproject.toml"


def verify_required_overlay_files(overlay: Path = OVERLAY) -> str:
    missing = [
        rel_path
        for rel_path in REQUIRED_OVERLAY_FILES
        if not (overlay / rel_path).is_file()
    ]
    if missing:
        details = "\n  ".join(missing)
        raise ArtifactVerificationError(f"required overlay files missing:\n  {details}")
    return f"{len(REQUIRED_OVERLAY_FILES)} required files present"


def verify_overlay_executable_modes(overlay: Path = OVERLAY) -> str:
    not_executable = []
    for rel_path in EXECUTABLE_OVERLAY_FILES:
        path = overlay / rel_path
        if not path.is_file():
            not_executable.append(f"{rel_path} (missing)")
            continue
        if not path.stat().st_mode & stat.S_IXUSR:
            not_executable.append(rel_path)
    if not_executable:
        details = "\n  ".join(not_executable)
        raise ArtifactVerificationError(f"overlay files are not user-executable:\n  {details}")
    return f"{len(EXECUTABLE_OVERLAY_FILES)} executable modes present"


def verify_release_manifest(
    artifact: Path,
    release_manifest: Path,
    *,
    target: str = TARGET,
) -> str:
    artifact = artifact.expanduser().resolve()
    release_manifest = release_manifest.expanduser().resolve()
    if not artifact.is_file():
        raise ArtifactVerificationError(f"artifact not found: {artifact}")
    if not release_manifest.is_file():
        raise ArtifactVerificationError(f"release manifest not found: {release_manifest}")
    if not valid_image_payload(artifact, artifact.name):
        raise ArtifactVerificationError(
            f"artifact is not a valid .img or .img.gz payload: {artifact.name}"
        )

    try:
        payload = json.loads(release_manifest.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactVerificationError(f"could not read release manifest: {exc}") from exc
    if not isinstance(payload, dict):
        raise ArtifactVerificationError("release manifest must be a JSON object")
    artifact_entry = payload.get("artifact")
    if not isinstance(artifact_entry, dict):
        raise ArtifactVerificationError("release manifest artifact field must be an object")

    expected_size = artifact.stat().st_size
    expected_sha = image_sha256(artifact)
    errors = []
    if payload.get("schema_version") != IMAGE_RELEASE_SCHEMA_VERSION:
        errors.append(
            "schema_version expected "
            f"{IMAGE_RELEASE_SCHEMA_VERSION}, got {payload.get('schema_version')!r}"
        )
    if payload.get("product") != IMAGE_RELEASE_PRODUCT:
        errors.append(
            f"product expected {IMAGE_RELEASE_PRODUCT!r}, got {payload.get('product')!r}"
        )
    if payload.get("target") != target:
        errors.append(f"target expected {target!r}, got {payload.get('target')!r}")
    if artifact_entry.get("filename") != artifact.name:
        errors.append(
            f"filename expected {artifact.name!r}, got {artifact_entry.get('filename')!r}"
        )
    if artifact_entry.get("size_bytes") != expected_size:
        errors.append(
            f"size_bytes expected {expected_size}, got {artifact_entry.get('size_bytes')!r}"
        )
    try:
        actual_sha = normalize_sha256(str(artifact_entry.get("sha256", "")))
    except ValueError:
        actual_sha = str(artifact_entry.get("sha256", ""))
        errors.append(f"sha256 is not a valid SHA-256: {actual_sha!r}")
    else:
        if actual_sha != expected_sha:
            errors.append(f"sha256 expected {expected_sha}, got {actual_sha}")
    if errors:
        raise ArtifactVerificationError("; ".join(errors))
    return f"{artifact.name} matches manifest metadata, size, and SHA-256"


def verify_boot_payload_fixture(fleet: Path = DEFAULT_FLEET, node: str = DEFAULT_NODE) -> str:
    fleet = fleet.expanduser().resolve()
    if not fleet.is_file():
        raise ArtifactVerificationError(f"fleet file not found: {fleet}")
    manifest = load_manifest(str(fleet))
    with tempfile.TemporaryDirectory(prefix="easymanet-boot-fat-") as tmp:
        boot_root = Path(tmp)
        (boot_root / "cmdline.txt").write_text(
            "console=ttyAMA0 root=/dev/sda2 rootfstype=squashfs rootwait\n"
        )
        (boot_root / "partuuid.txt").write_text("12345678\n")
        results = stage_boot_payload(boot_root, manifest, node)
        provision_path = boot_root / "easymanet" / "provision.json"
        if not provision_path.is_file():
            raise ArtifactVerificationError(
                "boot payload did not write easymanet/provision.json"
            )
        provision_mode = stat.S_IMODE(provision_path.stat().st_mode)
        if provision_mode != 0o600:
            raise ArtifactVerificationError(
                f"boot payload provision.json mode expected 0600, got {provision_mode:04o}"
            )
        try:
            provision = json.loads(provision_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactVerificationError(
                f"boot payload provision.json is invalid: {exc}"
            ) from exc
        node_payload = provision.get("node")
        if not isinstance(node_payload, dict) or node_payload.get("name") != node:
            raise ArtifactVerificationError(f"boot payload did not render node {node!r}")
        if "root=PARTUUID=12345678-02" not in (boot_root / "cmdline.txt").read_text():
            raise ArtifactVerificationError(
                "boot payload did not patch cmdline.txt to PARTUUID root"
            )
        if ("/boot/easymanet/provision.json", True) not in results:
            raise ArtifactVerificationError("boot payload result did not report provision.json")
    return f"staged provision.json and cmdline.txt for {node}"


def verify_image_cache_read_only() -> str:
    with tempfile.TemporaryDirectory(prefix="easymanet-cache-readonly-") as tmp:
        workspace = Path(tmp) / "workspace"
        images = workspace / "Images"
        for rel_path in ("Fleets", "Images", "Diagnostics", "Builds"):
            (workspace / rel_path).mkdir(parents=True)
        (workspace / "README.txt").write_text("EasyMANET workspace\n")

        image = images / "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
        with gzip.open(image, "wb") as handle:
            handle.write(b"firmware")
        (images / "version.json").write_text(
            json.dumps(
                {
                    TARGET: {
                        "version": "images-v0.2.8",
                        "sha256": "0" * 64,
                        "url": f"https://example.invalid/{image.name}",
                    }
                },
                indent=2,
            )
        )

        before = snapshot_tree(images)
        old_workspace = os.environ.get("EASYMANET_WORKSPACE")
        os.environ["EASYMANET_WORKSPACE"] = str(workspace)
        try:
            payload = state_payload()
        finally:
            if old_workspace is None:
                os.environ.pop("EASYMANET_WORKSPACE", None)
            else:
                os.environ["EASYMANET_WORKSPACE"] = old_workspace
        after = snapshot_tree(images)

        if before != after:
            raise ArtifactVerificationError("desktop state payload mutated the image cache")
        entry = payload.get("images", {}).get(TARGET, {})
        if not isinstance(entry, dict):
            raise ArtifactVerificationError("desktop state payload omitted target image metadata")
        if entry.get("cache_present"):
            raise ArtifactVerificationError(
                "stale checksum metadata was reported as a verified cache"
            )
        if not image.exists():
            raise ArtifactVerificationError("stale checksum check deleted the cached image")
    return "state payload left stale cache metadata and image files unchanged"


def snapshot_tree(root: Path) -> dict[str, tuple[Any, ...]]:
    snapshot: dict[str, tuple[Any, ...]] = {}
    for path in sorted(root.rglob("*")):
        rel_path = path.relative_to(root).as_posix()
        mode = stat.S_IMODE(path.stat().st_mode)
        if path.is_dir():
            snapshot[rel_path] = ("dir", mode)
        elif path.is_file():
            snapshot[rel_path] = ("file", mode, file_sha256(path))
    return snapshot


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
