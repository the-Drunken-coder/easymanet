"""Typed resolution for EasyMANET provision payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from .manifest import Manifest, ManifestError


@dataclass(frozen=True)
class MeshConfig:
    id: str = ""
    password: str = ""
    channel: int = 0
    bandwidth_mhz: int = 0
    country: str = ""

    @classmethod
    def from_mapping(cls, mesh: dict[str, object]) -> "MeshConfig":
        return cls(
            id=_string_value(mesh, "id", "mesh.id"),
            password=_string_value(mesh, "password", "mesh.password"),
            channel=_int_value(mesh, "channel", "mesh.channel"),
            bandwidth_mhz=_int_value(
                mesh,
                "bandwidth_mhz",
                "mesh.bandwidth_mhz",
            ),
            country=_string_value(mesh, "country", "mesh.country"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "password": self.password,
            "channel": self.channel,
            "bandwidth_mhz": self.bandwidth_mhz,
            "country": self.country,
        }


@dataclass(frozen=True)
class LocalApConfig:
    enabled: bool = False
    ssid: str | None = None
    password: str | None = None

    @classmethod
    def from_mapping(cls, local_ap: dict[str, object]) -> "LocalApConfig":
        return cls(
            enabled=_bool_value(local_ap, "enabled", "local_ap.enabled"),
            ssid=_optional_string_value(local_ap, "ssid", "local_ap.ssid"),
            password=_optional_string_value(
                local_ap,
                "password",
                "local_ap.password",
            ),
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"enabled": self.enabled}
        if self.ssid is not None:
            payload["ssid"] = self.ssid
        if self.password is not None:
            payload["password"] = self.password
        return payload


@dataclass(frozen=True)
class GatewayWifiConfig:
    enabled: bool = False
    ssid: str | None = None
    password: str | None = None
    encryption: str | None = None

    @classmethod
    def from_mapping(cls, wifi: dict[str, object]) -> "GatewayWifiConfig":
        return cls(
            enabled=_bool_value(wifi, "enabled", "gateway.wifi.enabled"),
            ssid=_optional_string_value(wifi, "ssid", "gateway.wifi.ssid"),
            password=_optional_string_value(
                wifi,
                "password",
                "gateway.wifi.password",
            ),
            encryption=_optional_string_value(
                wifi,
                "encryption",
                "gateway.wifi.encryption",
            ),
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"enabled": self.enabled}
        if self.ssid is not None:
            payload["ssid"] = self.ssid
        if self.password is not None:
            payload["password"] = self.password
        if self.encryption is not None:
            payload["encryption"] = self.encryption
        return payload


@dataclass(frozen=True)
class GatewayConfig:
    enabled: bool = False
    uplink_interface: str = "eth0"
    wifi_config: GatewayWifiConfig | None = None

    @classmethod
    def from_mapping(cls, gateway: dict[str, object]) -> "GatewayConfig":
        wifi = gateway.get("wifi")
        if wifi is not None and not isinstance(wifi, dict):
            raise ManifestError(
                f"gateway.wifi must be a mapping, got {type(wifi).__name__}"
            )
        return cls(
            enabled=_bool_value(gateway, "enabled", "gateway.enabled"),
            uplink_interface=_string_value(
                gateway,
                "uplink_interface",
                "gateway.uplink_interface",
                default="eth0",
            ),
            wifi_config=(
                GatewayWifiConfig.from_mapping(wifi)
                if isinstance(wifi, dict)
                else None
            ),
        )

    @property
    def wifi(self) -> GatewayWifiConfig | None:
        return self.wifi_config

    def to_dict(self) -> dict[str, object]:
        values: dict[str, object] = {
            "enabled": self.enabled,
            "uplink_interface": self.uplink_interface,
        }
        if self.wifi_config is not None:
            values["wifi"] = self.wifi_config.to_dict()
        return values


def eth0_mesh_side(role: str, gateway: GatewayConfig) -> bool:
    wifi = gateway.wifi
    wifi_uplink = bool(wifi and wifi.enabled)
    return not (
        role == "gate"
        and not wifi_uplink
        and gateway.uplink_interface == "eth0"
    )


def provision_json_bool(value: object) -> bool:
    """Return an already-canonical manifest boolean without coercion."""
    return value is True


@dataclass(frozen=True)
class ManagementConfig:
    root_password_hash: str = ""
    ssh_authorized_keys: tuple[str, ...] = ()
    ssh_enabled: Optional[bool] = None
    api_wan_enabled: Optional[bool] = None

    @classmethod
    def from_mapping(
        cls,
        management: dict[str, object],
        *,
        ssh_enabled: Optional[bool] = None,
        api_wan_enabled: Optional[bool] = None,
    ) -> "ManagementConfig":
        root_password_hash = _string_value(
            management,
            "root_password_hash",
            "management.root_password_hash",
        )
        ssh_authorized_keys = _string_list_value(
            management,
            "ssh_authorized_keys",
            "management.ssh_authorized_keys",
        )
        return cls(
            root_password_hash=root_password_hash,
            ssh_authorized_keys=tuple(ssh_authorized_keys),
            ssh_enabled=ssh_enabled,
            api_wan_enabled=api_wan_enabled,
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "root_password_hash": self.root_password_hash,
            "ssh_authorized_keys": list(self.ssh_authorized_keys),
        }
        if self.ssh_enabled is not None:
            payload["ssh_enabled"] = self.ssh_enabled
        if self.api_wan_enabled is not None:
            payload["api_wan_enabled"] = self.api_wan_enabled
        return payload


@dataclass(frozen=True)
class ResolvedNode:
    name: str
    hostname: str
    role: str
    target: str
    ip: str
    local_ap: LocalApConfig
    gateway: GatewayConfig

    def to_dict(self) -> dict[str, object]:
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
class FleetNode:
    name: str
    hostname: str
    role: str
    target: str
    ip: str

    @classmethod
    def from_resolved_node(cls, node: ResolvedNode) -> "FleetNode":
        return cls(
            name=node.name,
            hostname=node.hostname,
            role=node.role,
            target=node.target,
            ip=node.ip,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "hostname": self.hostname,
            "role": self.role,
            "target": self.target,
            "ip": self.ip,
        }


@dataclass(frozen=True)
class FleetConfig:
    nodes: tuple[FleetNode, ...]

    def to_dict(self) -> dict[str, object]:
        return {"nodes": [node.to_dict() for node in self.nodes]}


@dataclass(frozen=True)
class ProvisionPayload:
    version: int
    mesh: MeshConfig
    node: ResolvedNode
    management: ManagementConfig
    fleet: FleetConfig

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "mesh": self.mesh.to_dict(),
            "node": self.node.to_dict(),
            "management": self.management.to_dict(),
            "fleet": self.fleet.to_dict(),
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

    default_role = _string_value(defaults, "role", "defaults.role", default="point")
    role = _string_value(
        node,
        "role",
        f"nodes.{node_name}.role",
        default=default_role,
    )
    local_ap = LocalApConfig.from_mapping(
        _resolved_local_ap(defaults, node, node_name)
    )
    gateway = GatewayConfig.from_mapping(
        _resolved_gateway(defaults, node, role=role)
    )
    _require_distinct_local_wifi_modes(node_name, local_ap, gateway)
    return ResolvedNode(
        name=node_name,
        hostname=_string_value(
            node,
            "hostname",
            f"nodes.{node_name}.hostname",
            default=node_name,
        ),
        role=role,
        target=_string_value(
            node,
            "target",
            f"nodes.{node_name}.target",
            default=_string_value(
                defaults,
                "target",
                "defaults.target",
                default="rpi4-mm6108-spi",
            ),
        ),
        ip=_string_value(node, "ip", f"nodes.{node_name}.ip"),
        local_ap=local_ap,
        gateway=gateway,
    )


def _require_distinct_local_wifi_modes(
    node_name: str,
    local_ap: LocalApConfig,
    gateway: GatewayConfig,
) -> None:
    wifi = gateway.wifi
    if local_ap.enabled and wifi is not None and wifi.enabled:
        raise ManifestError(
            f"Node '{node_name}': local_ap.enabled and gateway.wifi.enabled "
            "cannot both be true"
        )


def resolve_provision(
    manifest: Manifest,
    node_name: str,
    *,
    ssh_enabled: Optional[bool] = None,
    api_wan_enabled: Optional[bool] = None,
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
        management=ManagementConfig.from_mapping(
            management,
            ssh_enabled=ssh_enabled,
            api_wan_enabled=api_wan_enabled,
        ),
        fleet=resolve_fleet_model(manifest),
    )


def resolve_fleet_model(manifest: Manifest) -> FleetConfig:
    return FleetConfig(
        nodes=tuple(
            FleetNode.from_resolved_node(resolve_node_model(manifest, name))
            for name in manifest.node_names()
        )
    )


def _require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ManifestError(
            f"Manifest section '{label}' must be a mapping, got {type(value).__name__}"
        )
    return value


def _mapping_value(
    mapping: dict[str, object],
    key: str,
    path: str,
) -> dict[str, object]:
    value = mapping.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ManifestError(f"{path} must be a mapping, got {type(value).__name__}")
    return dict(value)


def _string_value(
    mapping: dict[str, object],
    key: str,
    path: str,
    *,
    default: str = "",
) -> str:
    value = mapping.get(key, default)
    if not isinstance(value, str):
        raise ManifestError(f"{path} must be a string, got {type(value).__name__}")
    return value


def _optional_string_value(
    mapping: dict[str, object],
    key: str,
    path: str,
) -> str | None:
    if key not in mapping:
        return None
    return _string_value(mapping, key, path)


def _int_value(
    mapping: dict[str, object],
    key: str,
    path: str,
    *,
    default: int = 0,
) -> int:
    value = mapping.get(key, default)
    if type(value) is not int:
        raise ManifestError(f"{path} must be an int, got {type(value).__name__}")
    return value


def _bool_value(
    mapping: dict[str, object],
    key: str,
    path: str,
    *,
    default: bool = False,
) -> bool:
    value = mapping.get(key, default)
    if type(value) is not bool:
        raise ManifestError(f"{path} must be a boolean, got {type(value).__name__}")
    return value


def _string_list_value(
    mapping: dict[str, object],
    key: str,
    path: str,
) -> list[str]:
    value = mapping.get(key, [])
    if not isinstance(value, list):
        raise ManifestError(f"{path} must be a list, got {type(value).__name__}")
    if not all(isinstance(item, str) for item in value):
        raise ManifestError(f"{path} entries must be strings")
    return list(value)


def _resolved_local_ap(
    defaults: dict[str, object],
    node: dict[str, object],
    node_name: str,
) -> dict[str, object]:
    default_local_ap = _mapping_value(defaults, "local_ap", "defaults.local_ap")
    node_local_ap = _mapping_value(node, "local_ap", f"nodes.{node_name}.local_ap")
    resolved = {
        **default_local_ap,
        **node_local_ap,
    }
    enabled = _bool_value(resolved, "enabled", "local_ap.enabled")
    resolved["enabled"] = enabled
    if enabled and "ssid" not in resolved:
        resolved["ssid"] = f"{node_name}-local"
    return resolved


def _resolved_gateway(
    defaults: dict[str, object],
    node: dict[str, object],
    *,
    role: str,
) -> dict[str, object]:
    default_gateway = _mapping_value(defaults, "gateway", "defaults.gateway")
    node_gateway = _mapping_value(node, "gateway", "node.gateway")
    resolved = {
        **default_gateway,
        **node_gateway,
    }
    default_wifi = default_gateway.get("wifi")
    node_wifi = node_gateway.get("wifi")
    if isinstance(default_wifi, dict):
        if "wifi" not in node_gateway:
            resolved["wifi"] = dict(default_wifi)
        elif isinstance(node_wifi, dict):
            resolved["wifi"] = {**default_wifi, **node_wifi}
    resolved["enabled"] = role == "gate"

    wifi = resolved.get("wifi")
    if wifi is not None and not isinstance(wifi, dict):
        raise ManifestError(
            f"gateway.wifi must be a mapping, got {type(wifi).__name__}"
        )
    wifi_enabled = bool(
        isinstance(wifi, dict)
        and _bool_value(wifi, "enabled", "gateway.wifi.enabled")
    )
    if wifi_enabled:
        if not resolved.get("uplink_interface"):
            resolved["uplink_interface"] = "wifi"
    else:
        resolved.pop("wifi", None)
        if not resolved.get("uplink_interface"):
            resolved["uplink_interface"] = "eth0"
    return resolved
