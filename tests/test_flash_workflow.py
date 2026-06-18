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


def test_prepare_flash_workflow_downloads_missing_image(tmp_path, monkeypatch):
    image_path = tmp_path / "openmanet.img.gz"
    events = []

    monkeypatch.setattr(flash, "check_platform", lambda: None)
    monkeypatch.setattr(flash, "lookup_device", lambda _device: None)
    monkeypatch.setattr(flash, "assert_flash_allowed", lambda *_args, **_kwargs: None)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("prepare_flash_workflow must not run flash execution steps")

    monkeypatch.setattr(flash, "check_privileges", fail_if_called)
    monkeypatch.setattr(flash, "flash_image", fail_if_called)
    monkeypatch.setattr(flash, "inject", fail_if_called)
    monkeypatch.setattr(flash, "finish_flash", fail_if_called)
    monkeypatch.setattr(flash, "get_cached_image", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        flash,
        "check_latest_version",
        lambda _target: SimpleNamespace(
            version="images-v0.2.4",
            url="https://example.test/openmanet.img.gz",
            sha256="a" * 64,
        ),
    )

    def fake_download_image(target, version, url, sha256, force=False, emit=None):
        assert target == "rpi4-mm6108-spi"
        assert version == "images-v0.2.4"
        assert url == "https://example.test/openmanet.img.gz"
        assert sha256 == "a" * 64
        assert force is False
        image_path.write_bytes(b"firmware")
        if emit:
            emit({"type": "download_completed", "message": f"Saved: {image_path}", "path": str(image_path)})
        return image_path

    monkeypatch.setattr(flash, "download_image", fake_download_image)

    result = flash.prepare_flash_workflow(
        flash.FlashOptions(
            config="examples/three-node-field-mesh.yml",
            node="point01",
            device="/dev/disk4",
            yes=True,
        ),
        emit=events.append,
    )

    assert result.ok is True
    assert result.image["cached_path"] == str(image_path)
    assert result.plan["base_image"] == str(image_path)
    assert "download_completed" in [event.event_type for event in events]
    assert events[-1].event_type == "plan"


def test_prepare_flash_workflow_download_failure_is_classified(monkeypatch):
    monkeypatch.setattr(flash, "check_platform", lambda: None)
    monkeypatch.setattr(flash, "lookup_device", lambda _device: None)
    monkeypatch.setattr(flash, "assert_flash_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(flash, "get_cached_image", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        flash,
        "check_latest_version",
        lambda _target: SimpleNamespace(
            version="images-v0.2.4",
            url="https://example.test/openmanet.img.gz",
            sha256="a" * 64,
        ),
    )
    monkeypatch.setattr(
        flash,
        "download_image",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("network unavailable")),
    )

    result = flash.prepare_flash_workflow(
        flash.FlashOptions(
            config="examples/three-node-field-mesh.yml",
            node="point01",
            device="/dev/disk4",
            yes=True,
        )
    )

    assert result.ok is False
    assert result.code is flash.FlashErrorCode.IMAGE
    assert result.errors == ["Image download error: network unavailable"]
    assert result.events[-1].event_type == "error"


def test_prepare_flash_workflow_missing_local_base_image_is_classified(tmp_path, monkeypatch):
    missing_image = tmp_path / "missing-openmanet.img.gz"
    monkeypatch.setattr(flash, "check_platform", lambda: None)

    result = flash.prepare_flash_workflow(
        flash.FlashOptions(
            config="examples/three-node-field-mesh.yml",
            node="point01",
            device="/dev/disk4",
            base_image=str(missing_image),
            yes=True,
        )
    )

    assert result.ok is False
    assert result.code is flash.FlashErrorCode.IMAGE
    assert result.errors == [f"Base image not found: {missing_image}"]
    assert result.events[-1].event_type == "error"


def test_prepare_flash_workflow_exposes_effective_ssh_enabled(monkeypatch):
    monkeypatch.setattr(flash, "check_platform", lambda: None)
    monkeypatch.setattr(flash, "lookup_device", lambda _device: None)
    monkeypatch.setattr(flash, "assert_flash_allowed", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(flash, "get_cached_image", lambda *_args, **_kwargs: None)

    cases = [
        ("gate01", {}, True),
        ("point01", {}, False),
        ("point01", {"enable_ssh": True}, True),
        ("gate01", {"disable_ssh": True}, False),
    ]

    for node, overrides, expected in cases:
        result = flash.prepare_flash_workflow(
            flash.FlashOptions(
                config="examples/three-node-field-mesh.yml",
                node=node,
                device="/dev/disk4",
                dry_run=True,
                **overrides,
            )
        )

        assert result.ok is True
        assert result.plan["ssh_enabled"] is expected


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


def test_flash_workflow_unexpected_failure_is_internal(monkeypatch):
    monkeypatch.setattr(flash, "check_platform", lambda: None)

    def fail_resolve_fleet_config(_config):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        flash,
        "resolve_fleet_config",
        fail_resolve_fleet_config,
    )

    result = flash.run_flash_workflow(
        flash.FlashOptions(
            config="examples/three-node-field-mesh.yml",
            node="point01",
            device="/dev/disk4",
            dry_run=True,
        )
    )

    assert result.ok is False
    assert result.code is flash.FlashErrorCode.INTERNAL
    assert result.errors == ["Unexpected flash workflow error: RuntimeError: boom"]
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
    assert any("Boot payload error: boot partition missing" in error for error in result.errors)
    assert any("mounted, writable, and healthy" in warning for warning in result.warnings)


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
    inject_calls = []

    def fake_inject(**kwargs):
        inject_calls.append(kwargs)
        return [("/easymanet/provision.json", True)]

    monkeypatch.setattr(flash, "inject", fake_inject)
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
    assert inject_calls[0]["ssh_enabled"] is False
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
