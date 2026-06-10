"""JSON bridge used by the Electron desktop shell."""

import argparse
from contextlib import redirect_stderr, redirect_stdout
import json
import os
import shlex
import sys
from io import StringIO
from typing import Any, Sequence

import typer

from easymanet.download import check_latest_version, get_cached_image
from easymanet.manifest import load_manifest
from easymanet.render import render_dict
from easymanet.validate import validate
from easymanet.workspace import resolve_fleet_config
from easymanet_cli.flash import run_flash

from .server import _disks_payload, _state_payload, _validate_payload


PRIVILEGE_ERROR_MARKER = "Write access to the target block device is required."


def state_payload() -> dict[str, Any]:
    return _state_payload()


def disks_payload(*, include_all: bool = False) -> dict[str, Any]:
    return _disks_payload(include_all=include_all)


def validate_payload(*, config: str, node: str = "") -> dict[str, Any]:
    return _validate_payload({"config": config, "node": node})


def flash_plan_payload(
    *,
    config: str,
    node: str,
    device: str,
    base_image: str | None = None,
    image_sha256: str | None = None,
    enable_ssh: bool = False,
    disable_ssh: bool = False,
) -> dict[str, Any]:
    payload = _capture_flash(
        config=config,
        node=node,
        device=device,
        base_image=base_image,
        image_sha256=image_sha256,
        dry_run=True,
        yes=False,
        enable_ssh=enable_ssh,
        disable_ssh=disable_ssh,
    )
    payload["image"] = _safe_flash_image_details(config=config, node=node)
    return payload


def flash_payload(
    *,
    config: str,
    node: str,
    device: str,
    yes: bool,
    base_image: str | None = None,
    image_sha256: str | None = None,
    enable_ssh: bool = False,
    disable_ssh: bool = False,
) -> dict[str, Any]:
    if not yes:
        return {"ok": False, "errors": ["--yes is required for desktop flash execution"]}

    payload = _capture_flash(
        config=config,
        node=node,
        device=device,
        base_image=base_image,
        image_sha256=image_sha256,
        dry_run=False,
        yes=True,
        enable_ssh=enable_ssh,
        disable_ssh=disable_ssh,
    )
    details = _safe_flash_image_details(config=config, node=node)
    payload["image"] = details
    if not payload["ok"] and _is_privilege_error(payload.get("output", "")):
        payload["sudo_command"] = _sudo_flash_command(
            config=config,
            node=node,
            device=device,
            enable_ssh=enable_ssh,
            disable_ssh=disable_ssh,
            image=details,
        )
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m easymanet_desktop.bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("state")

    disks = subparsers.add_parser("disks")
    disks.add_argument("--all", action="store_true", dest="include_all")

    validate = subparsers.add_parser("validate")
    validate.add_argument("--config", required=True)
    validate.add_argument("--node", default="")

    flash_plan = subparsers.add_parser("flash-plan")
    _add_flash_args(flash_plan, include_yes=False)

    flash = subparsers.add_parser("flash")
    _add_flash_args(flash, include_yes=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "state":
            payload = state_payload()
        elif args.command == "disks":
            payload = disks_payload(include_all=args.include_all)
        elif args.command == "validate":
            payload = validate_payload(config=args.config, node=args.node)
        elif args.command == "flash-plan":
            payload = flash_plan_payload(
                config=args.config,
                node=args.node,
                device=args.device,
                base_image=args.base_image,
                image_sha256=args.image_sha256,
                enable_ssh=args.enable_ssh,
                disable_ssh=args.disable_ssh,
            )
        elif args.command == "flash":
            payload = flash_payload(
                config=args.config,
                node=args.node,
                device=args.device,
                yes=args.yes,
                base_image=args.base_image,
                image_sha256=args.image_sha256,
                enable_ssh=args.enable_ssh,
                disable_ssh=args.disable_ssh,
            )
        else:
            raise ValueError(f"Unsupported bridge command: {args.command}")
    except Exception as exc:  # noqa: BLE001 - converted into bridge JSON.
        payload = {"ok": False, "errors": [str(exc)]}

    print(json.dumps(payload))
    return 0


def _add_flash_args(parser: argparse.ArgumentParser, *, include_yes: bool) -> None:
    parser.add_argument("--config", required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--base-image", default=None)
    parser.add_argument("--image-sha256", default=None)
    parser.add_argument("--enable-ssh", action="store_true")
    parser.add_argument("--disable-ssh", action="store_true")
    if include_yes:
        parser.add_argument("--yes", action="store_true")


def _capture_flash(**kwargs: Any) -> dict[str, Any]:
    stdout = StringIO()
    stderr = StringIO()
    exit_code = 0
    previous_skip_update = os.environ.get("EASYMANET_SKIP_UPDATE_CHECK")
    os.environ.setdefault("EASYMANET_SKIP_UPDATE_CHECK", "1")
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            run_flash(**kwargs)
        except typer.Exit as exc:
            exit_code = int(exc.exit_code or 0)
        except SystemExit as exc:
            exit_code = _system_exit_code(exc)
        except Exception as exc:  # noqa: BLE001 - converted into bridge JSON.
            exit_code = 1
            print(str(exc), file=sys.stderr)
        finally:
            if previous_skip_update is None:
                os.environ.pop("EASYMANET_SKIP_UPDATE_CHECK", None)
            else:
                os.environ["EASYMANET_SKIP_UPDATE_CHECK"] = previous_skip_update

    output = _combined_output(stdout.getvalue(), stderr.getvalue())
    ok = exit_code == 0
    return {
        "ok": ok,
        "exit_code": exit_code,
        "errors": [] if ok else [_error_summary(output, exit_code)],
        "warnings": _warning_lines(output),
        "output": output,
        "sudo_command": "",
    }


def _system_exit_code(exc: SystemExit) -> int:
    code = exc.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1


def _combined_output(stdout: str, stderr: str) -> str:
    parts = [part.strip() for part in (stdout, stderr) if part.strip()]
    return "\n".join(parts)


def _error_summary(output: str, exit_code: int) -> str:
    for line in reversed(output.splitlines()):
        text = line.strip()
        if text:
            return text
    return f"Flash command exited with code {exit_code}"


def _warning_lines(output: str) -> list[str]:
    warnings = []
    for line in output.splitlines():
        text = line.strip()
        if text.startswith("Warning:") or text.startswith("Flash safety:") or " Flash safety:" in text:
            warnings.append(text)
    return warnings


def _flash_image_details(*, config: str, node: str) -> dict[str, Any]:
    config_path = resolve_fleet_config(config)
    manifest = load_manifest(str(config_path))
    result = validate(manifest, node_name=node)
    if result.errors:
        return {"config_path": str(config_path), "errors": result.errors}

    resolved = render_dict(manifest, node)
    target = str(resolved["node"]["target"])
    details: dict[str, Any] = {
        "config_path": str(config_path),
        "node": node,
        "target": target,
        "version": "",
        "url": "",
        "sha256": "",
        "cached_path": "",
    }

    latest = _quiet_call(check_latest_version, target)
    if latest:
        details.update(
            {
                "version": latest.version,
                "url": latest.url,
                "sha256": latest.sha256 or "",
            }
        )
        if latest.sha256:
            cached = _quiet_call(get_cached_image, target, latest.sha256, latest.url)
            details["cached_path"] = str(cached) if cached else ""
    return details


def _safe_flash_image_details(*, config: str, node: str) -> dict[str, Any]:
    try:
        return _flash_image_details(config=config, node=node)
    except Exception as exc:  # noqa: BLE001 - best-effort metadata for JSON bridge.
        return {"errors": [str(exc)]}


def _quiet_call(func: Any, *args: Any) -> Any:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        return func(*args)


def _is_privilege_error(output: str) -> bool:
    return PRIVILEGE_ERROR_MARKER in output


def _sudo_flash_command(
    *,
    config: str,
    node: str,
    device: str,
    enable_ssh: bool,
    disable_ssh: bool,
    image: dict[str, Any],
) -> str:
    args = ["sudo", *_bridge_command(), "flash", "--config", config, "--node", node, "--device", device, "--yes"]
    if enable_ssh:
        args.append("--enable-ssh")
    if disable_ssh:
        args.append("--disable-ssh")

    cached_path = str(image.get("cached_path") or "")
    sha256 = str(image.get("sha256") or "")
    if cached_path and sha256:
        args.extend(["--base-image", cached_path, "--image-sha256", sha256])

    return " ".join(shlex.quote(part) for part in args)


def _bridge_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "easymanet_desktop.bridge"]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
