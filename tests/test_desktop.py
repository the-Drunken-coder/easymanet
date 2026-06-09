from types import SimpleNamespace
import json
from pathlib import Path

from easymanet_desktop import bridge
from easymanet_desktop import server
from easymanet.workspace import WORKSPACE_ENV, ensure_workspace


def test_desktop_validate_payload_returns_nodes():
    payload = server._validate_payload(
        {
            "config": "examples/three-node-field-mesh.yml",
            "node": "point01",
        }
    )

    assert payload["ok"] is True
    assert "point01" in payload["nodes"]


def test_desktop_state_reads_configured_images_and_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    (workspace / "Fleets" / "field.yml").write_text(
        Path("examples/three-node-field-mesh.yml").read_text()
    )
    cache = tmp_path / "images"
    manifest = tmp_path / "images.json"
    cache.mkdir()
    manifest.write_text(
        '{"rpi4-mm6108-spi": {"version": "1.6.5", "sha256": "%s"}}' % ("a" * 64)
    )

    monkeypatch.setattr(server, "CACHE_DIR", cache)
    monkeypatch.setattr(server, "IMAGES_MANIFEST", manifest)
    monkeypatch.setattr(server, "get_cached_image", lambda _target: None)

    payload = server._state_payload()

    assert payload["ok"] is True
    assert payload["workspace"]["root"] == str(workspace)
    assert payload["workspace"]["fleet_files"][0]["relative_path"] == "field.yml"
    assert payload["image_cache_dir"] == str(cache)
    assert payload["images"]["rpi4-mm6108-spi"]["version"] == "1.6.5"


def test_desktop_validate_resolves_workspace_fleet_name(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    fleet = workspace / "Fleets" / "field.yml"
    fleet.write_text(Path("examples/three-node-field-mesh.yml").read_text())

    payload = server._validate_payload({"config": "field", "node": "point01"})

    assert payload["ok"] is True
    assert payload["config_path"] == str(fleet)
    assert "point01" in payload["nodes"]


def test_desktop_disks_payload_serializes_disk_info(monkeypatch):
    monkeypatch.setattr(server, "check_platform", lambda: None)
    monkeypatch.setattr(
        server,
        "list_disks",
        lambda include_all=False: [
            SimpleNamespace(
                device="/dev/disk4",
                model="USB",
                size_human="8 GB",
                removable=True,
                mounted=[],
                warnings=[],
            )
        ],
    )

    payload = server._disks_payload(include_all=False)

    assert payload["ok"] is True
    assert payload["disks"][0]["device"] == "/dev/disk4"


def test_desktop_bridge_validate_outputs_json(capsys):
    exit_code = bridge.main(
        [
            "validate",
            "--config",
            "examples/three-node-field-mesh.yml",
            "--node",
            "point01",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert "point01" in payload["nodes"]


def test_desktop_static_supports_electron_and_http_modes():
    root = Path(__file__).resolve().parents[1]
    index = root / "apps" / "desktop" / "src" / "easymanet_desktop" / "static" / "index.html"
    app_js = root / "apps" / "desktop" / "src" / "easymanet_desktop" / "static" / "app.js"

    assert 'href="styles.css"' in index.read_text()
    assert 'src="app.js"' in index.read_text()
    text = app_js.read_text()
    assert "window.easymanet" in text
    assert "nativeApi.getState" in text
    assert "nativeApi.chooseConfig" in text
    assert "nativeApi.openFleetsFolder" in text
    assert "fleet-select" in index.read_text()
    assert "open-fleets-folder" in index.read_text()
    assert "renderFleets" in text


def test_desktop_static_containment_rejects_sibling_prefix(tmp_path):
    static_root = (tmp_path / "static").resolve()
    sibling = (tmp_path / "static-backup" / "secret.txt").resolve()

    assert server._is_relative_to(static_root / "index.html", static_root)
    assert not server._is_relative_to(sibling, static_root)


def test_electron_shell_files_exist():
    root = Path(__file__).resolve().parents[1]
    electron = root / "apps" / "desktop" / "electron"
    bridge_runner = electron / "scripts" / "run-build-bridge.js"

    assert (electron / "package.json").exists()
    assert (electron / "electron-builder.yml").exists()
    assert (electron / "main.js").exists()
    assert (electron / "preload.js").exists()
    assert bridge_runner.exists()
    assert "loadFile(indexHtmlPath())" in (electron / "main.js").read_text()
    assert "contextBridge.exposeInMainWorld" in (electron / "preload.js").read_text()
    assert "easymanet:open-fleets-folder" in (electron / "main.js").read_text()
    assert "EASYMANET_ELECTRON_NO_SOURCE_PATHS" in (electron / "main.js").read_text()
    assert "bridgeTimeoutMs" in (electron / "main.js").read_text()
    assert "process.resourcesPath" in (electron / "main.js").read_text()
    assert "desktop-static" in (electron / "main.js").read_text()
    assert "build:backend" in (electron / "package.json").read_text()
    assert "electron-builder" in (electron / "package.json").read_text()
    runner_text = bridge_runner.read_text()
    assert 'candidates.push("python", "py")' in runner_text
    assert 'process.env.PYTHON' in runner_text
