from pathlib import Path
from types import SimpleNamespace

import easymanet.flash as flash
from easymanet.inject import InjectError
from easymanet.privileges import PrivilegeError


def _options(tmp_path, **overrides):
    image = tmp_path / "openmanet.img.gz"
    image.write_bytes(b"firmware")
    values = {
        "config": "examples/three-node-field-mesh.yml",
        "node": "point01",
        "device": "/dev/disk4",
        "base_image": str(image),
        "dry_run": False,
        "yes": True,
    }
    values.update(overrides)
    return flash.FlashOptions(**values)


def test_flash_workflow_dry_run_emits_plan_before_complete(monkeypatch):
    events = []
    monkeypatch.setattr(flash, "check_platform", lambda: None)
    monkeypatch.setattr(flash, "lookup_device", lambda _device: None)
    monkeypatch.setattr(flash, "assert_flash_allowed", lambda *_args, **_kwargs: None)

    result = flash.run_flash_workflow(
        flash.FlashOptions(
            config="examples/three-node-field-mesh.yml",
            node="point01",
            device="/dev/disk4",
            dry_run=True,
        ),
        emit=events.append,
    )

    assert result.ok is True
    assert [event.event_type for event in events][-2:] == ["plan", "complete"]
    assert result.plan["boot_payload"] == "/easymanet/provision.json"


def test_flash_workflow_validation_failure_returns_structured_errors(tmp_path, monkeypatch):
    config = tmp_path / "bad.yml"
    config.write_text("version: 1\nnodes: {}\n")
    monkeypatch.setattr(flash, "check_platform", lambda: None)

    result = flash.run_flash_workflow(
        flash.FlashOptions(
            config=str(config),
            node="point01",
            device="/dev/disk4",
            dry_run=True,
        )
    )

    assert result.ok is False
    assert result.code is flash.FlashErrorCode.VALIDATION
    assert any("at least one node" in error for error in result.errors)


def test_flash_workflow_dry_run_keeps_disk_safety_as_warning(monkeypatch):
    monkeypatch.setattr(flash, "check_platform", lambda: None)
    monkeypatch.setattr(flash, "lookup_device", lambda _device: None)
    monkeypatch.setattr(
        flash,
        "assert_flash_allowed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("too large")),
    )

    result = flash.run_flash_workflow(
        flash.FlashOptions(
            config="examples/three-node-field-mesh.yml",
            node="point01",
            device="/dev/disk4",
            dry_run=True,
        )
    )

    assert result.ok is True
    assert "Flash safety: too large" in result.warnings


def test_flash_workflow_privilege_error_is_classified(tmp_path, monkeypatch):
    monkeypatch.setattr(flash, "check_platform", lambda: None)
    monkeypatch.setattr(flash, "lookup_device", lambda _device: None)
    monkeypatch.setattr(flash, "assert_flash_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        flash,
        "check_privileges",
        lambda _device: (_ for _ in ()).throw(PrivilegeError("write access required")),
    )

    result = flash.run_flash_workflow(_options(tmp_path))

    assert result.ok is False
    assert result.code is flash.FlashErrorCode.PRIVILEGE_REQUIRED
    assert result.errors == ["write access required"]


def test_flash_workflow_download_failure_is_classified(monkeypatch):
    def fail_download(*_args, **_kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(flash, "check_platform", lambda: None)
    monkeypatch.setattr(
        flash,
        "check_latest_version",
        lambda _target: SimpleNamespace(
            version="1.6.5",
            url="https://example.test/openmanet.img.gz",
            sha256="a" * 64,
        ),
    )
    monkeypatch.setattr(flash, "download_image", fail_download)

    result = flash.run_flash_workflow(
        flash.FlashOptions(
            config="examples/three-node-field-mesh.yml",
            node="point01",
            device="/dev/disk4",
            download=True,
            yes=True,
        )
    )

    assert result.ok is False
    assert result.code is flash.FlashErrorCode.IMAGE
    assert result.errors == ["Image download error: network unavailable"]
    assert result.events[-1].event_type == "error"


def test_flash_workflow_inject_failure_reports_partial_write(tmp_path, monkeypatch):
    monkeypatch.setattr(flash, "check_platform", lambda: None)
    monkeypatch.setattr(flash, "lookup_device", lambda _device: None)
    monkeypatch.setattr(flash, "assert_flash_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(flash, "check_privileges", lambda _device: None)
    monkeypatch.setattr(flash, "flash_image", lambda **_kwargs: None)
    monkeypatch.setattr(
        flash,
        "inject",
        lambda **_kwargs: (_ for _ in ()).throw(InjectError("boot partition missing")),
    )

    result = flash.run_flash_workflow(_options(tmp_path))

    assert result.ok is False
    assert result.code is flash.FlashErrorCode.INJECT
    assert "Boot payload error: boot partition missing" in result.errors
    assert any("Image was written" in warning for warning in result.warnings)


def test_flash_workflow_success_runs_steps_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(flash, "check_platform", lambda: None)
    monkeypatch.setattr(flash, "lookup_device", lambda _device: None)
    monkeypatch.setattr(flash, "assert_flash_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(flash, "check_privileges", lambda _device: None)

    def fake_flash_image(**kwargs):
        kwargs["emit"]({"type": "write_started", "message": "Writing image"})
        kwargs["emit"]({"type": "write_completed", "message": "Done writing."})

    def fake_finish_flash(_device, eject=True, emit=None):
        assert eject is True
        emit({"type": "safe_to_remove", "message": "Safe to remove."})
        return True

    monkeypatch.setattr(flash, "flash_image", fake_flash_image)
    monkeypatch.setattr(flash, "inject", lambda **_kwargs: [("/easymanet/provision.json", True)])
    monkeypatch.setattr(flash, "finish_flash", fake_finish_flash)
    events = []

    result = flash.run_flash_workflow(_options(tmp_path), emit=events.append)

    assert result.ok is True
    assert result.code is flash.FlashErrorCode.OK
    assert [event.event_type for event in events if event.event_type != "warning"] == [
        "plan",
        "write_started",
        "write_completed",
        "inject_started",
        "inject_result",
        "safe_to_remove",
        "complete",
    ]
    assert events[0].event_type == "warning"
    assert result.inject_results == [{"path": "/easymanet/provision.json", "ok": True}]


def test_flash_workflow_finish_failure_is_structured(tmp_path, monkeypatch):
    monkeypatch.setattr(flash, "check_platform", lambda: None)
    monkeypatch.setattr(flash, "lookup_device", lambda _device: None)
    monkeypatch.setattr(flash, "assert_flash_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(flash, "check_privileges", lambda _device: None)
    monkeypatch.setattr(flash, "flash_image", lambda **_kwargs: None)
    monkeypatch.setattr(flash, "inject", lambda **_kwargs: [("/easymanet/provision.json", True)])

    def fake_finish_flash(_device, eject=True, emit=None):
        assert eject is True
        emit({"type": "eject_failed", "message": "eject failed", "level": "warning"})
        return False

    monkeypatch.setattr(flash, "finish_flash", fake_finish_flash)

    result = flash.run_flash_workflow(_options(tmp_path))

    assert result.ok is False
    assert result.code is flash.FlashErrorCode.FINISH
    assert result.errors == [
        "Eject failed; sync and eject the disk manually before removing it."
    ]
    assert result.inject_results == [{"path": "/easymanet/provision.json", "ok": True}]
