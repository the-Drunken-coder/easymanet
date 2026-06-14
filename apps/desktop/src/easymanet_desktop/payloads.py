"""Shared desktop payload builders for HTTP and JSON bridge surfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from easymanet.disks import list_disks
from easymanet.download import (
    cache_dir,
    get_cached_image,
    image_sha256,
    images_manifest_path,
    version_file_path,
)
from easymanet.manifest import ManifestError, load_manifest
from easymanet.platform import check_platform
from easymanet.provision import resolve_node_model
from easymanet.validate import validate
from easymanet.workspace import FLEET_SUFFIXES, resolve_fleet_config, workspace_payload

MANAGEMENT_LAN_IP = "10.41.254.1"


def state_payload() -> dict[str, Any]:
    workspace = workspace_payload()
    images = configured_images()
    versions = cached_versions()
    for target, entry in images.items():
        cached = get_cached_image(target)
        if not cached:
            cached = display_cached_image(target, entry)
        entry["cached_path"] = str(cached) if cached else ""
        cached_version = versions.get(target, {})
        if cached_version.get("version") and not entry.get("version"):
            entry["version"] = cached_version["version"]
        if cached:
            add_cached_image_details(entry, cached)
    return {
        "ok": True,
        "workspace": workspace,
        "image_cache_dir": str(cache_dir()),
        "image_manifest": str(images_manifest_path()),
        "images": images,
    }


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


def cached_versions() -> dict[str, dict[str, str]]:
    path = version_file_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    versions: dict[str, dict[str, str]] = {}
    for target, entry in data.items():
        if isinstance(entry, str):
            versions[str(target)] = {"version": entry}
        elif isinstance(entry, dict):
            versions[str(target)] = {
                str(key): str(value)
                for key, value in entry.items()
                if isinstance(value, str)
            }
    return versions


def display_cached_image(target: str, entry: dict[str, Any]) -> Path | None:
    if entry.get("sha256"):
        return None
    candidates = sorted(
        cache_dir().glob(f"*{target}*"),
        key=_path_mtime,
        reverse=True,
    )
    for path in candidates:
        if _display_cache_candidate(path):
            return path
    return None


def add_cached_image_details(entry: dict[str, Any], cached: Path) -> None:
    try:
        entry["cached_size_bytes"] = cached.stat().st_size
    except OSError:
        entry["cached_size_bytes"] = 0
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
        disks = [disk for disk in list_disks(include_all=include_all) if disk.mounted]
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
