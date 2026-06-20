import json
import zipfile
from pathlib import Path

from easymanet import support_bundle
from easymanet.workspace import WORKSPACE_ENV, ensure_workspace


FLEET = """\
version: 1
mesh:
  id: field
  password: mesh-secret
  channel: 42
  bandwidth_mhz: 2
  country: US
defaults:
  target: rpi4-mm6108-spi
  local_ap:
    enabled: true
    password: ap-secret
nodes:
  point01:
    role: point
    hostname: point01
    ip: 10.41.2.1
"""


def test_support_bundle_zip_contains_redacted_diagnostics(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    fleet = workspace / "Fleets" / "field.yml"
    fleet.write_text(FLEET)
    boot = tmp_path / "boot-report-latest"
    boot.mkdir()
    (boot / "logread.txt").write_text("wifi password='boot-secret'\n")

    result = support_bundle.create_support_bundle(
        config="field",
        node="point01",
        boot_report=str(boot),
        output=str(tmp_path / "support.zip"),
        flash_log="api_key=secret-token\n",
    )

    assert result.path.name == "support.zip"
    with zipfile.ZipFile(result.path) as archive:
        names = set(archive.namelist())
        assert "support-bundle.json" in names
        assert "workspace/state.json" in names
        assert "images/inventory.json" in names
        assert "fleet/redacted-config.yml" in names
        assert "fleet/validation.json" in names
        assert "boot-reports/logread.txt" in names
        assert "flash/log.txt" in names
        redacted = archive.read("fleet/redacted-config.yml").decode()
        assert "mesh-secret" not in redacted
        assert "ap-secret" not in redacted
        assert "<redacted>" in redacted
        assert "boot-secret" not in archive.read("boot-reports/logread.txt").decode()
        assert "secret-token" not in archive.read("flash/log.txt").decode()
        report = json.loads(archive.read("redaction-report.json"))
        assert report["redacted"]


def test_default_support_bundle_path_uses_diagnostics_dir(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()

    path = support_bundle.default_support_bundle_path()

    assert path.parent == workspace / "Diagnostics"
    assert path.name.startswith("easymanet-support-")
    assert path.suffix == ".zip"
