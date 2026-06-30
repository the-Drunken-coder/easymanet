#!/usr/bin/env python3
"""Manual hardware-in-the-loop verification for EasyMANET nodes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    "packages/core/src",
    "packages/image/src",
    "apps/cli/src",
    "apps/desktop/src",
    "tools/publish/src",
)
for source_root in reversed(SOURCE_ROOTS):
    source_path = REPO_ROOT / source_root
    if source_path.is_dir():
        sys.path.insert(0, str(source_path))

from easymanet import __version__ as EASYMANET_VERSION  # noqa: E402
from easymanet.diagnostics import (  # noqa: E402
    HTTP_TIMEOUT_SECONDS,
    STATUS_TIMEOUT_SECONDS,
    TOPOLOGY_TIMEOUT_SECONDS,
    ApiResult,
    fetch_node_api,
)
from easymanet.flash import FlashOptions, run_flash_workflow  # noqa: E402
from easymanet.manifest import Manifest, ManifestError, load_manifest  # noqa: E402
from easymanet.provision import ResolvedNode, resolve_node_model  # noqa: E402
from easymanet.support_bundle import create_support_bundle  # noqa: E402
from easymanet.validate import validate, validate_ip  # noqa: E402
from easymanet.workspace import diagnostics_dir, ensure_workspace, resolve_fleet_config  # noqa: E402


SCHEMA_VERSION = 1
DEFAULT_WAIT_SECONDS = 120
MIN_WAIT_SECONDS = 90
MAX_WAIT_SECONDS = 120
DEFAULT_SSH_TIMEOUT_SECONDS = 8
DEFAULT_IPERF_SECONDS = 8
MAX_CAPTURE_CHARS = 4000


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]
SleepFn = Callable[[int], None]
NowFn = Callable[[], datetime]
InputFn = Callable[[str], str]


@dataclass(frozen=True)
class NodeSpec:
    name: str
    expected_role: str
    model: ResolvedNode
    host: str
    device: str
    ssh_enabled: bool
    boot_report: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Fleet config path or workspace fleet name.")
    parser.add_argument("--gate-node", required=True, help="Gate node name from the fleet config.")
    parser.add_argument("--point-node", required=True, help="Point node name from the fleet config.")
    parser.add_argument("--gate-ip", default="", help="Existing gate node IP. Defaults to the fleet IP.")
    parser.add_argument("--point-ip", default="", help="Existing point node IP. Defaults to the fleet IP.")
    parser.add_argument("--gate-device", default="", help="Explicit disk device for flashing the gate node.")
    parser.add_argument("--point-device", default="", help="Explicit disk device for flashing the point node.")
    parser.add_argument("--gate-boot-report", default="", help="Optional local gate boot report path.")
    parser.add_argument("--point-boot-report", default="", help="Optional local point boot report path.")
    parser.add_argument(
        "--gate-ssh-enabled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Whether gate SSH should be checked and requested during flashing.",
    )
    parser.add_argument(
        "--point-ssh-enabled",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Whether point SSH should be checked and requested during flashing.",
    )
    parser.add_argument("--ssh-user", default="root", help="SSH user for enabled SSH checks.")
    parser.add_argument(
        "--ssh-timeout-seconds",
        type=int,
        default=DEFAULT_SSH_TIMEOUT_SECONDS,
        help="SSH connect and command timeout.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=DEFAULT_WAIT_SECONDS,
        help="Post-flash/reuse settle wait. Release HIL runs require 90-120 seconds.",
    )
    parser.add_argument("--base-image", default="", help="Local OpenMANET image path to flash.")
    parser.add_argument("--image-sha256", default="", help="SHA-256 for a local or URL image.")
    parser.add_argument("--image-url", default="", help="Image URL to configure and download before flashing.")
    parser.add_argument("--download", action="store_true", help="Download the configured image before flashing.")
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Require a local --base-image instead of downloading.",
    )
    parser.add_argument("--force", action="store_true", help="Pass --force to the flash workflow disk safety check.")
    parser.add_argument("--no-eject", action="store_true", help="Do not eject media after flashing.")
    parser.add_argument(
        "--allow-flash",
        action="store_true",
        help="Required with --yes before this command writes any disk device.",
    )
    parser.add_argument("--yes", action="store_true", help="Required before this command writes any disk device.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config, devices, and flash plans without waiting for or probing hardware.",
    )
    parser.add_argument(
        "--skip-boot-prompt",
        action="store_true",
        help="Skip the post-flash boot prompt. Use only for lab fixtures that boot flashed media automatically.",
    )
    parser.add_argument(
        "--throughput-smoke",
        action="store_true",
        help="Run an optional iperf3 smoke test over SSH from gate to point.",
    )
    parser.add_argument(
        "--iperf-seconds",
        type=int,
        default=DEFAULT_IPERF_SECONDS,
        help="Duration for the optional iperf3 throughput smoke.",
    )
    parser.add_argument(
        "--min-throughput-bps",
        type=float,
        default=0,
        help="Optional minimum bits/sec threshold for throughput smoke.",
    )
    args = parser.parse_args(argv)
    _validate_cli_args(parser, args)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_hil(args)
    print(
        json.dumps(
            {
                "ok": payload["ok"],
                "mode": payload["mode"],
                "result_path": payload.get("result_path", ""),
                "support_bundle_path": payload.get("support_bundle_path", ""),
                "errors": payload.get("errors", []),
                "warnings": payload.get("warnings", []),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if payload["ok"] else 1


def run_hil(
    args: argparse.Namespace,
    *,
    command_runner: CommandRunner | None = None,
    sleep_fn: SleepFn = time.sleep,
    input_fn: InputFn = input,
    now_fn: NowFn | None = None,
) -> dict[str, Any]:
    now = (now_fn or _utc_now)()
    ensure_workspace()
    command_runner = command_runner or _run_command

    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    flash_results: dict[str, Any] = {}
    nodes: dict[str, Any] = {}
    topology: dict[str, Any] = {"ok": False, "skipped": True}
    throughput: dict[str, Any] = {"ok": None, "skipped": True}
    config_path = resolve_fleet_config(args.config)

    manifest = _load_manifest_for_result(config_path, checks, errors)
    gate = None
    point = None
    if manifest is not None:
        gate = _node_spec(
            manifest,
            args.gate_node,
            "gate",
            args.gate_ip,
            args.gate_device,
            args.gate_ssh_enabled,
            args.gate_boot_report,
            checks,
            errors,
        )
        point = _node_spec(
            manifest,
            args.point_node,
            "point",
            args.point_ip,
            args.point_device,
            args.point_ssh_enabled,
            args.point_boot_report,
            checks,
            errors,
        )

    if gate is not None and point is not None:
        for spec in (gate, point):
            if spec.device:
                result = _flash_node(args, spec)
                flash_results[spec.name] = result.to_dict(include_events=True)
                _add_check(checks, f"{spec.name} flash workflow", result.ok, _flash_detail(result.to_dict()))
                if not result.ok:
                    errors.extend(result.errors)
            else:
                flash_results[spec.name] = {"ok": True, "mode": "reuse", "device": ""}
                _add_check(checks, f"{spec.name} reuse requested", True, f"probing existing node at {spec.host}")

    flash_failed = any(not result.get("ok") for result in flash_results.values())
    if args.dry_run:
        warnings.append("Dry run skipped hardware wait, node API probes, SSH checks, and throughput smoke.")
    elif not flash_failed and gate is not None and point is not None:
        ready_to_probe = True
        if _has_device(args):
            ready_to_probe = _confirm_post_flash_boot(args, gate, point, input_fn, checks, errors)
        if ready_to_probe:
            sleep_fn(args.wait_seconds)
            for spec in (gate, point):
                nodes[spec.name] = _probe_node(args, spec, command_runner, checks)
            topology = _probe_topology(gate, point, checks)
            if args.throughput_smoke:
                throughput = _run_throughput_smoke(args, gate, point, command_runner, sleep_fn, checks)

    mode = "dry-run" if args.dry_run else ("flash" if _has_device(args) else "reuse")
    ok = not errors and all(check.get("ok") is not False for check in checks)
    payload = {
        "ok": ok,
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "generated_at": _iso(now),
        "easymanet_version": EASYMANET_VERSION,
        "config_path": str(config_path),
        "gate_node": args.gate_node,
        "point_node": args.point_node,
        "wait_seconds": 0 if args.dry_run else args.wait_seconds,
        "flash": flash_results,
        "nodes": nodes,
        "topology": topology,
        "throughput": throughput,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
    }
    result_path = diagnostics_dir() / f"easymanet-hil-{_stamp(now)}.json"
    payload["result_path"] = str(result_path)
    bundle_path = _write_support_bundle(payload, args, topology)
    payload["support_bundle_path"] = bundle_path
    _write_json(result_path, payload)
    return payload


def _validate_cli_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.gate_node == args.point_node:
        parser.error("--gate-node and --point-node must be different nodes.")

    if args.download and args.no_download:
        parser.error("--download and --no-download cannot be used together.")

    devices = [device for device in (args.gate_device, args.point_device) if device]
    device_ids = {_device_identity(device) for device in devices}
    if len(device_ids) != len(devices):
        parser.error("--gate-device and --point-device must not be the same disk.")
    if devices and not args.dry_run:
        if not args.allow_flash:
            parser.error("disk flashing requires --allow-flash.")
        if not args.yes:
            parser.error("disk flashing requires --yes.")
    if not args.dry_run and not MIN_WAIT_SECONDS <= args.wait_seconds <= MAX_WAIT_SECONDS:
        parser.error("--wait-seconds must be between 90 and 120 for real HIL runs.")
    if args.throughput_smoke and not (args.gate_ssh_enabled and args.point_ssh_enabled):
        parser.error("--throughput-smoke requires --gate-ssh-enabled and --point-ssh-enabled.")
    if not args.dry_run:
        if not args.gate_ssh_enabled and not args.gate_boot_report:
            parser.error("--gate-boot-report is required when gate SSH checks are disabled.")
        if not args.point_ssh_enabled and not args.point_boot_report:
            parser.error("--point-boot-report is required when point SSH checks are disabled.")


def _load_manifest_for_result(
    config_path: Path,
    checks: list[dict[str, Any]],
    errors: list[str],
) -> Manifest | None:
    try:
        manifest = load_manifest(str(config_path))
    except ManifestError as exc:
        errors.append(str(exc))
        _add_check(checks, "fleet config loads", False, str(exc))
        return None

    validation = validate(manifest)
    detail = "ok" if validation.valid else "; ".join(validation.errors)
    _add_check(checks, "fleet config validates", validation.valid, detail)
    if not validation.valid:
        errors.extend(validation.errors)
        return None
    return manifest


def _node_spec(
    manifest: Manifest,
    name: str,
    expected_role: str,
    host_override: str,
    device: str,
    ssh_enabled: bool,
    boot_report: str,
    checks: list[dict[str, Any]],
    errors: list[str],
) -> NodeSpec | None:
    try:
        model = resolve_node_model(manifest, name)
    except ManifestError as exc:
        errors.append(str(exc))
        _add_check(checks, f"{name} exists in fleet", False, str(exc))
        return None

    role = str(model.role)
    role_ok = role == expected_role
    _add_check(checks, f"{name} role is {expected_role}", role_ok, f"fleet role={role}")
    if not role_ok:
        errors.append(f"{name} must be a {expected_role} node, got {role}.")
        return None

    host = host_override.strip() or str(model.ip or "")
    host_ok = bool(host)
    _add_check(checks, f"{name} probe address resolved", host_ok, host or "missing IP")
    if not host_ok:
        errors.append(f"{name} needs a fleet IP or explicit --{expected_role}-ip.")
        return None
    host_error = validate_ip(host)
    _add_check(checks, f"{name} probe address is IPv4", host_error is None, host_error or host)
    if host_error:
        errors.append(f"{name} probe address is invalid: {host_error}")
        return None

    return NodeSpec(
        name=name,
        expected_role=expected_role,
        model=model,
        host=host,
        device=device.strip(),
        ssh_enabled=bool(ssh_enabled),
        boot_report=boot_report.strip(),
    )


def _flash_node(args: argparse.Namespace, spec: NodeSpec):
    enable_ssh, disable_ssh = _ssh_flash_overrides(spec)
    return run_flash_workflow(
        FlashOptions(
            config=args.config,
            node=spec.name,
            device=spec.device,
            base_image=args.base_image or None,
            image_sha256=args.image_sha256 or None,
            image_url=args.image_url or None,
            download=args.download,
            no_download=args.no_download,
            yes=args.yes,
            dry_run=args.dry_run,
            force=args.force,
            no_eject=args.no_eject,
            enable_ssh=enable_ssh,
            disable_ssh=disable_ssh,
        )
    )


def _probe_node(
    args: argparse.Namespace,
    spec: NodeSpec,
    command_runner: CommandRunner,
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    identity = fetch_node_api(spec.host, "identity", timeout=HTTP_TIMEOUT_SECONDS)
    status = fetch_node_api(spec.host, "status", timeout=STATUS_TIMEOUT_SECONDS)
    neighbors = fetch_node_api(spec.host, "neighbors", timeout=HTTP_TIMEOUT_SECONDS)

    _add_check(checks, f"{spec.name} /v1/identity", identity.ok, _api_detail(identity))
    _check_identity(spec, identity, checks)
    _add_check(checks, f"{spec.name} /v1/status", status.ok, _api_detail(status))
    _check_status(spec, status, checks)
    _add_check(checks, f"{spec.name} /v1/neighbors", neighbors.ok, _api_detail(neighbors))
    _check_mesh_neighbors(spec, status, neighbors, checks)

    ssh = {"ok": None, "skipped": True}
    if spec.ssh_enabled:
        ssh = _ssh_command(args, spec.host, "true", command_runner)
        _add_check(checks, f"{spec.name} SSH", bool(ssh["ok"]), _command_detail(ssh))

    boot_report = _boot_report_status(args, spec, command_runner)
    _add_check(
        checks,
        f"{spec.name} boot report available",
        bool(boot_report["ok"]),
        str(boot_report.get("detail", "")),
    )

    return {
        "name": spec.name,
        "expected_role": spec.expected_role,
        "host": spec.host,
        "ssh_enabled": spec.ssh_enabled,
        "identity": identity.to_dict(),
        "status": status.to_dict(),
        "neighbors": neighbors.to_dict(),
        "ssh": ssh,
        "boot_report": boot_report,
    }


def _probe_topology(gate: NodeSpec, point: NodeSpec, checks: list[dict[str, Any]]) -> dict[str, Any]:
    result = fetch_node_api(gate.host, "topology", timeout=TOPOLOGY_TIMEOUT_SECONDS)
    payload = result.payload
    _add_check(checks, f"{gate.name} /v1/topology", result.ok and payload.get("ok") is True, _api_detail(result))

    nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    statuses = {str(node.get("name")): str(node.get("status")) for node in nodes if isinstance(node, dict)}
    for spec in (gate, point):
        online = statuses.get(spec.name) == "online"
        _add_check(checks, f"topology sees {spec.name}", online, f"status={statuses.get(spec.name, 'missing')}")

    links = payload.get("links") if isinstance(payload.get("links"), list) else []
    linked = _has_resolved_link(links, gate.name, point.name)
    _add_check(checks, "topology resolves gate-point mesh link", linked, "resolved link present" if linked else "missing")
    return result.to_dict()


def _run_throughput_smoke(
    args: argparse.Namespace,
    gate: NodeSpec,
    point: NodeSpec,
    command_runner: CommandRunner,
    sleep_fn: SleepFn,
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    server = _ssh_command(
        args,
        point.host,
        "command -v iperf3 >/dev/null && nohup iperf3 -s -1 >/tmp/easymanet-hil-iperf3.log 2>&1 &",
        command_runner,
    )
    if not server["ok"]:
        _add_check(checks, "throughput smoke", False, _command_detail(server))
        return {"ok": False, "server": server, "client": {}, "bits_per_second": 0}

    sleep_fn(1)
    client_timeout = args.iperf_seconds + args.ssh_timeout_seconds + 5
    client = _ssh_command(
        args,
        gate.host,
        f"iperf3 -c {point.host} -t {args.iperf_seconds} -J",
        command_runner,
        timeout_seconds=client_timeout,
    )
    bps = _iperf_bits_per_second(str(client.get("stdout", "")))
    threshold_ok = args.min_throughput_bps <= 0 or bps >= args.min_throughput_bps
    ok = bool(client["ok"]) and threshold_ok
    detail = f"{bps:.0f} bps"
    if args.min_throughput_bps > 0:
        detail = f"{detail}; threshold={args.min_throughput_bps:.0f} bps"
    _add_check(checks, "throughput smoke", ok, detail)
    return {"ok": ok, "server": server, "client": client, "bits_per_second": bps}


def _confirm_post_flash_boot(
    args: argparse.Namespace,
    gate: NodeSpec,
    point: NodeSpec,
    input_fn: InputFn,
    checks: list[dict[str, Any]],
    errors: list[str],
) -> bool:
    if args.skip_boot_prompt:
        _add_check(checks, "post-flash boot handoff confirmed", True, "skipped by --skip-boot-prompt")
        return True

    flashed = ", ".join(f"{spec.name} ({spec.device})" for spec in (gate, point) if spec.device)
    prompt = (
        f"Flashed media is ready for {flashed}. "
        "Insert and boot flashed media, confirm all HIL nodes are powered, "
        "then press Enter to start the settle wait and probes: "
    )
    try:
        input_fn(prompt)
    except EOFError:
        message = "Post-flash boot confirmation is required before probing flashed nodes."
        errors.append(message)
        _add_check(checks, "post-flash boot handoff confirmed", False, message)
        return False

    _add_check(checks, "post-flash boot handoff confirmed", True, "operator confirmed")
    return True


def _check_identity(spec: NodeSpec, identity: ApiResult, checks: list[dict[str, Any]]) -> None:
    node = identity.payload.get("node") if isinstance(identity.payload.get("node"), dict) else {}
    if not identity.ok:
        return
    _add_check(checks, f"{spec.name} identity name", node.get("name") == spec.name, f"name={node.get('name', '')}")
    _add_check(
        checks,
        f"{spec.name} identity role",
        node.get("role") == spec.expected_role,
        f"role={node.get('role', '')}",
    )


def _check_status(spec: NodeSpec, status: ApiResult, checks: list[dict[str, Any]]) -> None:
    if not status.ok:
        return
    support_code = str(status.payload.get("support_code") or "")
    _add_check(checks, f"{spec.name} support code", support_code == "EM-OK", support_code or "missing")


def _check_mesh_neighbors(
    spec: NodeSpec,
    status: ApiResult,
    neighbors: ApiResult,
    checks: list[dict[str, Any]],
) -> None:
    status_mesh = status.payload.get("mesh") if isinstance(status.payload.get("mesh"), dict) else {}
    neighbor_count = _int_value(status_mesh.get("neighbor_count"))
    neighbor_payload = neighbors.payload.get("neighbors") if isinstance(neighbors.payload.get("neighbors"), list) else []
    visible = neighbor_count > 0 or len(neighbor_payload) > 0
    detail = f"status_count={neighbor_count}; api_neighbors={len(neighbor_payload)}"
    _add_check(checks, f"{spec.name} mesh neighbor visibility", visible, detail)


def _boot_report_status(
    args: argparse.Namespace,
    spec: NodeSpec,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    if spec.boot_report:
        local = _local_boot_report_status(spec.boot_report)
        if local["ok"] or not spec.ssh_enabled:
            return local

    if spec.ssh_enabled:
        command = (
            "test -s /boot/easymanet/boot-report-latest/status.json "
            "|| test -s /boot/firmware/easymanet/boot-report-latest/status.json"
        )
        remote = _ssh_command(args, spec.host, command, command_runner)
        return {
            "ok": bool(remote["ok"]),
            "source": "ssh",
            "detail": _command_detail(remote),
            "ssh": remote,
        }

    return {
        "ok": False,
        "source": "not_checked",
        "detail": "SSH disabled and no local boot report path was provided.",
    }


def _local_boot_report_status(path_value: str) -> dict[str, Any]:
    source = Path(path_value).expanduser()
    candidates = [source]
    if source.is_dir():
        if not source.name.startswith("boot-report"):
            candidates.extend(
                [
                    source / "easymanet" / "boot-report-latest",
                    source / "boot-report-latest",
                ]
            )
    for candidate in candidates:
        if candidate.is_file() and candidate.name in {"status.json", "summary.txt"}:
            return {"ok": True, "source": "local", "path": str(candidate), "detail": "file exists"}
        if candidate.is_dir():
            status = candidate / "status.json"
            summary = candidate / "summary.txt"
            if status.is_file() or summary.is_file():
                return {"ok": True, "source": "local", "path": str(candidate), "detail": "report exists"}
    return {"ok": False, "source": "local", "path": str(source), "detail": "boot report not found"}


def _ssh_command(
    args: argparse.Namespace,
    host: str,
    remote_command: str,
    command_runner: CommandRunner,
    *,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    timeout = timeout_seconds or args.ssh_timeout_seconds
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={args.ssh_timeout_seconds}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{args.ssh_user}@{host}",
        remote_command,
    ]
    try:
        completed = command_runner(command, timeout)
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "command": _display_command(command),
            "exit_code": None,
            "stdout": _limit(exc.stdout or ""),
            "stderr": _limit(exc.stderr or ""),
            "error": "timeout",
        }
    except OSError as exc:
        return {
            "ok": False,
            "command": _display_command(command),
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": f"{exc.__class__.__name__}: {exc}",
        }
    return {
        "ok": completed.returncode == 0,
        "command": _display_command(command),
        "exit_code": completed.returncode,
        "stdout": _limit(completed.stdout),
        "stderr": _limit(completed.stderr),
        "error": "",
    }


def _run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def _write_support_bundle(payload: dict[str, Any], args: argparse.Namespace, topology: dict[str, Any]) -> str:
    boot_report = args.gate_boot_report or args.point_boot_report
    result = create_support_bundle(
        config=args.config,
        node="",
        boot_report=boot_report,
        include_mesh=not topology.get("skipped", False),
        flash_result=payload,
        mesh_payload=topology.get("payload", topology),
    )
    return str(result.path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _add_check(checks: list[dict[str, Any]], name: str, ok: bool, detail: str = "") -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def _ssh_flash_overrides(spec: NodeSpec) -> tuple[bool, bool]:
    if spec.expected_role == "gate":
        return False, not spec.ssh_enabled
    return spec.ssh_enabled, False


def _has_device(args: argparse.Namespace) -> bool:
    return bool(args.gate_device or args.point_device)


def _device_identity(device: str) -> str:
    value = device.strip()
    if value.startswith("/dev/rdisk"):
        value = value.replace("/dev/rdisk", "/dev/disk", 1)
    try:
        return str(Path(value).resolve(strict=False))
    except OSError:
        return value


def _has_resolved_link(links: Any, gate_name: str, point_name: str) -> bool:
    if not isinstance(links, list):
        return False
    expected = {gate_name, point_name}
    for link in links:
        if not isinstance(link, dict):
            continue
        if link.get("status") != "resolved":
            continue
        actual = {str(link.get("source") or ""), str(link.get("target") or "")}
        if expected == actual:
            return True
    return False


def _iperf_bits_per_second(stdout: str) -> float:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return 0
    end = payload.get("end") if isinstance(payload.get("end"), dict) else {}
    for key in ("sum_received", "sum_sent"):
        summary = end.get(key) if isinstance(end.get(key), dict) else {}
        value = summary.get("bits_per_second")
        if isinstance(value, (int, float)):
            return float(value)
    return 0


def _api_detail(result: ApiResult) -> str:
    if result.ok:
        return f"{result.host} ok"
    return f"{result.host} {result.error}"


def _flash_detail(payload: dict[str, Any]) -> str:
    if payload.get("ok"):
        plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
        return f"{payload.get('code', 'ok')} {plan.get('device', '')}".strip()
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    return "; ".join(str(error) for error in errors)


def _command_detail(payload: dict[str, Any]) -> str:
    if payload.get("ok"):
        return "ok"
    if payload.get("error"):
        return str(payload["error"])
    stderr = str(payload.get("stderr") or "").strip()
    return stderr or f"exit={payload.get('exit_code')}"


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _limit(value: Any) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
    if len(text) <= MAX_CAPTURE_CHARS:
        return text
    return text[:MAX_CAPTURE_CHARS] + "\n<truncated>\n"


def _display_command(command: list[str]) -> list[str]:
    return list(command)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    raise SystemExit(main())
