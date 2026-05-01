"""Config validation.

Validates fleet.yml configuration against all required rules.
Returns a list of errors and warnings.
"""

import ipaddress
import re
from typing import List, Optional, Tuple

from .manifest import Manifest

VALID_ROLES = {"gate", "point"}
VALID_TARGETS = {"rpi4-mm6108-spi"}
VALID_BANDWIDTHS = {1, 2, 4, 8}

SSH_KEY_PATTERN = re.compile(
    r"^(ssh-(?:ed25519|rsa|ecdsa|dss)\s+[A-Za-z0-9+/]+={0,2}(\s+\S+)?)$"
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
        ipaddress.ip_address(ip_str)
        return None
    except ValueError:
        return f"Invalid IP address: {ip_str}"


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
    else:
        if not mesh.get("id"):
            result.add_error("mesh.id is required")
        if not mesh.get("password"):
            result.add_error("mesh.password is required")
        if not mesh.get("channel"):
            result.add_error("mesh.channel is required")
        if not mesh.get("bandwidth_mhz"):
            result.add_error("mesh.bandwidth_mhz is required")
        elif mesh["bandwidth_mhz"] not in VALID_BANDWIDTHS:
            result.add_error(
                f"mesh.bandwidth_mhz must be one of {sorted(VALID_BANDWIDTHS)}, "
                f"got {mesh['bandwidth_mhz']}"
            )
        if not mesh.get("country"):
            result.add_error("mesh.country is required")

    nodes = manifest.nodes
    if not nodes:
        result.add_error("nodes section is required (at least one node must be defined)")
        return result

    hostnames_seen: dict = {}
    ips_seen: dict = {}
    node_names_lower = set()

    for name in nodes:
        if name.lower() in node_names_lower:
            result.add_error(f"Duplicate node name (case-insensitive): {name}")
        node_names_lower.add(name.lower())

        node = nodes[name]

        role = node.get("role", manifest.defaults.get("role"))
        if role not in VALID_ROLES:
            result.add_error(f"Node '{name}': role must be one of {sorted(VALID_ROLES)}, got '{role}'")

        target = node.get("target", manifest.defaults.get("target"))
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

        local_ap = node.get("local_ap", {})
        if isinstance(local_ap, dict) and local_ap.get("enabled", True):
            ap_password = local_ap.get("password",
                                         manifest.defaults.get("local_ap", {}).get("password", ""))
            if ap_password and len(ap_password) < 8:
                result.add_error(
                    f"Node '{name}': local_ap.password must be at least 8 characters"
                )

        gateway = node.get("gateway", {})
        if isinstance(gateway, dict) and gateway.get("enabled"):
            uplink = gateway.get("uplink_interface")
            if role == "gate" and not uplink:
                result.add_warning(
                    f"Node '{name}': gate role without gateway.uplink_interface set"
                )

    management = manifest.defaults.get("management", {})
    ssh_keys = management.get("ssh_authorized_keys", [])
    if not ssh_keys:
        result.add_warning("No SSH authorized keys provided in defaults.management.ssh_authorized_keys")
    else:
        for key in ssh_keys:
            err = validate_ssh_key(key)
            if err:
                result.add_error(f"Invalid SSH key: {err}")

    root_pw_hash = management.get("root_password_hash", "")
    if not root_pw_hash:
        result.add_warning("root_password_hash is empty — root password will not be set")

    if node_name is not None:
        if node_name not in nodes:
            result.add_error(f"Selected node '{node_name}' does not exist in manifest")
        else:
            node = nodes[node_name]
            resolved = resolve_node(manifest, node_name)
            if isinstance(resolved.get("local_ap"), dict) and resolved["local_ap"].get("enabled"):
                pw = resolved["local_ap"].get("password", "")
                if pw and len(pw) < 8:
                    result.add_error(
                        f"Node '{node_name}': resolved local_ap.password must be at least 8 characters"
                    )

    return result


def resolve_node(manifest: Manifest, node_name: str) -> dict:
    defaults = manifest.defaults
    node = manifest.get_node(node_name)
    mesh = manifest.mesh

    resolved: dict = {
        "name": node_name,
        "hostname": node.get("hostname", node_name),
        "role": node.get("role", defaults.get("role", "point")),
        "target": node.get("target", defaults.get("target", "rpi4-mm6108-spi")),
        "ip": node.get("ip", ""),
    }

    default_local_ap = defaults.get("local_ap", {})
    node_local_ap = node.get("local_ap", {})
    resolved_local_ap = {**default_local_ap, **node_local_ap}
    if "enabled" not in resolved_local_ap:
        resolved_local_ap["enabled"] = False
    if resolved_local_ap.get("ssid") is None:
        resolved_local_ap["ssid"] = f"{node_name}-local"
    resolved["local_ap"] = resolved_local_ap

    default_gateway = defaults.get("gateway", {})
    node_gateway = node.get("gateway", {})
    resolved_gateway = {**default_gateway, **node_gateway}
    if resolved["role"] == "gate":
        resolved_gateway.setdefault("enabled", True)
    else:
        resolved_gateway.setdefault("enabled", False)
    resolved["gateway"] = resolved_gateway

    if resolved_local_ap.get("enabled") and not resolved_local_ap.get("password"):
        default_ap_pw = default_local_ap.get("password", "")
        if default_ap_pw:
            resolved_local_ap["password"] = default_ap_pw

    return resolved
