"""Config validation.

Validates fleet.yml configuration against all required rules.
Returns a list of errors and warnings.
"""

import ipaddress
import re
from typing import List, Optional

from .manifest import Manifest
from .provision import GatewayConfig, LocalApConfig, resolve_node_model

VALID_ROLES = {"gate", "point"}
VALID_TARGETS = {"rpi4-mm6108-spi"}
VALID_BANDWIDTHS = {1, 2, 4, 8}
VALID_WIFI_ENCRYPTION = {"psk2", "sae", "none", "psk", "psk-mixed"}
COUNTRY_PATTERN = re.compile(r"^[A-Z]{2}$")

SSH_KEY_PATTERN = re.compile(
    r"^(?:"
    r"ssh-(?:ed25519|rsa|ecdsa|dss)|"
    r"ecdsa-sha2-nistp(?:256|384|521)|"
    r"sk-(?:ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com"
    r")\s+[A-Za-z0-9+/]+={0,2}(?:\s+.+)?$"
)


class ValidationResult:
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def validate_ip(ip_str: str) -> Optional[str]:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return f"Invalid IP address: {ip_str}"
    if not isinstance(ip, ipaddress.IPv4Address):
        return f"Invalid IPv4 address: {ip_str}"
    return None


def validate_ssh_key(key: str) -> Optional[str]:
    if not SSH_KEY_PATTERN.match(key.strip()):
        return f"Invalid SSH public key format: {key[:50]}..."
    return None


def validate(manifest: Manifest, node_name: Optional[str] = None) -> ValidationResult:
    result = ValidationResult()

    if manifest.version != 1:
        result.add_error(f"version must be 1, got {manifest.version}")

    mesh = manifest.mesh
    if not mesh:
        result.add_error("mesh section is required")
    elif not isinstance(mesh, dict):
        result.add_error(f"mesh section must be a mapping, got {type(mesh).__name__}")
    else:
        if not mesh.get("id"):
            result.add_error("mesh.id is required")
        if not mesh.get("password"):
            result.add_error("mesh.password is required")
        if mesh.get("channel") is None:
            result.add_error("mesh.channel is required")
        if mesh.get("bandwidth_mhz") is None:
            result.add_error("mesh.bandwidth_mhz is required")
        elif mesh["bandwidth_mhz"] not in VALID_BANDWIDTHS:
            result.add_error(
                f"mesh.bandwidth_mhz must be one of {sorted(VALID_BANDWIDTHS)}, "
                f"got {mesh['bandwidth_mhz']}"
            )
        country = mesh.get("country", "")
        if not country:
            result.add_error("mesh.country is required")
        elif not COUNTRY_PATTERN.match(str(country)):
            result.add_error(
                f"mesh.country must be a two-letter ISO country code (e.g. US), got '{country}'"
            )

    nodes = manifest.nodes
    if not nodes:
        result.add_error("nodes section is required (at least one node must be defined)")
        return result
    if not isinstance(nodes, dict):
        result.add_error(f"nodes section must be a mapping, got {type(nodes).__name__}")
        return result

    defaults = manifest.defaults
    if not isinstance(defaults, dict):
        result.add_error(f"defaults section must be a mapping, got {type(defaults).__name__}")
        defaults = {}

    hostnames_seen: dict = {}
    ips_seen: dict = {}
    node_names_lower = set()

    default_gateway = defaults.get("gateway", {})
    if not isinstance(default_gateway, dict):
        result.add_error(
            f"defaults.gateway must be a mapping, got {type(default_gateway).__name__}"
        )
        default_gateway = {}

    default_local_ap = defaults.get("local_ap", {})
    if not isinstance(default_local_ap, dict):
        result.add_error(
            f"defaults.local_ap must be a mapping, got {type(default_local_ap).__name__}"
        )
        default_local_ap = {}

    management = defaults.get("management", {})
    if not isinstance(management, dict):
        result.add_error(
            f"defaults.management must be a mapping, got {type(management).__name__}"
        )
        management = {}

    for name in nodes:
        if not isinstance(name, str):
            result.add_error(f"Node name must be a string, got {type(name).__name__}")
            continue
        if name.lower() in node_names_lower:
            result.add_error(f"Duplicate node name (case-insensitive): {name}")
        node_names_lower.add(name.lower())

        node = nodes[name]
        if not isinstance(node, dict):
            result.add_error(f"Node '{name}' must be a mapping, got {type(node).__name__}")
            continue

        role = node.get("role", defaults.get("role", "point"))
        if role not in VALID_ROLES:
            result.add_error(f"Node '{name}': role must be one of {sorted(VALID_ROLES)}, got '{role}'")

        target = node.get("target", defaults.get("target"))
        if target not in VALID_TARGETS:
            result.add_error(
                f"Node '{name}': target must be one of {sorted(VALID_TARGETS)}, got '{target}'"
            )

        hostname = node.get("hostname", "")
        if not hostname:
            result.add_error(f"Node '{name}': hostname is required")
        elif hostname in hostnames_seen:
            result.add_error(
                f"Duplicate hostname '{hostname}' in node '{name}' "
                f"(also used by node '{hostnames_seen[hostname]}')"
            )
        else:
            hostnames_seen[hostname] = name

        ip = node.get("ip", "")
        if not ip:
            result.add_error(f"Node '{name}': ip is required")
        else:
            err = validate_ip(ip)
            if err:
                result.add_error(f"Node '{name}': {err}")
            elif ip in ips_seen:
                result.add_error(
                    f"Duplicate IP '{ip}' in node '{name}' "
                    f"(also used by node '{ips_seen[ip]}')"
                )
            else:
                ips_seen[ip] = name

        node_local_ap = node.get("local_ap", {})
        if not isinstance(node_local_ap, dict):
            result.add_error(
                f"Node '{name}': local_ap must be a mapping, got {type(node_local_ap).__name__}"
            )

        node_gateway = node.get("gateway", {})
        if not isinstance(node_gateway, dict):
            result.add_error(
                f"Node '{name}': gateway must be a mapping, got {type(node_gateway).__name__}"
            )
        if isinstance(manifest.defaults, dict):
            resolved = resolve_node_model(manifest, name)
            _validate_local_ap(result, name, resolved.local_ap)
            if resolved.gateway.enabled and role == "gate":
                uplink = resolved.gateway.uplink_interface
                if not uplink:
                    result.add_warning(
                        f"Node '{name}': gate role without gateway.uplink_interface set"
                    )
            _validate_gateway_wifi(result, name, resolved.gateway)

    ssh_keys = management.get("ssh_authorized_keys", [])
    if not ssh_keys:
        result.add_warning("No SSH authorized keys provided in defaults.management.ssh_authorized_keys")
    elif not isinstance(ssh_keys, list):
        result.add_error(
            f"defaults.management.ssh_authorized_keys must be a list, got {type(ssh_keys).__name__}"
        )
    else:
        for key in ssh_keys:
            if not isinstance(key, str):
                result.add_error(
                    f"defaults.management.ssh_authorized_keys entries must be strings, got {type(key).__name__}"
                )
                continue
            err = validate_ssh_key(key)
            if err:
                result.add_error(f"Invalid SSH key: {err}")

    root_pw_hash = management.get("root_password_hash", "")
    if not root_pw_hash:
        result.add_warning("root_password_hash is empty — root password will not be set")

    if node_name is not None:
        if node_name not in nodes:
            result.add_error(f"Selected node '{node_name}' does not exist in manifest")
        elif not isinstance(nodes[node_name], dict):
            result.add_error(
                f"Selected node '{node_name}' must be a mapping, got {type(nodes[node_name]).__name__}"
            )
        elif not isinstance(manifest.defaults, dict):
            pass

    return result


def _validate_local_ap(
    result: ValidationResult,
    node_label: str,
    local_ap: LocalApConfig,
) -> None:
    if not local_ap.enabled:
        return
    password = local_ap.password
    if not password:
        result.add_error(
            f"Node '{node_label}': local_ap.enabled requires local_ap.password"
        )
    elif not isinstance(password, str):
        result.add_error(
            f"Node '{node_label}': local_ap.password must be a string"
        )
    elif len(password) < 8:
        result.add_error(
            f"Node '{node_label}': local_ap.password must be at least 8 characters"
        )


def _validate_gateway_wifi(
    result: ValidationResult,
    node_label: str,
    gateway: GatewayConfig | dict,
) -> None:
    gateway_data = gateway.to_dict() if isinstance(gateway, GatewayConfig) else gateway
    if not isinstance(gateway_data, dict):
        return
    wifi = gateway_data.get("wifi", {})
    if not isinstance(wifi, dict) or not wifi.get("enabled"):
        return
    ssid = wifi.get("ssid", "")
    password = wifi.get("password", "")
    if not ssid:
        result.add_error(
            f"Node '{node_label}': gateway.wifi.enabled requires gateway.wifi.ssid"
        )
    if not password:
        result.add_error(
            f"Node '{node_label}': gateway.wifi.enabled requires gateway.wifi.password"
        )
    encryption = wifi.get("encryption")
    if encryption is not None and encryption not in VALID_WIFI_ENCRYPTION:
        result.add_error(
            f"Node '{node_label}': gateway.wifi.encryption must be one of "
            f"{sorted(VALID_WIFI_ENCRYPTION)}, got '{encryption}'"
        )


def resolve_node(manifest: Manifest, node_name: str) -> dict:
    return resolve_node_model(manifest, node_name).to_dict()
