import json
from pathlib import Path
from zipfile import ZipFile

from easymanet import diagnostics
from easymanet.workspace import WORKSPACE_ENV, ensure_workspace


def _api_result(host: str, endpoint: str, payload: dict, *, ok: bool = True) -> diagnostics.ApiResult:
    return diagnostics.ApiResult(ok=ok, host=host, endpoint=endpoint, payload=payload, error="" if ok else "down")


def test_run_diagnostics_collects_status_and_summary(monkeypatch):
    observed_timeouts = {}

    def fake_fetch(host, endpoint, timeout=diagnostics.HTTP_TIMEOUT_SECONDS):
        observed_timeouts[endpoint] = timeout
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
    assert observed_timeouts["status"] == diagnostics.STATUS_TIMEOUT_SECONDS
    assert observed_timeouts["topology"] == diagnostics.TOPOLOGY_TIMEOUT_SECONDS


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
    imported_report = workspace / "Diagnostics" / diagnostics.BOOT_REPORT_IMPORT_DIR / "20260620T000000Z" / "boot-report-latest"
    imported_report.mkdir(parents=True)
    (imported_report / "provision.json").write_text('{"mesh":{"password":"boot-secret"},"root_password_hash":"$6$boot"}\n')

    def fake_run_diagnostics(config: str = "") -> dict:
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
                },
                "point01": {
                    "identity": {"ok": False, "host": "10.41.2.1", "endpoint": "identity", "payload": {}, "error": "timeout"},
                    "status": {"ok": False, "host": "10.41.2.1", "endpoint": "status", "payload": {}, "error": "timeout"},
                    "neighbors": {"ok": False, "host": "10.41.2.1", "endpoint": "neighbors", "payload": {}, "error": "timeout"},
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
        assert "$6$secret" not in redacted
        assert "root_password_hash: <redacted>" in redacted
        assert "<redacted>" in redacted
        failed_status = json.loads(zf.read("nodes/point01/status.json"))
        assert failed_status["ok"] is False
        assert failed_status["host"] == "10.41.2.1"
        assert failed_status["error"] == "timeout"
        boot_report = zf.read("boot-reports/20260620T000000Z/boot-report-latest/provision.json").decode()
        assert "boot-secret" not in boot_report
        assert "$6$boot" not in boot_report


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


def test_import_boot_report_preserves_symlinks(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    source = tmp_path / "boot" / "easymanet"
    report = source / "boot-report-latest"
    report.mkdir(parents=True)
    target = tmp_path / "host-secret.txt"
    target.write_text("do not copy\n")
    (report / "linked-secret.txt").symlink_to(target)

    payload = diagnostics.import_boot_report(source=str(tmp_path / "boot"))

    assert payload["ok"] is True
    imported_link = Path(payload["imported"][0]) / "linked-secret.txt"
    assert imported_link.is_symlink()
    assert imported_link.resolve() == target


def test_import_boot_report_rejects_blank_and_file_sources(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    file_source = tmp_path / "boot-report.txt"
    file_source.write_text("not a directory\n")

    blank = diagnostics.import_boot_report(source=" ")
    file_payload = diagnostics.import_boot_report(source=str(file_source))

    assert blank["ok"] is False
    assert "source is required" in blank["errors"][0]
    assert file_payload["ok"] is False
    assert "source is not a directory" in file_payload["errors"][0]


def test_diagnostics_support_code_reports_missing_configured_node():
    code = diagnostics._diagnostics_support_code(
        {
            "gate01": {
                "candidate": {"source": "fleet"},
                "identity": {"ok": True},
                "status": {"ok": True, "payload": {"support_code": "EM-OK"}},
            },
            "point01": {
                "candidate": {"source": "fleet"},
                "identity": {"ok": False},
                "status": {"ok": False, "payload": {}, "error": "timeout"},
            },
        }
    )

    assert code == "EM-NODE-MISSING"


def test_redact_value_removes_obvious_secret_fields():
    value = {
        "mesh": {"password": "secret", "mesh_psk": "psk-secret"},
        "gateway": {"wifi": {"password": "wifi-secret", "wifi_passphrase": "phrase-secret"}},
        "api_key_id": "api-secret",
        "public_key_fingerprint": "not-secret",
        "node": {"name": "gate01"},
    }

    redacted = diagnostics.redact_value(value)

    assert redacted["mesh"]["password"] == "<redacted>"
    assert redacted["mesh"]["mesh_psk"] == "<redacted>"
    assert redacted["gateway"]["wifi"]["password"] == "<redacted>"
    assert redacted["gateway"]["wifi"]["wifi_passphrase"] == "<redacted>"
    assert redacted["api_key_id"] == "<redacted>"
    assert redacted["public_key_fingerprint"] == "not-secret"
    assert redacted["node"]["name"] == "gate01"
