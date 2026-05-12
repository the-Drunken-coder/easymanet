"""Render resolved provision.json from fleet manifest."""

import json
from typing import Any, Dict, Optional

from .manifest import Manifest
from .validate import resolve_node


def render(
    manifest: Manifest,
    node_name: str,
    *,
    ssh_enabled: Optional[bool] = None,
) -> str:
    mesh = manifest.mesh
    resolved_node = resolve_node(manifest, node_name)
    management = manifest.defaults.get("management", {})

    if ssh_enabled is None:
        ssh_enabled = resolved_node.get("role") == "gate"

    provision: Dict[str, Any] = {
        "version": 1,
        "mesh": {
            "id": mesh.get("id", ""),
            "password": mesh.get("password", ""),
            "channel": mesh.get("channel", 0),
            "bandwidth_mhz": mesh.get("bandwidth_mhz", 0),
            "country": mesh.get("country", ""),
        },
        "node": resolved_node,
        "management": {
            "root_password_hash": management.get("root_password_hash", ""),
            "ssh_authorized_keys": management.get("ssh_authorized_keys", []),
            "ssh_enabled": bool(ssh_enabled),
        },
    }

    return json.dumps(provision, indent=2)


def render_dict(
    manifest: Manifest,
    node_name: str,
    *,
    ssh_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    return json.loads(render(manifest, node_name, ssh_enabled=ssh_enabled))
