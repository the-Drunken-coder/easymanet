import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from easymanet import diagnostics
from easymanet.workspace import WORKSPACE_ENV
from tools import hil_verify


def _now():
    return datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)


def _api_result(host, endpoint, payload, *, ok=True):
    return diagnostics.ApiResult(ok=ok, host=host, endpoint=endpoint, payload=payload, error="" if ok else "down")


def test_parse_args_refuses_flash_without_guardrails():
    with pytest.raises(SystemExit):
        hil_verify.parse_args(
            [
                "--config",
                "examples/three-node-field-mesh.yml",
                "--gate-node",
                "gate01",
                "--point-node",
                "point01",
                "--gate-device",
                "/dev/disk4",
            ]
        )


def test_dry_run_writes_result_and_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "EasyMANET"))
    args = hil_verify.parse_args(
        [
            "--config",
            "examples/three-node-field-mesh.yml",
            "--gate-node",
            "gate01",
            "--point-node",
            "point01",
            "--dry-run",
        ]
    )

    payload = hil_verify.run_hil(args, now_fn=_now)

    result_path = Path(payload["result_path"])
    assert payload["ok"] is True
    assert payload["mode"] == "dry-run"
    assert result_path == tmp_path / "EasyMANET" / "Diagnostics" / "easymanet-hil-20260630T120000Z.json"
    assert result_path.is_file()
    assert Path(payload["support_bundle_path"]).is_file()
    assert payload["nodes"] == {}
    assert "Dry run skipped hardware" in payload["warnings"][0]


def test_reuse_nodes_collects_mock_hardware_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "EasyMANET"))
    calls = []
    slept = []

    def fake_fetch(host, endpoint, timeout=diagnostics.HTTP_TIMEOUT_SECONDS):
        calls.append((host, endpoint, timeout))
        node_name = "gate01" if host == "10.41.1.1" else "point01"
        role = "gate" if node_name == "gate01" else "point"
        if endpoint == "identity":
            return _api_result(host, endpoint, {"ok": True, "node": {"name": node_name, "role": role, "ip": host}})
        if endpoint == "status":
            return _api_result(
                host,
                endpoint,
                {
                    "ok": True,
                    "support_code": "EM-OK",
                    "mesh": {"ok": True, "neighbor_count": 1},
                    "node": {"name": node_name, "role": role, "ip": host},
                },
            )
        if endpoint == "neighbors":
            return _api_result(host, endpoint, {"ok": True, "neighbors": [{"mac": "aa:bb:cc:dd:ee:ff"}]})
        if endpoint == "topology":
            return _api_result(
                host,
                endpoint,
                {
                    "ok": True,
                    "nodes": [
                        {"name": "gate01", "status": "online"},
                        {"name": "point01", "status": "online"},
                    ],
                    "links": [{"source": "gate01", "target": "point01", "status": "resolved"}],
                },
            )
        raise AssertionError(endpoint)

    def fake_command(command, timeout):
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(hil_verify, "fetch_node_api", fake_fetch)
    args = hil_verify.parse_args(
        [
            "--config",
            "examples/three-node-field-mesh.yml",
            "--gate-node",
            "gate01",
            "--point-node",
            "point01",
            "--point-ssh-enabled",
            "--wait-seconds",
            "90",
        ]
    )

    payload = hil_verify.run_hil(
        args,
        command_runner=fake_command,
        sleep_fn=slept.append,
        now_fn=_now,
    )

    assert payload["ok"] is True
    assert slept == [90]
    assert ("10.41.1.1", "topology", diagnostics.TOPOLOGY_TIMEOUT_SECONDS) in calls
    assert payload["nodes"]["gate01"]["ssh"]["ok"] is True
    assert payload["nodes"]["point01"]["boot_report"]["ok"] is True
    assert Path(payload["result_path"]).is_file()
    assert Path(payload["support_bundle_path"]).is_file()


def test_boot_report_requires_path_when_ssh_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "EasyMANET"))

    def fake_fetch(host, endpoint, timeout=diagnostics.HTTP_TIMEOUT_SECONDS):
        if endpoint == "identity":
            name = "gate01" if host == "10.41.1.1" else "point01"
            role = "gate" if name == "gate01" else "point"
            return _api_result(host, endpoint, {"ok": True, "node": {"name": name, "role": role, "ip": host}})
        if endpoint == "status":
            return _api_result(host, endpoint, {"ok": True, "support_code": "EM-OK", "mesh": {"neighbor_count": 1}})
        if endpoint == "neighbors":
            return _api_result(host, endpoint, {"ok": True, "neighbors": [{"mac": "aa:bb:cc:dd:ee:ff"}]})
        if endpoint == "topology":
            return _api_result(
                host,
                endpoint,
                {
                    "ok": True,
                    "nodes": [
                        {"name": "gate01", "status": "online"},
                        {"name": "point01", "status": "online"},
                    ],
                    "links": [{"source": "gate01", "target": "point01", "status": "resolved"}],
                },
            )
        raise AssertionError(endpoint)

    monkeypatch.setattr(hil_verify, "fetch_node_api", fake_fetch)
    args = hil_verify.parse_args(
        [
            "--config",
            "examples/three-node-field-mesh.yml",
            "--gate-node",
            "gate01",
            "--point-node",
            "point01",
            "--wait-seconds",
            "90",
        ]
    )

    payload = hil_verify.run_hil(
        args,
        command_runner=lambda command, timeout: subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
        sleep_fn=lambda seconds: None,
        now_fn=_now,
    )

    assert payload["ok"] is False
    assert payload["nodes"]["point01"]["boot_report"]["source"] == "not_checked"
    assert any(check["name"] == "point01 boot report available" and check["ok"] is False for check in payload["checks"])
