"""Render resolved provision.json from fleet manifest."""

from typing import Optional

from .manifest import Manifest
from .provision import ProvisionAttestation, resolve_provision


def render(
    manifest: Manifest,
    node_name: str,
    *,
    ssh_enabled: Optional[bool] = None,
    api_wan_enabled: Optional[bool] = None,
    attestation: ProvisionAttestation | None = None,
) -> str:
    return resolve_provision(
        manifest,
        node_name,
        ssh_enabled=ssh_enabled,
        api_wan_enabled=api_wan_enabled,
        attestation=attestation,
    ).to_json()


def render_dict(
    manifest: Manifest,
    node_name: str,
    *,
    ssh_enabled: Optional[bool] = None,
    api_wan_enabled: Optional[bool] = None,
    attestation: ProvisionAttestation | None = None,
) -> dict[str, object]:
    return resolve_provision(
        manifest,
        node_name,
        ssh_enabled=ssh_enabled,
        api_wan_enabled=api_wan_enabled,
        attestation=attestation,
    ).to_dict()
