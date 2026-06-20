import json
from pathlib import Path
from zipfile import ZipFile

from easymanet import diagnostics
from easymanet.workspace import WORKSPACE_ENV, ensure_workspace


def _api_result(host, endpoint, payload, ok=True):
    return diagnostics.ApiResult(ok=ok, host=host, endpoint=endpoint, payload=payload, error="" if ok else "down")


def test_run_diagnostics_collects_status_and_summary(monkeypatch):
    def fake_fetch(host, endpoint, timeout=diagnostics.HTTP_TIMEOUT_SECONDS):
        if endpoint == "identity":
            return _api_result(host, endpoint, {"ok": True, "node": {"name": "gate01", "role": "gate", "ip": host}})
        if endpoint == "status":
            return _api_result(
                host,
                endpoint,
                {
                    "ok": True,
                    "support_code": "EM-OK",
                    "node": {"name": "gate01", "role": "gate", "ip": host},
                    "mesh": {"ok": True, "neighbor_count": 2},
                    "internet": {"ok": True},
                    "manageability": {"ok": True},
                },
            )
        if endpoint == "neighbors":
            return _api_result(host, endpoint, {"ok": True, "neighbors": []})
        if endpoint == "topology":
            return _api_result(host, endpoint, {"ok": True, "nodes": [{"name": "gate01", "status": "online"}]})
        raise AssertionError(endpoint)

    monkeypatch.setattr(diagnostics, "fetch_node_api", fake_fetch)

    payload = diagnostics.run_diagnostics(config="examples/three-node-field-mesh.yml")

    assert payload["support_code"] == "EM-OK"
    assert "Node gate01" in payload["summary"]
    assert payload["topology"]["nodes"][0]["name"] == "gate01"


def test_export_support_bundle_writes_zip_layout_and_redacts(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    fleet = workspace / "Fleets" / "field.yml"
    fleet.write_text(
        """version: 1
mesh:
  id: field
  password: super-secret
  channel: 42
  bandwidth_mhz: 2
  country: US
defaults:
  target: rpi4-mm6108-spi
  management:
    root_password_hash: "$6$secret"
    ssh_authorized_keys: []
nodes:
  gate01:
    role: gate
    hostname: gate01
    ip: 10.41.1.1
"""
    )

    def fake_run_diagnostics(config=""):
        return {
            "ok": True,
            "generated_at": "2026-06-20T00:00:00Z",
            "support_code": "EM-OK",
            "support_level": "ok",
            "summary": "EasyMANET Diagnostics\nSupport code: EM-OK\n",
            "config_path": str(fleet),
            "validation": {"ok": True},
            "discovery": {},
            "topology": {},
            "nodes": {
                "gate01": {
                    "identity": {"ok": True, "payload": {"node": {"name": "gate01"}}},
                    "status": {"ok": True, "payload": {"support_code": "EM-OK"}},
                    "neighbors": {"ok": True, "payload": {"neighbors": []}},
                }
            },
        }

    monkeypatch.setattr(diagnostics, "run_diagnostics", fake_run_diagnostics)

    payload = diagnostics.export_support_bundle(config="field")

    bundle = Path(payload["bundle_path"])
    assert bundle.parent == workspace / "Diagnostics"
    with ZipFile(bundle) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "summary.txt" in names
        assert "fleet/redacted-fleet.yml" in names
        assert "nodes/gate01/status.json" in names
        redacted = zf.read("fleet/redacted-fleet.yml").decode()
        assert "super-secret" not in redacted
        assert "<redacted>" in redacted


def test_import_boot_report_copies_reports_to_workspace_diagnostics(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    source = tmp_path / "boot" / "easymanet"
    report = source / "boot-report-latest"
    report.mkdir(parents=True)
    (report / "summary.txt").write_text("reason=init\n")

    payload = diagnostics.import_boot_report(source=str(tmp_path / "boot"))

    assert payload["ok"] is True
    imported = Path(payload["imported"][0])
    assert imported.is_dir()
    assert imported.is_relative_to(workspace / "Diagnostics")
    assert (imported / "summary.txt").read_text() == "reason=init\n"


def test_redact_value_removes_obvious_secret_fields():
    value = {
        "mesh": {"password": "secret"},
        "gateway": {"wifi": {"password": "wifi-secret"}},
        "node": {"name": "gate01"},
    }

    redacted = diagnostics.redact_value(value)

    assert redacted["mesh"]["password"] == "<redacted>"
    assert redacted["gateway"]["wifi"]["password"] == "<redacted>"
    assert redacted["node"]["name"] == "gate01"
