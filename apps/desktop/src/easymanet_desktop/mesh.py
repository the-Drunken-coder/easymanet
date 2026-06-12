"""Local SSH discovery for the desktop Mesh tab."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import ipaddress
import re
import shlex
import shutil
import socket
import subprocess
from typing import Any, Callable, Iterable

from easymanet.manifest import ManifestError, load_manifest
from easymanet.workspace import resolve_fleet_config

DEFAULT_SSH_USER = "root"
MAX_CANDIDATES = 384
MAX_WORKERS = 32
PORT_TIMEOUT_SECONDS = 0.45
SSH_TIMEOUT_SECONDS = 5
COMMON_MANAGEMENT_HOSTS = (
    "10.41.254.1",
    "manet01.local",
    "manet02.local",
    "openmanet.local",
    "easymanet.local",
)


@dataclass
class MeshCandidate:
    host: str
    source: str
    node: str = ""
    expected_ip: str = ""
    expected_hostname: str = ""
    sources: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, str]:
        sources = sorted(self.sources or {self.source})
        return {
            "host": self.host,
            "source": ", ".join(sources),
            "node": self.node,
            "expected_ip": self.expected_ip,
            "expected_hostname": self.expected_hostname,
        }


Probe = Callable[[MeshCandidate, str], dict[str, Any]]


def mesh_discover_payload(payload: dict[str, Any] | None = None, *, probe: Probe | None = None) -> dict[str, Any]:
    request = payload or {}
    config = str(request.get("config", "") or "").strip()
    user = _safe_ssh_user(str(request.get("user", DEFAULT_SSH_USER) or DEFAULT_SSH_USER))
    scan_subnet = bool(request.get("scan_subnet") or request.get("scanSubnet"))

    candidates, warnings = mesh_candidates(config=config, scan_subnet=scan_subnet)
    probe_fn = probe or probe_mesh_candidate
    results = _probe_candidates(candidates, user=user, probe=probe_fn)
    radios = _dedupe_radios([result for result in results if result.get("ok")])

    return {
        "ok": True,
        "config": config,
        "user": user,
        "scan_subnet": scan_subnet,
        "candidates_checked": len(candidates),
        "radios": radios,
        "seen": [],
        "warnings": warnings,
    }


def mesh_candidates(*, config: str = "", scan_subnet: bool = False) -> tuple[list[MeshCandidate], list[str]]:
    warnings: list[str] = []
    records: dict[str, MeshCandidate] = {}

    def add(host: str, source: str, *, node: str = "", expected_ip: str = "", expected_hostname: str = "") -> None:
        host = str(host or "").strip()
        if not host:
            return
        key = host.lower()
        existing = records.get(key)
        if existing:
            existing.sources.add(source)
            existing.node = existing.node or node
            existing.expected_ip = existing.expected_ip or expected_ip
            existing.expected_hostname = existing.expected_hostname or expected_hostname
            return
        records[key] = MeshCandidate(
            host=host,
            source=source,
            node=node,
            expected_ip=expected_ip,
            expected_hostname=expected_hostname,
            sources={source},
        )

    if config:
        for candidate in _fleet_candidates(config, warnings):
            add(
                candidate.host,
                candidate.source,
                node=candidate.node,
                expected_ip=candidate.expected_ip,
                expected_hostname=candidate.expected_hostname,
            )

    for host in COMMON_MANAGEMENT_HOSTS:
        add(host, "known management address")

    for host in _arp_hosts():
        add(host, "arp table")

    if scan_subnet:
        for host in _local_subnet_hosts():
            add(host, "local subnet")

    return list(records.values())[:MAX_CANDIDATES], warnings


def probe_mesh_candidate(candidate: MeshCandidate, user: str) -> dict[str, Any]:
    base = candidate.to_dict()
    reachable, address = _ssh_port_open(candidate.host)
    if not reachable:
        return {
            **base,
            "ok": False,
            "status": "ssh_closed",
            "address": address,
            "error": "SSH port 22 did not answer",
        }

    ssh = shutil.which("ssh")
    if not ssh:
        return {
            **base,
            "ok": False,
            "status": "ssh_unavailable",
            "address": address,
            "error": "ssh executable not found",
        }

    completed = _run_ssh_identity(ssh=ssh, host=candidate.host, user=user)
    parsed = _parse_identity(completed.stdout)
    result = {
        **base,
        "address": address,
        "ssh_exit_code": completed.returncode,
        "stderr": completed.stderr.strip(),
        **parsed,
    }
    if completed.returncode != 0:
        result["ok"] = False
        result["status"] = _ssh_error_status(completed.stderr)
        return result
    if not _looks_like_easymanet_radio(parsed):
        result["ok"] = False
        result["status"] = "not_easymanet"
        return result
    result["ok"] = True
    result["status"] = "connected"
    result["summary"] = _radio_summary(result)
    return result


def _probe_candidates(candidates: list[MeshCandidate], *, user: str, probe: Probe) -> list[dict[str, Any]]:
    if not candidates:
        return []
    workers = min(MAX_WORKERS, max(1, len(candidates)))
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(probe, candidate, user): candidate for candidate in candidates}
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - discovery should keep going.
                results.append({**candidate.to_dict(), "ok": False, "status": "probe_error", "error": str(exc)})
    return sorted(results, key=lambda item: (not bool(item.get("ok")), str(item.get("host", ""))))


def _fleet_candidates(config: str, warnings: list[str]) -> Iterable[MeshCandidate]:
    try:
        config_path = resolve_fleet_config(config)
        manifest = load_manifest(str(config_path))
    except (ManifestError, OSError, ValueError) as exc:
        warnings.append(f"Fleet candidates skipped: {exc}")
        return []

    candidates: list[MeshCandidate] = []
    for name in manifest.node_names():
        node = manifest.get_node(name)
        hostname = str(node.get("hostname") or name).strip()
        node_ip = str(node.get("ip") or "").strip()
        if node_ip:
            candidates.append(
                MeshCandidate(
                    host=node_ip,
                    source="fleet ip",
                    node=name,
                    expected_ip=node_ip,
                    expected_hostname=hostname,
                )
            )
        if hostname:
            candidates.append(
                MeshCandidate(
                    host=hostname,
                    source="fleet hostname",
                    node=name,
                    expected_ip=node_ip,
                    expected_hostname=hostname,
                )
            )
            if "." not in hostname:
                candidates.append(
                    MeshCandidate(
                        host=f"{hostname}.local",
                        source="fleet mDNS",
                        node=name,
                        expected_ip=node_ip,
                        expected_hostname=hostname,
                    )
                )
    return candidates


def _ssh_port_open(host: str) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, 22), timeout=PORT_TIMEOUT_SECONDS) as sock:
            address = str(sock.getpeername()[0])
            return True, address
    except OSError:
        return False, ""


def _run_ssh_identity(*, ssh: str, host: str, user: str) -> subprocess.CompletedProcess[str]:
    target = f"{user}@{host}"
    command = "sh -c " + shlex.quote(_IDENTITY_SCRIPT)
    return subprocess.run(
        [
            ssh,
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={SSH_TIMEOUT_SECONDS}",
            "-o",
            "ConnectionAttempts=1",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            target,
            command,
        ],
        capture_output=True,
        text=True,
        timeout=SSH_TIMEOUT_SECONDS + 2,
        check=False,
    )


def _parse_identity(stdout: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in stdout.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[a-z_]+", key):
            parsed[key] = value.strip()
    return parsed


def _looks_like_easymanet_radio(fields: dict[str, str]) -> bool:
    if fields.get("easymanet") == "yes" or fields.get("openmanet") == "yes":
        return True
    if fields.get("provisioned") or fields.get("mesh_id"):
        return True
    node_ip = fields.get("node_ip", "")
    return node_ip.startswith("10.41.")


def _ssh_error_status(stderr: str) -> str:
    text = stderr.lower()
    if "permission denied" in text or "publickey" in text:
        return "auth_failed"
    if "host key verification failed" in text:
        return "host_key_failed"
    if "operation timed out" in text or "connection timed out" in text:
        return "timeout"
    return "ssh_failed"


def _radio_summary(radio: dict[str, Any]) -> str:
    parts = [
        str(radio.get("hostname") or radio.get("expected_hostname") or radio.get("host") or ""),
        str(radio.get("role") or ""),
        str(radio.get("node_ip") or radio.get("address") or ""),
    ]
    return " / ".join(part for part in parts if part)


def _dedupe_radios(radios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for radio in radios:
        key = "|".join(
            [
                str(radio.get("hostname") or radio.get("expected_hostname") or "").lower(),
                str(radio.get("node_ip") or radio.get("address") or radio.get("host") or ""),
            ]
        )
        existing = deduped.get(key)
        if existing:
            sources = sorted({*(str(existing.get("source") or "").split(", ")), *(str(radio.get("source") or "").split(", "))})
            existing["source"] = ", ".join(source for source in sources if source)
            continue
        deduped[key] = dict(radio)
    return list(deduped.values())


def _safe_ssh_user(value: str) -> str:
    user = value.strip() or DEFAULT_SSH_USER
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", user):
        return DEFAULT_SSH_USER
    return user


def _arp_hosts() -> list[str]:
    hosts: set[str] = set()
    for command in (["arp", "-an"], ["ip", "neigh"]):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=2, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode != 0:
            continue
        for match in re.finditer(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", result.stdout):
            ip = _usable_ipv4(match.group(0))
            if ip:
                hosts.add(ip)
    return sorted(hosts, key=_ip_sort_key)


def _local_subnet_hosts() -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()
    for network, local_ip in _local_ipv4_networks():
        for address in network.hosts():
            text = str(address)
            if text == local_ip or text in seen:
                continue
            seen.add(text)
            hosts.append(text)
            if len(hosts) >= MAX_CANDIDATES:
                return hosts
    return hosts


def _local_ipv4_networks() -> list[tuple[ipaddress.IPv4Network, str]]:
    networks: list[tuple[ipaddress.IPv4Network, str]] = []
    for address, prefix in _ip_addr_networks() + _ifconfig_networks():
        if not _usable_ipv4(address):
            continue
        try:
            network = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
        except ValueError:
            continue
        if network.prefixlen < 24:
            network = ipaddress.ip_network(f"{address}/24", strict=False)
        if network.num_addresses > 256:
            continue
        networks.append((network, address))
    return networks


def _ip_addr_networks() -> list[tuple[str, int]]:
    try:
        result = subprocess.run(["ip", "-o", "-4", "addr", "show", "scope", "global"], capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    networks: list[tuple[str, int]] = []
    for match in re.finditer(r"\binet\s+((?:\d{1,3}\.){3}\d{1,3})/(\d{1,2})", result.stdout):
        networks.append((match.group(1), int(match.group(2))))
    return networks


def _ifconfig_networks() -> list[tuple[str, int]]:
    try:
        result = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    networks: list[tuple[str, int]] = []
    for match in re.finditer(r"\binet\s+((?:\d{1,3}\.){3}\d{1,3})\s+netmask\s+([0-9a-fx.]+)", result.stdout, re.IGNORECASE):
        prefix = _netmask_prefix(match.group(2))
        if prefix is not None:
            networks.append((match.group(1), prefix))
    return networks


def _netmask_prefix(value: str) -> int | None:
    try:
        if value.lower().startswith("0x"):
            mask_int = int(value, 16)
            mask = ipaddress.IPv4Address(mask_int)
        else:
            mask = ipaddress.IPv4Address(value)
        return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
    except ValueError:
        return None


def _usable_ipv4(value: str) -> str:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return ""
    if not isinstance(ip, ipaddress.IPv4Address):
        return ""
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return ""
    return str(ip)


def _ip_sort_key(value: str) -> tuple[int, int, int, int]:
    try:
        return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]
    except ValueError:
        return (999, 999, 999, 999)


_IDENTITY_SCRIPT = r"""
hostname_value="$(cat /proc/sys/kernel/hostname 2>/dev/null || hostname 2>/dev/null || true)"
provisioned_value="$(cat /etc/easymanet/provisioned 2>/dev/null || true)"
node_ip_value="$(uci -q get network.meship.ipaddr 2>/dev/null || uci -q get network.lan.ipaddr 2>/dev/null || true)"
mesh_id_value="$(uci -q get wireless.mesh0.mesh_id 2>/dev/null || true)"
role_value=""
target_value=""
if command -v jsonfilter >/dev/null 2>&1 && [ -f /etc/easymanet/provision.json ]; then
    role_value="$(jsonfilter -i /etc/easymanet/provision.json -e '@.node.role' 2>/dev/null || true)"
    target_value="$(jsonfilter -i /etc/easymanet/provision.json -e '@.node.target' 2>/dev/null || true)"
fi
easymanet_value=""
openmanet_value=""
dropbear_value=""
[ -f /etc/easymanet/provision.json ] && easymanet_value="yes"
[ -f /etc/openmanetd/config.yml ] && openmanet_value="yes"
pgrep -x dropbear >/dev/null 2>&1 && dropbear_value="yes"
printf 'hostname=%s\n' "$hostname_value"
printf 'provisioned=%s\n' "$provisioned_value"
printf 'node_ip=%s\n' "$node_ip_value"
printf 'mesh_id=%s\n' "$mesh_id_value"
printf 'role=%s\n' "$role_value"
printf 'target=%s\n' "$target_value"
printf 'easymanet=%s\n' "$easymanet_value"
printf 'openmanet=%s\n' "$openmanet_value"
printf 'dropbear=%s\n' "$dropbear_value"
"""
