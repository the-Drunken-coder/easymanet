"""Typed resolution for EasyMANET provision payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .manifest import Manifest, ManifestError


@dataclass(frozen=True)
class MeshConfig:
    id: Any = ""
    password: Any = ""
    channel: Any = 0
    bandwidth_mhz: Any = 0
    country: Any = ""

    @classmethod
    def from_mapping(cls, mesh: dict[str, Any]) -> "MeshConfig":
        return cls(
            id=mesh.get("id", ""),
            password=mesh.get("password", ""),
            channel=mesh.get("channel", 0),
            bandwidth_mhz=mesh.get("bandwidth_mhz", 0),
            country=mesh.get("country", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "password": self.password,
            "channel": self.channel,
            "bandwidth_mhz": self.bandwidth_mhz,
            "country": self.country,
        }


@dataclass(frozen=True)
class LocalApConfig:
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def enabled(self) -> Any:
        return self.data.get("enabled", False)

    @property
    def password(self) -> Any:
        return self.data.get("password", "")

    @property
    def ssid(self) -> Any:
        return self.data.get("ssid", "")

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)


@dataclass(frozen=True)
class GatewayWifiConfig:
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def enabled(self) -> Any:
        return self.data.get("enabled", False)

    @property
    def ssid(self) -> Any:
        return self.data.get("ssid", "")

    @property
    def password(self) -> Any:
        return self.data.get("password", "")

    @property
    def encryption(self) -> Any:
        return self.data.get("encryption")

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)


@dataclass(frozen=True)
class GatewayConfig:
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def enabled(self) -> Any:
        return self.data.get("enabled", False)

    @property
    def uplink_interface(self) -> Any:
        return self.data.get("uplink_interface", "")

    @property
    def wifi(self) -> GatewayWifiConfig | None:
        wifi = self.data.get("wifi", {})
        if not isinstance(wifi, dict):
            return None
        return GatewayWifiConfig(dict(wifi))

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)


@dataclass(frozen=True)
class ManagementConfig:
    root_password_hash: Any = ""
    ssh_authorized_keys: Any = field(default_factory=list)
    ssh_enabled: Optional[bool] = None

    @classmethod
    def from_mapping(
        cls,
        management: dict[str, Any],
        *,
        ssh_enabled: Optional[bool] = None,
    ) -> "ManagementConfig":
        return cls(
            root_password_hash=management.get("root_password_hash", ""),
            ssh_authorized_keys=management.get("ssh_authorized_keys", []),
            ssh_enabled=ssh_enabled,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "root_password_hash": self.root_password_hash,
            "ssh_authorized_keys": self.ssh_authorized_keys,
        }
        if self.ssh_enabled is not None:
            payload["ssh_enabled"] = bool(self.ssh_enabled)
        return payload


@dataclass(frozen=True)
class ResolvedNode:
    name: str
    hostname: Any
    role: Any
    target: Any
    ip: Any
    local_ap: LocalApConfig
    gateway: GatewayConfig

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "hostname": self.hostname,
            "role": self.role,
            "target": self.target,
            "ip": self.ip,
            "local_ap": self.local_ap.to_dict(),
            "gateway": self.gateway.to_dict(),
        }


@dataclass(frozen=True)
class ProvisionPayload:
    version: int
    mesh: MeshConfig
    node: ResolvedNode
    management: ManagementConfig

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "mesh": self.mesh.to_dict(),
            "node": self.node.to_dict(),
            "management": self.management.to_dict(),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def resolve_node_model(manifest: Manifest, node_name: str) -> ResolvedNode:
    defaults = _require_mapping(manifest.defaults, "defaults")
    node = manifest.get_node(node_name)
    if not isinstance(node, dict):
        raise ManifestError(
            f"Manifest node '{node_name}' must be a mapping, got {type(node).__name__}"
        )

    local_ap = _resolved_local_ap(defaults, node, node_name)
    gateway = _resolved_gateway(defaults, node, role=node.get("role", defaults.get("role", "point")))
    return ResolvedNode(
        name=node_name,
        hostname=node.get("hostname", node_name),
        role=node.get("role", defaults.get("role", "point")),
        target=node.get("target", defaults.get("target", "rpi4-mm6108-spi")),
        ip=node.get("ip", ""),
        local_ap=LocalApConfig(local_ap),
        gateway=GatewayConfig(gateway),
    )


def resolve_provision(
    manifest: Manifest,
    node_name: str,
    *,
    ssh_enabled: Optional[bool] = None,
) -> ProvisionPayload:
    mesh = _require_mapping(manifest.mesh, "mesh")
    defaults = _require_mapping(manifest.defaults, "defaults")
    management = defaults.get("management", {})
    if not isinstance(management, dict):
        raise ManifestError(
            f"defaults.management must be a mapping, got {type(management).__name__}"
        )

    return ProvisionPayload(
        version=1,
        mesh=MeshConfig.from_mapping(mesh),
        node=resolve_node_model(manifest, node_name),
        management=ManagementConfig.from_mapping(management, ssh_enabled=ssh_enabled),
    )


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(
            f"Manifest section '{label}' must be a mapping, got {type(value).__name__}"
        )
    return value


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _resolved_local_ap(
    defaults: dict[str, Any],
    node: dict[str, Any],
    node_name: str,
) -> dict[str, Any]:
    resolved = {
        **_mapping_or_empty(defaults.get("local_ap", {})),
        **_mapping_or_empty(node.get("local_ap", {})),
    }
    if "enabled" not in resolved:
        resolved["enabled"] = False
    if resolved.get("ssid") is None:
        resolved["ssid"] = f"{node_name}-local"
    if resolved.get("enabled") and not resolved.get("password"):
        default_password = _mapping_or_empty(defaults.get("local_ap", {})).get("password", "")
        if default_password:
            resolved["password"] = default_password
    return resolved


def _resolved_gateway(
    defaults: dict[str, Any],
    node: dict[str, Any],
    *,
    role: Any,
) -> dict[str, Any]:
    resolved = {
        **_mapping_or_empty(defaults.get("gateway", {})),
        **_mapping_or_empty(node.get("gateway", {})),
    }
    if role == "gate":
        resolved.setdefault("enabled", True)
    else:
        resolved.setdefault("enabled", False)
    return resolved
