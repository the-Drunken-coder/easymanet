"""Local HTTP discovery for the desktop Mesh tab."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
import ipaddress
import json
import re
import subprocess
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from easymanet.manifest import ManifestError, load_manifest
from easymanet.provision import resolve_node_model
from easymanet.workspace import resolve_fleet_config

API_PORT = 10411
MAX_CANDIDATES = 384
MAX_WORKERS = 32
HTTP_TIMEOUT_SECONDS = 2
TOPOLOGY_TIMEOUT_SECONDS = 12
MAX_RESPONSE_BYTES = 1_000_000
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
    role: str = ""
    expected_ip: str = ""
    expected_hostname: str = ""
    sources: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, str]:
        sources = sorted(self.sources or {self.source})
        return {
            "host": self.host,
            "source": ", ".join(sources),
            "node": self.node,
            "role": self.role,
            "expected_ip": self.expected_ip,
            "expected_hostname": self.expected_hostname,
        }


Probe = Callable[[MeshCandidate], dict[str, Any]]
TopologyFetcher = Callable[[dict[str, Any]], dict[str, Any]]
NeighborFetcher = Callable[[dict[str, Any]], dict[str, Any]]

GATEWAY_UNREACHABLE_ERROR = (
    "Gateway unreachable: no EasyMANET gateway topology API answered. "
    "Check gateway power, network, or API health, then rescan."
)
DEGRADED_MESH_WARNING = "Gateway unreachable; showing partial mesh view from reachable node APIs."


def mesh_discover_payload(
    payload: dict[str, Any] | None = None,
    *,
    probe: Probe | None = None,
    topology_fetcher: TopologyFetcher | None = None,
    neighbor_fetcher: NeighborFetcher | None = None,
) -> dict[str, Any]:
    request = payload or {}
    config = str(request.get("config", "") or "").strip()
    scan_subnet = _request_bool(request.get("scan_subnet", request.get("scanSubnet")))

    candidates, warnings = mesh_candidates(config=config, scan_subnet=scan_subnet)
    probe_fn = probe or probe_mesh_candidate
    results = _probe_candidates(candidates, probe=probe_fn)
    gateways = _dedupe_gateways([result for result in results if _is_connected_gateway(result)])

    if not gateways:
        fallback_warnings = list(warnings)
        fallback_candidates = _fallback_point_candidates(config, fallback_warnings, candidates)
        fallback_results = results
        if fallback_candidates:
            fallback_results = [*results, *_probe_candidates(fallback_candidates, probe=probe_fn)]
        fetch_neighbors = neighbor_fetcher or fetch_node_neighbors
        return _degraded_mesh_payload(
            config=config,
            scan_subnet=scan_subnet,
            candidates_checked=len(candidates) + len(fallback_candidates),
            results=fallback_results,
            warnings=fallback_warnings,
            neighbor_fetcher=fetch_neighbors,
        )

    fetcher = topology_fetcher or fetch_gateway_topology
    last_gateway = gateways[0]
    last_topology: dict[str, Any] = {"ok": False, "errors": ["Gateway topology request failed"]}
    for gateway in gateways:
        topology = fetcher(gateway)
        merged_warnings = [*warnings, *(topology.get("warnings") or [])]
        if topology.get("ok"):
            nodes = topology.get("nodes") or []
            links = topology.get("links") or []
            return {
                "ok": True,
                "config": config,
                "scan_subnet": scan_subnet,
                "candidates_checked": len(candidates),
                "gateway": gateway,
                "nodes": nodes,
                "links": links,
                "radios": nodes,
                "seen": gateways,
                "warnings": merged_warnings,
                "generated_at": topology.get("generated_at") or _now_iso(),
            }
        last_gateway = gateway
        last_topology = topology

    return {
        "ok": False,
        "code": last_topology.get("code") or "topology_failed",
        "config": config,
        "scan_subnet": scan_subnet,
        "candidates_checked": len(candidates),
        "gateway": last_gateway,
        "nodes": last_topology.get("nodes") or [],
        "links": last_topology.get("links") or [],
        "radios": last_topology.get("nodes") or [],
        "seen": gateways,
        "warnings": [*warnings, *(last_topology.get("warnings") or [])],
        "errors": last_topology.get("errors") or ["Gateway topology request failed"],
        "generated_at": last_topology.get("generated_at") or _now_iso(),
    }


def _request_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return value is True or value == 1


def mesh_candidates(*, config: str = "", scan_subnet: bool = False) -> tuple[list[MeshCandidate], list[str]]:
    warnings: list[str] = []
    records: dict[str, MeshCandidate] = {}

    def add(
        host: str,
        source: str,
        *,
        node: str = "",
        role: str = "",
        expected_ip: str = "",
        expected_hostname: str = "",
    ) -> None:
        host = str(host or "").strip()
        if not host:
            return
        key = host.lower()
        existing = records.get(key)
        if existing:
            existing.sources.add(source)
            existing.node = existing.node or node
            existing.role = existing.role or role
            existing.expected_ip = existing.expected_ip or expected_ip
            existing.expected_hostname = existing.expected_hostname or expected_hostname
            return
        records[key] = MeshCandidate(
            host=host,
            source=source,
            node=node,
            role=role,
            expected_ip=expected_ip,
            expected_hostname=expected_hostname,
            sources={source},
        )

    if config:
        for candidate in _fleet_candidates(config, warnings, roles={"gate"}, label="Fleet gateway"):
            add(
                candidate.host,
                candidate.source,
                node=candidate.node,
                role=candidate.role,
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


def probe_mesh_candidate(candidate: MeshCandidate) -> dict[str, Any]:
    base = candidate.to_dict()
    try:
        identity = _fetch_api_json(candidate.host, "identity", timeout=HTTP_TIMEOUT_SECONDS)
    except TopologyApiError as exc:
        return {
            **base,
            "ok": False,
            "status": exc.status,
            "address": candidate.host,
            "error": str(exc),
        }

    node = identity.get("node") if isinstance(identity.get("node"), dict) else {}
    interfaces = identity.get("interfaces") if isinstance(identity.get("interfaces"), dict) else {}
    result = {
        **base,
        "address": candidate.host,
        "api_port": API_PORT,
        "hostname": str(node.get("hostname") or ""),
        "role": str(node.get("role") or base.get("role") or ""),
        "node": str(node.get("name") or base.get("node") or ""),
        "node_ip": str(node.get("ip") or ""),
        "target": str(node.get("target") or ""),
        "mesh_mac": str(interfaces.get("mesh_mac") or ""),
        "bat0_mac": str(interfaces.get("bat0_mac") or ""),
    }
    if not _looks_like_easymanet_api(identity):
        result["ok"] = False
        result["status"] = "not_easymanet_api"
        return result
    result["ok"] = True
    result["status"] = "connected"
    result["summary"] = _node_summary(result)
    return result


def fetch_gateway_topology(gateway: dict[str, Any]) -> dict[str, Any]:
    host = str(gateway.get("host") or gateway.get("address") or "").strip()
    if not host:
        return {"ok": False, "code": "gateway_host_missing", "errors": ["Gateway host is missing"]}
    try:
        topology = _fetch_api_json(host, "topology", timeout=TOPOLOGY_TIMEOUT_SECONDS)
    except TopologyApiError as exc:
        return {"ok": False, "code": exc.status, "errors": [str(exc)]}
    if not isinstance(topology, dict):
        return {"ok": False, "code": "invalid_topology", "errors": ["Gateway returned invalid topology JSON"]}
    return topology


def fetch_node_neighbors(node: dict[str, Any]) -> dict[str, Any]:
    host = str(node.get("host") or node.get("address") or "").strip()
    if not host:
        return {"ok": False, "code": "node_host_missing", "errors": ["Node host is missing"]}
    try:
        neighbors = _fetch_api_json(host, "neighbors", timeout=HTTP_TIMEOUT_SECONDS)
    except TopologyApiError as exc:
        return {"ok": False, "code": exc.status, "errors": [str(exc)]}
    return neighbors


class TopologyApiError(Exception):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


def _fetch_api_json(host: str, endpoint: str, *, timeout: int) -> dict[str, Any]:
    url = f"http://{host}:{API_PORT}/v1/{endpoint}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "EasyMANETDesktop/0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - local operator LAN/mesh API.
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise TopologyApiError("http_error", f"{url} returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise TopologyApiError("api_unreachable", f"{url} did not answer: {exc.reason}") from exc
    except TimeoutError as exc:
        raise TopologyApiError("api_timeout", f"{url} timed out") from exc
    except OSError as exc:
        raise TopologyApiError("api_failed", f"{url} failed: {exc}") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise TopologyApiError("response_too_large", f"{url} returned too much data")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TopologyApiError("invalid_json", f"{url} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise TopologyApiError("invalid_json", f"{url} returned a non-object JSON payload")
    return payload


def _probe_candidates(candidates: list[MeshCandidate], *, probe: Probe) -> list[dict[str, Any]]:
    if not candidates:
        return []
    workers = min(MAX_WORKERS, max(1, len(candidates)))
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(probe, candidate): candidate for candidate in candidates}
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - discovery should keep going.
                results.append({**candidate.to_dict(), "ok": False, "status": "probe_error", "error": str(exc)})
    return sorted(results, key=lambda item: (not bool(item.get("ok")), str(item.get("host", ""))))


def _fleet_candidates(
    config: str,
    warnings: list[str],
    *,
    roles: set[str] | None,
    label: str,
) -> Iterable[MeshCandidate]:
    try:
        config_path = resolve_fleet_config(config)
        manifest = load_manifest(str(config_path))
    except (ManifestError, OSError, ValueError) as exc:
        warnings.append(f"{label} candidates skipped: {exc}")
        return []

    candidates: list[MeshCandidate] = []
    for name in manifest.node_names():
        try:
            node = resolve_node_model(manifest, name)
        except ManifestError as exc:
            warnings.append(f"{label} candidate skipped for {name}: {exc}")
            continue
        role = str(node.role or "").strip()
        if roles is not None and role not in roles:
            continue
        hostname = str(node.hostname or name).strip()
        node_ip = str(node.ip or "").strip()
        if node_ip:
            candidates.append(
                MeshCandidate(
                    host=node_ip,
                    source=f"fleet {role or 'node'} ip",
                    node=name,
                    role=role,
                    expected_ip=node_ip,
                    expected_hostname=hostname,
                )
            )
        if hostname:
            if hostname.lower().endswith(".local"):
                candidates.append(
                    MeshCandidate(
                        host=hostname,
                        source=f"fleet {role or 'node'} hostname",
                        node=name,
                        role=role,
                        expected_ip=node_ip,
                        expected_hostname=hostname,
                    )
                )
            elif "." not in hostname:
                candidates.append(
                    MeshCandidate(
                        host=f"{hostname}.local",
                        source=f"fleet {role or 'node'} mDNS",
                        node=name,
                        role=role,
                        expected_ip=node_ip,
                        expected_hostname=hostname,
                    )
                )
    return candidates


def _fallback_point_candidates(
    config: str,
    warnings: list[str],
    existing_candidates: list[MeshCandidate],
) -> list[MeshCandidate]:
    if not config:
        return []

    existing_hosts = {candidate.host.lower() for candidate in existing_candidates}
    candidates: list[MeshCandidate] = []
    for candidate in _fleet_candidates(config, warnings, roles={"point"}, label="Fleet point"):
        if candidate.host.lower() in existing_hosts:
            continue
        candidates.append(candidate)
    return candidates


def _looks_like_easymanet_api(payload: dict[str, Any]) -> bool:
    node = payload.get("node")
    api = payload.get("api")
    if payload.get("ok") is True and isinstance(node, dict):
        return True
    return isinstance(api, dict) and str(api.get("version") or "")


def _is_connected_gateway(result: dict[str, Any]) -> bool:
    return bool(result.get("ok")) and str(result.get("role") or "").lower() == "gate"


def _degraded_mesh_payload(
    *,
    config: str,
    scan_subnet: bool,
    candidates_checked: int,
    results: list[dict[str, Any]],
    warnings: list[str],
    neighbor_fetcher: NeighborFetcher,
) -> dict[str, Any]:
    connected = _dedupe_nodes([result for result in results if result.get("ok")])
    if not connected:
        return {
            "ok": False,
            "code": "gateway_api_not_found",
            "config": config,
            "scan_subnet": scan_subnet,
            "candidates_checked": candidates_checked,
            "gateway": None,
            "nodes": [],
            "links": [],
            "radios": [],
            "seen": [],
            "warnings": warnings,
            "errors": [GATEWAY_UNREACHABLE_ERROR],
            "generated_at": _now_iso(),
        }

    nodes = [_degraded_node(result) for result in connected]
    mac_index = _mac_node_index(nodes)
    links: list[dict[str, str]] = []
    merged_warnings = [*warnings, DEGRADED_MESH_WARNING]

    for result, neighbors in _fetch_degraded_neighbors(connected, neighbor_fetcher=neighbor_fetcher):
        if neighbors.get("ok"):
            links.extend(_degraded_links(result, neighbors, mac_index))
            continue
        label = _result_label(result)
        merged_warnings.append(f"{label} neighbors unavailable: {_payload_error(neighbors)}")

    return {
        "ok": False,
        "code": "gateway_unreachable_partial",
        "degraded": True,
        "config": config,
        "scan_subnet": scan_subnet,
        "candidates_checked": candidates_checked,
        "gateway": None,
        "nodes": nodes,
        "links": links,
        "radios": nodes,
        "seen": connected,
        "warnings": merged_warnings,
        "errors": [],
        "generated_at": _now_iso(),
    }


def _fetch_degraded_neighbors(
    connected: list[dict[str, Any]],
    *,
    neighbor_fetcher: NeighborFetcher,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    workers = min(MAX_WORKERS, max(1, len(connected)))
    order = {id(result): index for index, result in enumerate(connected)}
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(neighbor_fetcher, result): result for result in connected}
        for future in as_completed(futures):
            result = futures[future]
            try:
                neighbors = future.result()
            except Exception as exc:  # noqa: BLE001 - degraded discovery should keep going.
                neighbors = {"ok": False, "code": "neighbors_failed", "errors": [str(exc)]}
            pairs.append((result, neighbors))

    return sorted(pairs, key=lambda pair: order[id(pair[0])])


def _degraded_node(result: dict[str, Any]) -> dict[str, str]:
    name = str(result.get("node") or result.get("hostname") or result.get("host") or "")
    return {
        "name": name,
        "hostname": str(result.get("hostname") or result.get("expected_hostname") or ""),
        "role": str(result.get("role") or ""),
        "target": str(result.get("target") or ""),
        "ip": str(result.get("node_ip") or result.get("address") or result.get("host") or ""),
        "mesh_mac": str(result.get("mesh_mac") or ""),
        "bat0_mac": str(result.get("bat0_mac") or ""),
        "status": "reachable",
    }


def _degraded_links(
    source: dict[str, Any],
    neighbors: dict[str, Any],
    mac_index: dict[str, str],
) -> list[dict[str, str]]:
    source_name = _result_label(source)
    source_mac = str(source.get("mesh_mac") or "")
    neighbor_items = neighbors.get("neighbors") if isinstance(neighbors.get("neighbors"), list) else []
    links: list[dict[str, str]] = []

    for neighbor in neighbor_items:
        if not isinstance(neighbor, dict):
            continue
        target_mac = str(neighbor.get("mac") or "").strip().lower()
        if not target_mac:
            continue
        target = mac_index.get(target_mac, "")
        links.append(
            {
                "source": source_name,
                "target": target,
                "source_mac": source_mac,
                "target_mac": target_mac,
                "iface": str(neighbor.get("iface") or ""),
                "last_seen": str(neighbor.get("last_seen") or ""),
                "throughput": str(neighbor.get("throughput") or ""),
                "status": "resolved" if target else "unresolved",
            }
        )

    return links


def _mac_node_index(nodes: list[dict[str, str]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for node in nodes:
        name = node.get("name") or node.get("hostname") or node.get("ip") or ""
        for mac_key in ("mesh_mac", "bat0_mac"):
            mac = str(node.get(mac_key) or "").strip().lower()
            if mac and name:
                index[mac] = name
    return index


def _payload_error(payload: dict[str, Any]) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        return str(errors[0])
    return str(payload.get("code") or "neighbors unavailable")


def _result_label(result: dict[str, Any]) -> str:
    return str(result.get("node") or result.get("hostname") or result.get("host") or "node")


def _node_summary(node: dict[str, Any]) -> str:
    parts = [
        str(node.get("hostname") or node.get("expected_hostname") or node.get("host") or ""),
        str(node.get("role") or ""),
        str(node.get("node_ip") or node.get("address") or ""),
    ]
    return " / ".join(part for part in parts if part)


def _dedupe_gateways(gateways: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _dedupe_nodes(gateways)


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for node in nodes:
        key = "|".join(
            [
                str(node.get("node") or node.get("hostname") or node.get("expected_hostname") or "").lower(),
                str(node.get("node_ip") or node.get("address") or node.get("host") or ""),
            ]
        )
        existing = deduped.get(key)
        if existing:
            existing["source"] = _merge_sources(existing.get("source"), node.get("source"))
            continue
        deduped[key] = dict(node)
    return list(deduped.values())


def _merge_sources(*values: Any) -> str:
    sources: set[str] = set()
    for value in values:
        sources.update(source for source in str(value or "").split(", ") if source)
    return ", ".join(sorted(sources))


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
