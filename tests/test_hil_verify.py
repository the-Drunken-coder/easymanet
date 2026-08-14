import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from easymanet import diagnostics
from easymanet.support_bundle import redact_text
from easymanet.workspace import WORKSPACE_ENV
from tools import hil_verify


def _now():
    return datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)


def _api_result(host, endpoint, payload, *, ok=True):
    return diagnostics.ApiResult(ok=ok, host=host, endpoint=endpoint, payload=payload, error="" if ok else "down")


def _image_artifact(tmp_path, contents=b"firmware"):
    artifact = tmp_path / "openmanet.img.gz"
    artifact.write_bytes(contents)
    return artifact, hashlib.sha256(contents).hexdigest()


def _clean_provenance(sha="a" * 40):
    source = {
        "git_sha": sha,
        "dirty": False,
        "valid": True,
        "detail": "",
    }
    return {
        "runner": dict(source),
        "source": dict(source),
    }


def _stable_config_evidence():
    return {
        "path": "/tmp/fleet.yml",
        "sha256": "b" * 64,
        "size_bytes": 123,
        "stable": True,
    }


HIL_NONCE = "c" * 32
HIL_BOOT_ID = "11111111-2222-3333-4444-555555555555"


def _runtime_attestation(expected):
    return {
        **expected,
        "provisioned_at": "2026-06-30T12:00:01Z",
        "boot_id": HIL_BOOT_ID,
    }


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


def test_parse_args_refuses_same_disk_aliases():
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
                "--point-device",
                "/dev/rdisk4",
                "--dry-run",
            ]
        )


def test_parse_args_refuses_conflicting_download_modes(capsys):
    with pytest.raises(SystemExit):
        hil_verify.parse_args(
            [
                "--config",
                "examples/three-node-field-mesh.yml",
                "--gate-node",
                "gate01",
                "--point-node",
                "point01",
                "--download",
                "--no-download",
                "--dry-run",
            ]
        )
    assert "--download and --no-download cannot be used together" in capsys.readouterr().err


def test_parse_args_refuses_wait_outside_hil_window(capsys):
    with pytest.raises(SystemExit):
        hil_verify.parse_args(
            [
                "--config",
                "examples/three-node-field-mesh.yml",
                "--gate-node",
                "gate01",
                "--point-node",
                "point01",
                "--wait-seconds",
                "30",
            ]
        )
    assert "--wait-seconds must be between 90 and 120" in capsys.readouterr().err


def test_parse_args_requires_gate_boot_report_when_gate_ssh_is_disabled(capsys):
    with pytest.raises(SystemExit):
        hil_verify.parse_args(
            [
                "--config",
                "examples/three-node-field-mesh.yml",
                "--gate-node",
                "gate01",
                "--point-node",
                "point01",
                "--no-gate-ssh-enabled",
                "--point-boot-report",
                "/tmp/point-boot",
                "--wait-seconds",
                "90",
            ]
        )
    assert "--gate-boot-report is required when gate SSH checks are disabled" in capsys.readouterr().err


def test_parse_args_requires_ssh_for_throughput_smoke(capsys):
    with pytest.raises(SystemExit):
        hil_verify.parse_args(
            [
                "--config",
                "examples/three-node-field-mesh.yml",
                "--gate-node",
                "gate01",
                "--point-node",
                "point01",
                "--throughput-smoke",
                "--dry-run",
            ]
        )
    assert "--throughput-smoke requires --gate-ssh-enabled and --point-ssh-enabled" in capsys.readouterr().err


def test_dry_run_writes_result_and_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "EasyMANET"))
    monkeypatch.setattr(hil_verify, "_git_provenance", _clean_provenance)
    artifact, sha256 = _image_artifact(tmp_path)
    args = hil_verify.parse_args(
        [
            "--config",
            "examples/three-node-field-mesh.yml",
            "--gate-node",
            "gate01",
            "--point-node",
            "point01",
            "--base-image",
            str(artifact),
            "--image-sha256",
            sha256,
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
    assert payload["schema_version"] == 2
    assert payload["image"]["artifact_path"] == str(artifact.resolve())
    assert payload["image"]["sha256"] == sha256
    assert payload["image"]["trust"]["status"] == "checksum-only"
    assert payload["provenance"]["source"]["valid"] is True
    config_path = Path(payload["config"]["path"])
    assert payload["config"]["sha256"] == hashlib.sha256(config_path.read_bytes()).hexdigest()
    assert payload["config"]["stable"] is True
    assert payload["evidence_scope"] == {
        "kind": "synthetic-dry-run",
        "simulation": False,
        "calibration": False,
        "physical_acceptance": False,
        "detail": "Dry-run evidence does not probe hardware or establish physical acceptance.",
    }
    assert json.loads(result_path.read_text()) == payload


def test_role_mismatch_skips_flash(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "EasyMANET"))

    def fail_flash(*_args, **_kwargs):
        raise AssertionError("role mismatches must stop before flashing")

    monkeypatch.setattr(hil_verify, "run_flash_workflow", fail_flash)
    args = hil_verify.parse_args(
        [
            "--config",
            "examples/three-node-field-mesh.yml",
            "--gate-node",
            "point01",
            "--point-node",
            "gate01",
            "--gate-device",
            "/dev/disk4",
            "--point-device",
            "/dev/disk5",
            "--point-ssh-enabled",
            "--allow-flash",
            "--yes",
            "--wait-seconds",
            "90",
        ]
    )

    payload = hil_verify.run_hil(args, now_fn=_now)

    assert payload["ok"] is False
    assert payload["flash"] == {}
    assert any("point01 must be a gate node" in error for error in payload["errors"])
    assert any("gate01 must be a point node" in error for error in payload["errors"])


def test_unsafe_ip_override_stops_before_throughput_command(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "EasyMANET"))

    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("invalid probe hosts must stop before API probes")

    def fail_command(*_args, **_kwargs):
        raise AssertionError("invalid probe hosts must stop before SSH commands")

    monkeypatch.setattr(hil_verify, "fetch_node_api", fail_fetch)
    args = hil_verify.parse_args(
        [
            "--config",
            "examples/three-node-field-mesh.yml",
            "--gate-node",
            "gate01",
            "--point-node",
            "point01",
            "--point-ip",
            "10.41.1.2; reboot",
            "--point-ssh-enabled",
            "--throughput-smoke",
            "--wait-seconds",
            "90",
        ]
    )

    payload = hil_verify.run_hil(
        args,
        command_runner=fail_command,
        sleep_fn=lambda seconds: None,
        now_fn=_now,
    )

    assert payload["ok"] is False
    assert payload["flash"] == {}
    assert any("point01 probe address is invalid" in error for error in payload["errors"])
    assert any(check["name"] == "point01 probe address is IPv4" and not check["ok"] for check in payload["checks"])


@pytest.mark.parametrize(
    ("reported_nonce", "accepted"),
    [
        (HIL_NONCE, True),
        ("0" * 32, False),
    ],
)
def test_flash_mode_prompts_before_waiting_and_probing(
    tmp_path,
    monkeypatch,
    reported_nonce,
    accepted,
):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "EasyMANET"))
    monkeypatch.setattr(hil_verify, "_git_provenance", _clean_provenance)
    artifact, sha256 = _image_artifact(tmp_path)
    events = []
    expected_trust = {
        "status": "verified",
        "source": "official",
        "channel": "stable",
        "release_tag": "images-v1.2.3",
        "image_status": "current",
        "manifest_url": "https://example.invalid/manifest.json",
        "manifest_schema_version": 2,
        "manifest_signature_verified": True,
        "expected_repo": "the-Drunken-coder/easymanet-images",
        "attestation_subject_digest": sha256,
        "warnings": [],
    }

    class FakeFlashResult:
        ok = True
        errors = []

        def __init__(self, node):
            self.node = node

        def to_dict(self, include_events=False):
            return {
                "ok": True,
                "code": "ok",
                "node": self.node,
                "plan": {"device": f"/dev/{self.node}"},
                "image": {
                    "path": str(artifact),
                    "sha256": sha256,
                    "trust": expected_trust,
                },
                "events": [] if include_events else None,
            }

    flash_attestations = []

    def fake_flash(options):
        events.append(f"flash {options.node}")
        flash_attestations.append(options.attestation)
        return FakeFlashResult(options.node)

    def fake_fetch(host, endpoint, timeout=diagnostics.HTTP_TIMEOUT_SECONDS):
        events.append(f"fetch {endpoint}")
        node_name = "gate01" if host == "10.41.1.1" else "point01"
        role = "gate" if node_name == "gate01" else "point"
        if endpoint == "identity":
            expected = {
                **flash_attestations[0],
                "image_sha256": sha256,
            }
            reported = _runtime_attestation(expected)
            reported["hil_run_nonce"] = reported_nonce
            return _api_result(
                host,
                endpoint,
                {
                    "ok": True,
                    "node": {"name": node_name, "role": role, "ip": host},
                    "attestation": reported,
                },
            )
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

    monkeypatch.setattr(hil_verify, "run_flash_workflow", fake_flash)
    monkeypatch.setattr(hil_verify, "fetch_node_api", fake_fetch)
    args = hil_verify.parse_args(
        [
            "--config",
            "examples/three-node-field-mesh.yml",
            "--gate-node",
            "gate01",
            "--point-node",
            "point01",
            "--gate-device",
            "/dev/disk4",
            "--point-device",
            "/dev/disk5",
            "--point-ssh-enabled",
            "--allow-flash",
            "--yes",
            "--wait-seconds",
            "90",
        ]
    )

    payload = hil_verify.run_hil(
        args,
        command_runner=lambda command, timeout: subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
        input_fn=lambda prompt: events.append("prompt") or "",
        sleep_fn=lambda seconds: events.append(f"sleep {seconds}"),
        now_fn=_now,
        nonce_fn=lambda: HIL_NONCE,
    )

    assert payload["ok"] is accepted
    assert events[:4] == ["flash gate01", "flash point01", "prompt", "sleep 90"]
    assert any(check["name"] == "post-flash boot handoff confirmed" and check["ok"] for check in payload["checks"])
    assert payload["image"]["node_image_identity"] == "flashed"
    assert payload["image"]["sha256"] == sha256
    assert payload["image"]["trust"] == expected_trust
    assert payload["provenance"]["source"]["valid"] is True
    config_path = Path(payload["config"]["path"])
    assert payload["config"]["sha256"] == hashlib.sha256(config_path.read_bytes()).hexdigest()
    assert payload["config"]["stable"] is True
    assert flash_attestations == [
        {
            "hil_run_nonce": HIL_NONCE,
            "fleet_config_sha256": payload["config"]["sha256"],
            "source_git_sha": "a" * 40,
            "hil_started_at": "2026-06-30T12:00:00Z",
        }
    ] * 2
    assert payload["attestation"]["image_sha256"] == sha256
    assert payload["evidence_scope"]["physical_acceptance"] is accepted
    if accepted:
        assert payload["evidence_scope"]["kind"] == "physical-hil"
    else:
        assert payload["evidence_scope"]["kind"] == "physical-observation"
        assert any(
            check["name"].endswith("runtime attestation")
            and check["ok"] is False
            for check in payload["checks"]
        )


def test_reuse_nodes_collects_mock_hardware_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "EasyMANET"))
    artifact, sha256 = _image_artifact(tmp_path)
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
            "--base-image",
            str(artifact),
            "--image-sha256",
            sha256,
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
    assert payload["image"] == {
        "artifact_path": str(artifact.resolve()),
        "artifact_id": f"sha256:{sha256}",
        "sha256": sha256,
        "local_digest_verified": True,
        "node_image_identity": "not-attested",
        "trust": hil_verify.image_trust_payload(hil_verify.custom_trust()),
    }
    assert payload["evidence_scope"]["kind"] == "physical-observation"
    assert payload["evidence_scope"]["physical_acceptance"] is False


def test_git_provenance_records_clean_runner_and_source_shas(monkeypatch):
    sha256 = "a" * 40

    def fake_git_output(args):
        return sha256 if args == ["rev-parse", "HEAD"] else ""

    monkeypatch.setattr(hil_verify, "_git_output", fake_git_output)

    provenance = hil_verify._git_provenance()

    assert provenance["runner"]["git_sha"] == sha256
    assert provenance["source"]["git_sha"] == sha256
    assert provenance["runner"]["dirty"] is False
    assert provenance["source"]["dirty"] is False
    assert provenance["runner"]["valid"] is True
    assert provenance["source"]["valid"] is True


def test_git_provenance_records_dirty_state_without_claiming_clean(monkeypatch):
    sha256 = "b" * 40

    def fake_git_output(args):
        if args == ["rev-parse", "HEAD"]:
            return sha256
        return " M tools/hil_verify.py\n?? local-evidence.json"

    monkeypatch.setattr(hil_verify, "_git_output", fake_git_output)

    provenance = hil_verify._git_provenance()

    assert provenance["runner"]["git_sha"] == sha256
    assert provenance["source"]["git_sha"] == sha256
    assert provenance["runner"]["dirty"] is True
    assert provenance["source"]["dirty"] is True
    assert provenance["runner"]["valid"] is True
    assert provenance["source"]["valid"] is True


def test_git_provenance_marks_non_commit_head_invalid(monkeypatch):
    def fake_git_output(args):
        return "not-a-commit" if args == ["rev-parse", "HEAD"] else ""

    monkeypatch.setattr(hil_verify, "_git_output", fake_git_output)

    provenance = hil_verify._git_provenance()

    assert provenance["source"]["git_sha"] == "not-a-commit"
    assert provenance["source"]["dirty"] is False
    assert provenance["source"]["valid"] is False
    assert "40-character" in provenance["source"]["detail"]


def test_git_provenance_records_unavailable_source(monkeypatch):
    def fail_git_output(_args):
        raise subprocess.CalledProcessError(128, ["git"])

    monkeypatch.setattr(hil_verify, "_git_output", fail_git_output)

    provenance = hil_verify._git_provenance()

    assert provenance["source"]["git_sha"] == ""
    assert provenance["source"]["dirty"] is None
    assert provenance["source"]["valid"] is False
    assert "unavailable" in provenance["source"]["detail"].lower()


@pytest.mark.parametrize(
    "missing_attribution",
    [
        "dirty-source",
        "unavailable-source",
        "invalid-source",
        "unstable-config",
        "missing-config-digest",
    ],
)
def test_attribution_gaps_preserve_observation_but_block_acceptance(missing_attribution):
    provenance = _clean_provenance()
    config = _stable_config_evidence()
    if missing_attribution == "dirty-source":
        provenance["source"]["dirty"] = True
    elif missing_attribution == "unavailable-source":
        provenance["source"].update(
            {"git_sha": "", "dirty": None, "valid": False}
        )
    elif missing_attribution == "invalid-source":
        provenance["source"].update(
            {"git_sha": "not-a-commit", "valid": False}
        )
    elif missing_attribution == "unstable-config":
        config["stable"] = False
    else:
        config["sha256"] = ""

    scope = hil_verify._evidence_scope(
        "flash",
        True,
        {
            "gate01": {"ok": True, "mode": "flash"},
            "point01": {"ok": True, "mode": "flash"},
        },
        {
            "node_image_identity": "flashed",
            "local_digest_verified": True,
        },
        provenance,
        config,
        {
            "gate01": {"attestation": {"ok": True}},
            "point01": {"attestation": {"ok": True}},
        },
    )

    assert scope["kind"] == "physical-observation"
    assert scope["physical_acceptance"] is False
    assert "Behavioral HIL passed" in scope["detail"]


def test_stale_node_attestation_blocks_physical_acceptance():
    scope = hil_verify._evidence_scope(
        "flash",
        False,
        {
            "gate01": {"ok": True, "mode": "flash"},
            "point01": {"ok": True, "mode": "flash"},
        },
        {
            "node_image_identity": "flashed",
            "local_digest_verified": True,
        },
        _clean_provenance(),
        _stable_config_evidence(),
        {
            "gate01": {"attestation": {"ok": False}},
            "point01": {"attestation": {"ok": True}},
        },
    )

    assert scope["kind"] == "physical-observation"
    assert scope["physical_acceptance"] is False
    assert "did not attest" in scope["detail"]


def test_naive_provisioning_timestamp_is_not_current_run_evidence():
    assert hil_verify._provisioned_during_run(
        "2026-06-30T12:00:01",
        "2026-06-30T12:00:00Z",
    ) is False


def test_future_provisioning_timestamp_is_not_current_run_evidence(monkeypatch):
    observed = _now()
    monkeypatch.setattr(hil_verify, "_utc_now", lambda: observed)

    assert hil_verify._provisioned_during_run(
        hil_verify._iso(observed + hil_verify.MAX_NODE_CLOCK_SKEW),
        hil_verify._iso(observed),
    ) is True
    assert hil_verify._provisioned_during_run(
        hil_verify._iso(
            observed + hil_verify.MAX_NODE_CLOCK_SKEW + timedelta(seconds=1)
        ),
        hil_verify._iso(observed),
    ) is False


def test_manifest_snapshot_is_stable_when_source_changes_during_load(tmp_path, monkeypatch):
    source = hil_verify.REPO_ROOT / "examples" / "three-node-field-mesh.yml"
    config = tmp_path / "fleet.yml"
    snapshot = tmp_path / "snapshot.yml"
    original = source.read_bytes()
    config.write_bytes(original)
    real_load_manifest = hil_verify.load_manifest

    def load_then_mutate(path):
        manifest = real_load_manifest(path)
        config.write_bytes(original + b"\n# changed during load\n")
        return manifest

    monkeypatch.setattr(hil_verify, "load_manifest", load_then_mutate)
    checks = []
    errors = []

    manifest, evidence = hil_verify._load_manifest_for_result(
        config,
        snapshot,
        checks,
        errors,
    )

    assert manifest is not None
    assert snapshot.read_bytes() == original
    assert evidence["sha256"] == hashlib.sha256(original).hexdigest()
    assert evidence["stable"] is True
    assert errors == []
    assert any(
        check["name"] == "fleet config identity" and check["ok"] is True
        for check in checks
    )


def test_flash_acceptance_uses_one_config_snapshot_when_source_changes_between_flashes(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "EasyMANET"))
    monkeypatch.setattr(hil_verify, "_git_provenance", _clean_provenance)
    source = hil_verify.REPO_ROOT / "examples" / "three-node-field-mesh.yml"
    config = tmp_path / "fleet.yml"
    original = source.read_bytes()
    changed = original + b"\n# changed between flashes\n"
    config.write_bytes(original)
    artifact, sha256 = _image_artifact(tmp_path)
    flashed_configs: list[bytes] = []
    flashed_config_paths: list[Path] = []

    class FakeFlashResult:
        ok = True
        errors = []

        def __init__(self, node):
            self.node = node

        def to_dict(self, include_events=False):
            return {
                "ok": True,
                "node": self.node,
                "image": {"path": str(artifact), "sha256": sha256},
                "events": [] if include_events else None,
            }

    def fake_flash(options):
        flashed_config_paths.append(Path(options.config))
        flashed_configs.append(Path(options.config).read_bytes())
        if options.node == "gate01":
            config.write_bytes(changed)
        return FakeFlashResult(options.node)

    monkeypatch.setattr(hil_verify, "run_flash_workflow", fake_flash)
    monkeypatch.setattr(
        hil_verify,
        "_probe_node",
        lambda *_args, **_kwargs: {"attestation": {"ok": True}},
    )
    monkeypatch.setattr(hil_verify, "_probe_topology", lambda *_args: {"ok": True})
    args = hil_verify.parse_args(
        [
            "--config",
            str(config),
            "--gate-node",
            "gate01",
            "--point-node",
            "point01",
            "--gate-device",
            "/dev/disk4",
            "--point-device",
            "/dev/disk5",
            "--point-ssh-enabled",
            "--allow-flash",
            "--yes",
            "--skip-boot-prompt",
            "--wait-seconds",
            "90",
        ]
    )

    payload = hil_verify.run_hil(
        args,
        sleep_fn=lambda _seconds: None,
        now_fn=_now,
    )

    assert config.read_bytes() == changed
    assert flashed_config_paths[0] == flashed_config_paths[1]
    assert flashed_config_paths[0] != config
    assert flashed_configs == [original, original]
    assert payload["config"]["path"] == str(config.resolve())
    assert payload["config"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert payload["evidence_scope"]["physical_acceptance"] is True
    with zipfile.ZipFile(payload["support_bundle_path"]) as bundle:
        bundled_config = bundle.read("fleet/redacted-config.yml").decode()
        bundled_result = json.loads(bundle.read("flash/result.json"))
        bundle_metadata = json.loads(bundle.read("support-bundle.json"))
    assert bundled_config == redact_text(original.decode())
    assert bundle_metadata["config"] == str(config.resolve())
    assert bundled_result["config"]["path"] == str(config.resolve())
    assert bundled_result["config"]["sha256"] == hashlib.sha256(original).hexdigest()


def test_reuse_rejects_missing_local_artifact_before_probes(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "EasyMANET"))

    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("reuse must verify image identity before probes")

    monkeypatch.setattr(hil_verify, "fetch_node_api", fail_fetch)
    args = hil_verify.parse_args(
        [
            "--config",
            "examples/three-node-field-mesh.yml",
            "--gate-node",
            "gate01",
            "--point-node",
            "point01",
            "--base-image",
            str(tmp_path / "missing.img.gz"),
            "--image-sha256",
            hashlib.sha256(b"firmware").hexdigest(),
            "--point-ssh-enabled",
            "--wait-seconds",
            "90",
        ]
    )

    payload = hil_verify.run_hil(args, now_fn=_now)

    assert payload["ok"] is False
    assert payload["nodes"] == {}
    assert any("Image artifact not found" in error for error in payload["errors"])
    assert any(check["name"] == "reuse image identity" and not check["ok"] for check in payload["checks"])


def test_reuse_rejects_stale_or_mismatched_local_artifact_before_probes(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "EasyMANET"))
    artifact, _sha256 = _image_artifact(tmp_path, b"old firmware")

    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("reuse must verify image identity before probes")

    monkeypatch.setattr(hil_verify, "fetch_node_api", fail_fetch)
    args = hil_verify.parse_args(
        [
            "--config",
            "examples/three-node-field-mesh.yml",
            "--gate-node",
            "gate01",
            "--point-node",
            "point01",
            "--base-image",
            str(artifact),
            "--image-sha256",
            hashlib.sha256(b"current firmware").hexdigest(),
            "--point-ssh-enabled",
            "--wait-seconds",
            "90",
        ]
    )

    payload = hil_verify.run_hil(args, now_fn=_now)

    assert payload["ok"] is False
    assert payload["nodes"] == {}
    assert payload["image"]["local_digest_verified"] is False
    assert any("reuse image identity failed" in error.lower() for error in payload["errors"])


def test_mixed_flash_and_reuse_requires_image_identity_before_flash_or_probes(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "EasyMANET"))

    def fail_flash(*_args, **_kwargs):
        raise AssertionError("mixed mode must verify reuse identity before flashing")

    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("mixed mode must verify reuse identity before probes")

    monkeypatch.setattr(hil_verify, "run_flash_workflow", fail_flash)
    monkeypatch.setattr(hil_verify, "fetch_node_api", fail_fetch)
    args = hil_verify.parse_args(
        [
            "--config",
            "examples/three-node-field-mesh.yml",
            "--gate-node",
            "gate01",
            "--point-node",
            "point01",
            "--gate-device",
            "/dev/disk4",
            "--point-ssh-enabled",
            "--allow-flash",
            "--yes",
            "--wait-seconds",
            "90",
        ]
    )

    payload = hil_verify.run_hil(args, now_fn=_now)

    assert payload["ok"] is False
    assert payload["flash"] == {}
    assert payload["nodes"] == {}
    assert any("Reuse requires --base-image" in error for error in payload["errors"])


def test_mixed_flash_and_reuse_is_physical_observation_not_acceptance(tmp_path, monkeypatch):
    monkeypatch.setenv(WORKSPACE_ENV, str(tmp_path / "EasyMANET"))
    artifact, sha256 = _image_artifact(tmp_path)

    class FakeFlashResult:
        ok = True
        errors = []

        def to_dict(self, include_events=False):
            return {
                "ok": True,
                "image": {"path": str(artifact), "sha256": sha256},
                "events": [] if include_events else None,
            }

    monkeypatch.setattr(hil_verify, "_flash_node", lambda *_args: FakeFlashResult())
    monkeypatch.setattr(
        hil_verify,
        "_probe_node",
        lambda *_args, **_kwargs: {"attestation": {"ok": True}},
    )
    monkeypatch.setattr(hil_verify, "_probe_topology", lambda *_args: {"ok": True})
    args = hil_verify.parse_args(
        [
            "--config",
            "examples/three-node-field-mesh.yml",
            "--gate-node",
            "gate01",
            "--point-node",
            "point01",
            "--gate-device",
            "/dev/disk4",
            "--base-image",
            str(artifact),
            "--image-sha256",
            sha256,
            "--point-ssh-enabled",
            "--allow-flash",
            "--yes",
            "--wait-seconds",
            "90",
        ]
    )

    payload = hil_verify.run_hil(
        args,
        input_fn=lambda _prompt: "",
        sleep_fn=lambda _seconds: None,
        now_fn=_now,
    )

    assert payload["ok"] is True
    assert payload["mode"] == "flash"
    assert payload["image"]["node_image_identity"] == "mixed"
    assert payload["evidence_scope"]["kind"] == "physical-observation"
    assert payload["evidence_scope"]["physical_acceptance"] is False


def test_real_run_requires_boot_report_when_point_ssh_is_disabled(capsys):
    with pytest.raises(SystemExit):
        hil_verify.parse_args(
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
    assert "--point-boot-report is required when point SSH checks are disabled" in capsys.readouterr().err


def test_ssh_spawn_failure_returns_structured_result():
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

    def fail_spawn(_command, _timeout):
        raise FileNotFoundError("ssh")

    result = hil_verify._ssh_command(args, "10.41.1.1", "true", fail_spawn)

    assert result["ok"] is False
    assert result["exit_code"] is None
    assert "FileNotFoundError" in result["error"]


def test_ssh_command_uses_ephemeral_known_hosts():
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
    commands = []

    def fake_command(command, timeout):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = hil_verify._ssh_command(args, "10.41.1.1", "true", fake_command)

    assert result["ok"] is True
    assert "UserKnownHostsFile=/dev/null" in commands[0]
    assert "GlobalKnownHostsFile=/dev/null" in commands[0]


def test_throughput_smoke_fails_when_iperf_server_is_missing():
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
    gate = hil_verify.NodeSpec("gate01", "gate", None, "10.41.1.1", "", True, "")
    point = hil_verify.NodeSpec("point01", "point", None, "10.41.2.1", "", True, "")
    commands = []
    checks = []

    def fake_command(command, timeout):
        commands.append(command)
        if "command -v iperf3" in command[-1]:
            return subprocess.CompletedProcess(command, 127, stdout="", stderr="")
        raise AssertionError("client should not run when server precheck fails")

    result = hil_verify._run_throughput_smoke(
        args,
        gate,
        point,
        fake_command,
        lambda _seconds: None,
        checks,
    )

    assert result["ok"] is False
    assert result["server"]["exit_code"] == 127
    assert "|| exit 127; nohup iperf3" in commands[0][-1]
    assert checks == [{"name": "throughput smoke", "ok": False, "detail": "exit=127"}]
