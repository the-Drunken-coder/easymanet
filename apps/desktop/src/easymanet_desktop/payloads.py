"""Shared desktop payload builders for HTTP and JSON bridge surfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from easymanet.disks import list_disks
from easymanet.download import (
    cache_dir,
    check_latest_version,
    download_image,
    get_cached_image,
    image_sha256,
    images_manifest_path,
    normalize_sha256,
    version_file_path,
)
from easymanet.manifest import ManifestError, load_manifest
from easymanet.platform import check_platform
from easymanet.provision import resolve_node_model
from easymanet.validate import validate
from easymanet.workspace import FLEET_SUFFIXES, resolve_fleet_config, workspace_payload

MANAGEMENT_LAN_IP = "10.41.254.1"
DISPLAY_CACHE_HASH_LIMIT_BYTES = 64 * 1024 * 1024


def state_payload() -> dict[str, Any]:
    workspace = workspace_payload()
    images = configured_images()
    versions = cached_versions()
    for target, entry in images.items():
        verified_cached = get_cached_image(target)
        display_cached = verified_cached
        cached_version = versions.get(target, {})
        known_sha256 = cached_version.get("sha256") or entry.get("sha256")
        if not display_cached:
            display_cached = display_cached_image(target, entry)
            known_sha256 = entry.get("sha256") if isinstance(entry.get("sha256"), str) else ""
        entry["cached_path"] = str(display_cached) if display_cached else ""
        entry["cache_present"] = bool(verified_cached)
        if cached_version.get("version") and not entry.get("version"):
            entry["version"] = cached_version["version"]
        for key in (
            "trust_status",
            "source",
            "channel",
            "release_tag",
            "image_status",
            "manifest_url",
        ):
            if cached_version.get(key) and not entry.get(key):
                entry[key] = cached_version[key]
        if cached_version.get("warnings") and not entry.get("warnings"):
            entry["warnings"] = cached_version["warnings"]
        if display_cached:
            add_cached_image_details(
                entry,
                display_cached,
                known_sha256=known_sha256,
            )
    return {
        "ok": True,
        "workspace": workspace,
        "image_cache_dir": str(cache_dir()),
        "image_manifest": str(images_manifest_path()),
        "images": images,
    }


def image_update_payload(*, check_latest: bool = False) -> dict[str, Any]:
    """Return latest-image metadata without downloading firmware."""
    state = state_payload()
    images = state.get("images", {})
    if not isinstance(images, dict):
        images = {}
    updates = {
        str(target): image_update_entry(
            str(target),
            entry if isinstance(entry, dict) else {},
            check_latest=check_latest,
        )
        for target, entry in images.items()
    }
    return {"ok": True, "updates": updates}


def image_update_entry(
    target: str,
    entry: dict[str, Any],
    *,
    check_latest: bool = False,
) -> dict[str, Any]:
    current_version = str(entry.get("version") or "")
    current_sha256 = str(entry.get("cached_sha256") or entry.get("sha256") or "")
    cached_path = str(entry.get("cached_path") or "")
    cache_present = _cache_present(entry, cached_path)
    if not check_latest:
        return {
            "target": target,
            "status": "cached" if cache_present else "missing",
            "update_available": False,
            "current_version": current_version,
            "current_sha256": current_sha256,
            "cached_path": cached_path,
            "cache_present": cache_present,
        }
    try:
        latest = check_latest_version(target)
    except Exception as exc:  # noqa: BLE001 - surfaced as image-status data.
        return {
            "target": target,
            "status": "unavailable",
            "update_available": False,
            "current_version": current_version,
            "current_sha256": current_sha256,
            "cached_path": cached_path,
            "cache_present": cache_present,
            "errors": [str(exc)],
        }
    if latest is None:
        return {
            "target": target,
            "status": "unavailable",
            "update_available": False,
            "current_version": current_version,
            "current_sha256": current_sha256,
            "cached_path": cached_path,
            "cache_present": cache_present,
            "errors": ["Could not check the latest image release."],
        }

    latest_sha256 = str(latest.sha256 or "")
    latest_version = str(latest.version or "")
    sha_mismatch = bool(current_sha256 and latest_sha256 and current_sha256 != latest_sha256)
    version_mismatch = bool(current_version and latest_version and current_version != latest_version)
    missing_verified_metadata = bool(
        cache_present
        and not current_sha256
        and not current_version
        and (latest_sha256 or latest_version)
    )
    update_available = sha_mismatch or (
        version_mismatch and (not current_sha256 or not latest_sha256)
    ) or missing_verified_metadata
    status = "current"
    if not cache_present:
        status = "missing"
    elif update_available:
        status = "outdated"

    return {
        "target": target,
        "status": status,
        "update_available": update_available,
        "current_version": current_version,
        "current_sha256": current_sha256,
        "cached_path": cached_path,
        "cache_present": cache_present,
        "latest_version": latest_version,
        "latest_url": str(latest.url or ""),
        "latest_sha256": latest_sha256,
        "latest_trust_status": str(getattr(latest, "trust_status", "")),
        "latest_source": str(getattr(latest, "source", "")),
        "latest_channel": str(getattr(latest, "channel", "")),
        "latest_release_tag": str(getattr(latest, "release_tag", "")),
        "latest_image_status": str(getattr(latest, "image_status", "")),
        "latest_manifest_url": str(getattr(latest, "manifest_url", "")),
        "warnings": [str(warning) for warning in getattr(latest, "warnings", ())],
    }


def install_image_update_payload(*, target: str) -> dict[str, Any]:
    """Download and verify the latest image for a target on explicit request."""
    target = str(target or "").strip()
    if not target:
        return {"ok": False, "errors": ["Image target is required."]}

    state = state_payload()
    images = state.get("images", {})
    if not isinstance(images, dict) or target not in images:
        return {"ok": False, "errors": [f"Unknown image target: {target}"]}
    entry = images[target] if isinstance(images[target], dict) else {}
    update = image_update_entry(target, entry, check_latest=True)
    if (
        update.get("status") == "current"
        and not update.get("update_available")
        and update.get("cache_present")
    ):
        return {
            "ok": True,
            "installed": False,
            "target": target,
            "message": "Image cache is already current.",
            "image": entry,
            "update": update,
        }

    try:
        latest = check_latest_version(target)
        if latest is None:
            return {"ok": False, "errors": ["Could not check the latest image release."]}
        if not latest.sha256:
            return {"ok": False, "errors": [f"No SHA-256 checksum found for target '{target}'."]}
        path = download_image(
            target,
            latest.version,
            latest.url,
            latest.sha256,
            force=True,
            trust=latest.trust,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the local UI.
        return {"ok": False, "errors": [str(exc)]}

    refreshed = state_payload()
    refreshed_images = refreshed.get("images", {})
    image = refreshed_images.get(target, {}) if isinstance(refreshed_images, dict) else {}
    if not isinstance(image, dict):
        image = {}
    return {
        "ok": True,
        "installed": True,
        "target": target,
        "path": str(path),
        "version": str(latest.version or ""),
        "sha256": str(latest.sha256 or ""),
        "image": image,
        "update": image_update_entry(target, image, check_latest=True),
    }


def _cache_present(entry: dict[str, Any], cached_path: str) -> bool:
    if "cache_present" in entry:
        return bool(entry.get("cache_present"))
    return bool(cached_path)


def configured_images() -> dict[str, dict[str, Any]]:
    manifest = images_manifest_path()
    if not manifest.exists():
        return {"rpi4-mm6108-spi": {}}
    try:
        data = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError):
        return {"rpi4-mm6108-spi": {}}
    if not isinstance(data, dict):
        return {"rpi4-mm6108-spi": {}}
    return {
        str(target): entry if isinstance(entry, dict) else {}
        for target, entry in data.items()
    } or {"rpi4-mm6108-spi": {}}


def cached_versions() -> dict[str, dict[str, Any]]:
    path = version_file_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    versions: dict[str, dict[str, Any]] = {}
    for target, entry in data.items():
        if isinstance(entry, str):
            versions[str(target)] = {"version": entry}
        elif isinstance(entry, dict):
            versions[str(target)] = {
                str(key): str(value)
                for key, value in entry.items()
                if isinstance(value, str)
            }
            warnings = entry.get("warnings")
            if isinstance(warnings, list):
                versions[str(target)]["warnings"] = [
                    str(item) for item in warnings if isinstance(item, str)
                ]
    return versions


def display_cached_image(target: str, entry: dict[str, Any]) -> Path | None:
    manifest_sha = entry.get("sha256")
    if isinstance(manifest_sha, str):
        try:
            normalize_sha256(manifest_sha)
            return None
        except ValueError:
            pass
    candidates = sorted(
        cache_dir().glob(f"*{target}*"),
        key=_path_mtime,
        reverse=True,
    )
    for path in candidates:
        if _display_cache_candidate(path):
            return path
    return None


def add_cached_image_details(
    entry: dict[str, Any],
    cached: Path,
    *,
    known_sha256: str = "",
) -> None:
    try:
        size = cached.stat().st_size
    except OSError:
        size = 0
    entry["cached_size_bytes"] = size
    if known_sha256:
        try:
            entry["cached_sha256"] = normalize_sha256(known_sha256)
            return
        except (AttributeError, TypeError, ValueError):
            pass
    if size > DISPLAY_CACHE_HASH_LIMIT_BYTES:
        entry["cached_sha256"] = ""
        return
    try:
        entry["cached_sha256"] = image_sha256(cached)
    except OSError:
        entry["cached_sha256"] = ""


def _display_cache_candidate(path: Path) -> bool:
    try:
        return (
            path.is_file()
            and path.stat().st_size > 0
            and path.name.endswith((".img", ".img.gz"))
        )
    except OSError:
        return False


def _path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def disks_payload(*, include_all: bool) -> dict[str, Any]:
    try:
        check_platform()
        disks = list_disks(include_all=include_all)
    except Exception as exc:  # noqa: BLE001 - surfaced to the local UI as data.
        return {"ok": False, "errors": [str(exc)], "disks": []}
    return {
        "ok": True,
        "disks": [
            {
                "device": disk.device,
                "model": disk.model,
                "size_human": disk.size_human,
                "removable": disk.removable,
                "virtual": bool(getattr(disk, "virtual", False)),
                "mounted": disk.mounted,
                "warnings": disk.warnings,
            }
            for disk in disks
        ],
    }


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    config = str(payload.get("config", "")).strip()
    node = str(payload.get("node", "")).strip() or None
    if not config:
        raise ValueError("config is required")
    config_path = resolve_fleet_config(config)
    try:
        manifest = load_manifest(str(config_path))
    except ManifestError as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": [], "nodes": []}
    result = validate(manifest, node_name=node)
    return {
        "ok": result.valid,
        "config_path": str(config_path),
        "errors": result.errors,
        "warnings": result.warnings,
        "nodes": manifest.node_names(),
        "node_roles": node_roles(manifest),
        "node_access": node_access(manifest),
    }


def node_roles(manifest: Any) -> dict[str, str]:
    default_role = str(manifest.defaults.get("role", "point"))
    roles = {}
    for name in manifest.node_names():
        node = manifest.get_node(name)
        role = node.get("role", default_role) if isinstance(node, dict) else default_role
        roles[name] = str(role)
    return roles


def node_access(manifest: Any) -> dict[str, dict[str, Any]]:
    access: dict[str, dict[str, Any]] = {}
    for name in manifest.node_names():
        try:
            resolved = resolve_node_model(manifest, name)
        except Exception:  # noqa: BLE001 - invalid fleets already surface validation errors.
            access[name] = {
                "role": "",
                "local_ap_enabled": False,
                "local_ap_ssid": "",
                "management_ip": MANAGEMENT_LAN_IP,
            }
            continue
        local_ap = resolved.local_ap
        access[name] = {
            "role": str(resolved.role),
            "local_ap_enabled": bool(local_ap.enabled),
            "local_ap_ssid": str(local_ap.ssid or ""),
            "management_ip": MANAGEMENT_LAN_IP,
        }
    return access


def resolve_config_payload(*, config: str) -> dict[str, Any]:
    config = str(config).strip()
    if not config:
        return {"ok": False, "errors": ["config is required"]}
    path = resolve_fleet_config(config)
    if not path.exists():
        return {"ok": False, "errors": ["Fleet config file does not exist"], "config_path": str(path)}
    if not path.is_file():
        return {"ok": False, "errors": ["Fleet config path is not a file"], "config_path": str(path)}
    if path.suffix.lower() not in FLEET_SUFFIXES:
        return {"ok": False, "errors": ["Fleet config file must be .yml or .yaml"], "config_path": str(path)}
    return {"ok": True, "config_path": str(Path(path).resolve())}
