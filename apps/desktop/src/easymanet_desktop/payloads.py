"""Shared desktop payload builders for HTTP and JSON bridge surfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from easymanet.disks import list_disks
from easymanet.download import (
    cache_dir,
    get_cached_image,
    images_manifest_path,
)
from easymanet.manifest import ManifestError, load_manifest
from easymanet.platform import check_platform
from easymanet.validate import validate
from easymanet.workspace import FLEET_SUFFIXES, resolve_fleet_config, workspace_payload


def state_payload() -> dict[str, Any]:
    workspace = workspace_payload()
    images = configured_images()
    for target, entry in images.items():
        cached = get_cached_image(target)
        entry["cached_path"] = str(cached) if cached else ""
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
    }


def node_roles(manifest: Any) -> dict[str, str]:
    default_role = str(manifest.defaults.get("role", "point"))
    roles = {}
    for name in manifest.node_names():
        node = manifest.get_node(name)
        role = node.get("role", default_role) if isinstance(node, dict) else default_role
        roles[name] = str(role)
    return roles


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
