from types import SimpleNamespace
import json
from pathlib import Path

from easymanet_desktop import bridge
from easymanet_desktop import payloads
from easymanet_desktop import server
from easymanet.flash import FlashErrorCode, FlashEvent
from easymanet.workspace import WORKSPACE_ENV, ensure_workspace


def test_desktop_validate_payload_returns_nodes():
    payload = payloads.validate_payload(
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

    monkeypatch.setattr(payloads, "cache_dir", lambda: cache)
    monkeypatch.setattr(payloads, "images_manifest_path", lambda: manifest)
    monkeypatch.setattr(payloads, "get_cached_image", lambda _target: None)

    payload = payloads.state_payload()

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

    payload = payloads.validate_payload({"config": "field", "node": "point01"})

    assert payload["ok"] is True
    assert payload["config_path"] == str(fleet)
    assert "point01" in payload["nodes"]


def test_desktop_resolve_config_rejects_non_yaml_file(tmp_path):
    config = tmp_path / "notes.txt"
    config.write_text("not: fleet\n")

    payload = payloads.resolve_config_payload(config=str(config))

    assert payload["ok"] is False
    assert payload["errors"] == ["Fleet config file must be .yml or .yaml"]
    assert payload["config_path"] == str(config)


def test_desktop_disks_payload_serializes_disk_info(monkeypatch):
    monkeypatch.setattr(payloads, "check_platform", lambda: None)
    monkeypatch.setattr(
        payloads,
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

    payload = payloads.disks_payload(include_all=False)

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


def test_desktop_bridge_flash_plan_outputs_json(monkeypatch, capsys):
    calls = []

    def fake_run_flash_workflow(options, emit=None):
        del emit
        calls.append(options)
        return SimpleNamespace(
            to_dict=lambda include_events=False: {
                "ok": True,
                "events": [] if include_events else None,
                "image": {"cached_path": "/tmp/openmanet.img.gz"},
            }
        )

    monkeypatch.setattr(bridge, "run_flash_workflow", fake_run_flash_workflow)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {"target": "rpi4-mm6108-spi", "cached_path": "/tmp/openmanet.img.gz"},
    )

    exit_code = bridge.main(
        [
            "flash-plan",
            "--config",
            "examples/three-node-field-mesh.yml",
            "--node",
            "point01",
            "--device",
            "/dev/disk4",
            "--enable-ssh",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["image"]["cached_path"] == "/tmp/openmanet.img.gz"
    assert calls[0].dry_run is True
    assert calls[0].yes is False
    assert calls[0].enable_ssh is True


def test_desktop_bridge_flash_returns_sudo_fallback_on_privilege_error(monkeypatch):
    def fake_run_flash_workflow(options, emit=None):
        del options, emit
        return SimpleNamespace(
            to_dict=lambda include_events=False: {
                "ok": False,
                "code": FlashErrorCode.PRIVILEGE_REQUIRED.value,
                "errors": ["Write access is required"],
                "image": {"cached_path": "/tmp/openmanet.img.gz", "sha256": "a" * 64},
            }
        )

    monkeypatch.setattr(bridge, "run_flash_workflow", fake_run_flash_workflow)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {"cached_path": "/tmp/openmanet.img.gz", "sha256": "a" * 64},
    )
    monkeypatch.setattr(bridge.sys, "executable", "/Applications/EasyMANET.app/Contents/Resources/backend/easymanet-bridge/easymanet-bridge")
    monkeypatch.setattr(bridge.sys, "frozen", True, raising=False)

    payload = bridge.flash_payload(
        config="/Users/example/fleet.yml",
        node="point01",
        device="/dev/disk4",
        yes=True,
    )

    assert payload["ok"] is False
    assert payload["sudo_command"].startswith("sudo ")
    assert "easymanet-bridge flash" in payload["sudo_command"]
    assert "--base-image /tmp/openmanet.img.gz --image-sha256 " + "a" * 64 in payload["sudo_command"]


def test_desktop_bridge_sudo_fallback_preserves_unverified_custom_image(monkeypatch):
    def fake_run_flash_workflow(options, emit=None):
        del options, emit
        return SimpleNamespace(
            to_dict=lambda include_events=False: {
                "ok": False,
                "code": FlashErrorCode.PRIVILEGE_REQUIRED.value,
                "errors": ["Write access is required"],
                "image": {"path": "/tmp/custom-openmanet.img.gz", "sha256": ""},
            }
        )

    monkeypatch.setattr(bridge, "run_flash_workflow", fake_run_flash_workflow)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {"cached_path": "/tmp/default.img.gz", "sha256": "b" * 64},
    )

    payload = bridge.flash_payload(
        config="/Users/example/fleet.yml",
        node="point01",
        device="/dev/disk4",
        yes=True,
    )

    assert "--base-image /tmp/custom-openmanet.img.gz" in payload["sudo_command"]
    assert "--image-sha256" not in payload["sudo_command"]


def test_desktop_bridge_flash_streams_events_and_final_result(monkeypatch, capsys):
    def fake_run_flash_workflow(options, emit=None):
        assert options.yes is True
        assert emit is not None
        emit(FlashEvent("write_started", "Writing image"))
        return SimpleNamespace(
            to_dict=lambda include_events=False: {
                "ok": True,
                "code": "ok",
                "image": {"cached_path": "/tmp/openmanet.img.gz"},
            }
        )

    monkeypatch.setattr(bridge, "run_flash_workflow", fake_run_flash_workflow)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {"cached_path": "/tmp/openmanet.img.gz"},
    )

    exit_code = bridge.main(
        [
            "flash",
            "--config",
            "examples/three-node-field-mesh.yml",
            "--node",
            "point01",
            "--device",
            "/dev/disk4",
            "--yes",
        ]
    )

    assert exit_code == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["type"] == "event"
    assert lines[0]["event_type"] == "write_started"
    assert lines[-1]["type"] == "result"
    assert lines[-1]["ok"] is True
    assert "events" not in lines[-1]


def test_desktop_bridge_flash_uses_core_internal_result(monkeypatch, capsys):
    def fake_run_flash_workflow(options, emit=None):
        assert options.yes is True
        assert emit is not None
        return SimpleNamespace(
            to_dict=lambda include_events=False: {
                "ok": False,
                "exit_code": 1,
                "code": FlashErrorCode.INTERNAL.value,
                "errors": ["Unexpected flash workflow error: OSError: download failed"],
                "image": {},
            }
        )

    monkeypatch.setattr(bridge, "run_flash_workflow", fake_run_flash_workflow)
    monkeypatch.setattr(
        bridge,
        "_safe_flash_image_details",
        lambda **_kwargs: {"target": "rpi4-mm6108-spi"},
    )

    exit_code = bridge.main(
        [
            "flash",
            "--config",
            "examples/three-node-field-mesh.yml",
            "--node",
            "point01",
            "--device",
            "/dev/disk4",
            "--yes",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "result"
    assert payload["ok"] is False
    assert payload["code"] == FlashErrorCode.INTERNAL.value
    assert payload["errors"] == ["Unexpected flash workflow error: OSError: download failed"]


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
    assert "nativeApi.flashPlan" in text
    assert "nativeApi.flash" in text
    assert "nativeApi.onFlashEvent" in text
    assert "nativeApi.copyText" in text
    assert "fleet-select" in index.read_text()
    assert "open-fleets-folder" in index.read_text()
    assert "flash-panel" in index.read_text()
    assert "preview-flash" in index.read_text()
    assert "start-flash" in index.read_text()
    assert "renderFleets" in text
    assert "flashPanel.hidden = true" in text


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
    assert (electron / "path-utils.js").exists()
    assert (electron / "preload.js").exists()
    assert bridge_runner.exists()
    assert "loadFile(indexHtmlPath())" in (electron / "main.js").read_text()
    assert "contextBridge.exposeInMainWorld" in (electron / "preload.js").read_text()
    assert "easymanet:open-fleets-folder" in (electron / "main.js").read_text()
    assert "easymanet:flash-plan" in (electron / "main.js").read_text()
    assert "easymanet:flash" in (electron / "main.js").read_text()
    assert "easymanet:flash-event" in (electron / "main.js").read_text()
    assert "resolveConfigPath(config, {" in (electron / "main.js").read_text()
    assert "fleetPathCandidates" not in (electron / "main.js").read_text()
    assert "fleetExtensions" not in (electron / "main.js").read_text()
    path_utils_text = (electron / "path-utils.js").read_text()
    assert "resolveConfigPath" in path_utils_text
    assert "hasTraversalSegment" in path_utils_text
    assert "resolve-config" in path_utils_text
    assert "resolveConfigPath(\"field\"" in (electron / "scripts" / "check-electron.js").read_text()
    assert "flashBridgeTimeoutMs" in (electron / "main.js").read_text()
    assert "runBridgeStreaming" in (electron / "main.js").read_text()
    assert "fullStdout" in (electron / "main.js").read_text()
    assert "isDestroyed" in (electron / "main.js").read_text()
    assert "streamEvents" not in (electron / "main.js").read_text()
    assert "copyText" in (electron / "preload.js").read_text()
    assert "onFlashEvent" in (electron / "preload.js").read_text()
    assert "EASYMANET_ELECTRON_NO_SOURCE_PATHS" in (electron / "main.js").read_text()
    assert "bridgeTimeoutMs" in (electron / "main.js").read_text()
    assert "process.resourcesPath" in (electron / "main.js").read_text()
    assert "desktop-static" in (electron / "main.js").read_text()
    assert "EASYMANET_BRIDGE_BIN is a development/testing override" in (electron / "main.js").read_text()
    assert "EASYMANET_ELECTRON_ALLOW_BRIDGE_OVERRIDE" in (electron / "main.js").read_text()
    assert "build:backend" in (electron / "package.json").read_text()
    assert "electron-builder" in (electron / "package.json").read_text()
    runner_text = bridge_runner.read_text()
    assert 'candidates.push("python", "py")' in runner_text
    assert 'process.env.PYTHON' in runner_text
    build_text = (electron / "scripts" / "build-bridge.py").read_text()
    assert '"easymanet_cli"' not in build_text
    assert 'ROOT / "apps" / "cli" / "src"' not in build_text
