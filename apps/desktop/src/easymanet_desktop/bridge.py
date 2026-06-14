"""JSON bridge used by the Electron desktop shell."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from typing import Any, Callable, Sequence

from easymanet.flash import (
    FlashErrorCode,
    FlashEvent,
    FlashOptions,
    flash_image_details,
    run_flash_workflow,
)
from easymanet.download import download_image

from .payloads import (
    disks_payload,
    resolve_config_payload,
    state_payload,
    validate_payload as shared_validate_payload,
)
from .mesh import mesh_discover_payload


def validate_payload(*, config: str, node: str = "") -> dict[str, Any]:
    return shared_validate_payload({"config": config, "node": node})


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
    result = run_flash_workflow(
        FlashOptions(
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
    )
    payload = result.to_dict(include_events=True)
    payload["image"] = _best_image_details(payload.get("image", {}), config=config, node=node)
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
    emit: Callable[[FlashEvent], None] | None = None,
) -> dict[str, Any]:
    result = run_flash_workflow(
        FlashOptions(
            config=config,
            node=node,
            device=device,
            base_image=base_image,
            image_sha256=image_sha256,
            dry_run=False,
            yes=yes,
            enable_ssh=enable_ssh,
            disable_ssh=disable_ssh,
        ),
        emit=emit,
    )
    payload = result.to_dict(include_events=emit is None)
    payload["image"] = _best_image_details(payload.get("image", {}), config=config, node=node)
    if not payload["ok"] and payload.get("code") == FlashErrorCode.PRIVILEGE_REQUIRED.value:
        payload["sudo_command"] = _sudo_flash_command(
            config=config,
            node=node,
            device=device,
            enable_ssh=enable_ssh,
            disable_ssh=disable_ssh,
            image=payload["image"],
        )
    return payload


def ensure_image_payload(
    *,
    config: str,
    node: str,
    emit: Callable[[FlashEvent], None] | None = None,
) -> dict[str, Any]:
    details = flash_image_details(config=config, node=node)
    if details.get("errors"):
        return {"ok": False, "errors": details["errors"], "image": details}

    cached_path = str(details.get("cached_path") or "")
    if cached_path:
        return {"ok": True, "image": {**details, "path": cached_path}}

    target = str(details.get("target") or "")
    version = str(details.get("version") or "latest")
    url = str(details.get("url") or "")
    sha256 = str(details.get("sha256") or "")
    if not target or not url or not sha256:
        return {
            "ok": False,
            "errors": ["No downloadable image with SHA-256 is available for this target"],
            "image": details,
        }

    path = download_image(
        target,
        version,
        url,
        sha256,
        emit=lambda event: _emit_download_event(event, emit),
    )
    return {"ok": True, "image": {**details, "path": str(path), "cached_path": str(path)}}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m easymanet_desktop.bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("state")

    disks = subparsers.add_parser("disks")
    disks.add_argument("--all", action="store_true", dest="include_all")

    validate = subparsers.add_parser("validate")
    validate.add_argument("--config", required=True)
    validate.add_argument("--node", default="")

    resolve_config = subparsers.add_parser("resolve-config")
    resolve_config.add_argument("--config", required=True)

    mesh_discover = subparsers.add_parser("mesh-discover")
    mesh_discover.add_argument("--config", default="")
    mesh_discover.add_argument("--scan-subnet", action="store_true")

    flash_plan = subparsers.add_parser("flash-plan")
    _add_flash_args(flash_plan, include_yes=False)

    ensure_image = subparsers.add_parser("ensure-image")
    ensure_image.add_argument("--config", required=True)
    ensure_image.add_argument("--node", required=True)

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
        elif args.command == "resolve-config":
            payload = resolve_config_payload(config=args.config)
        elif args.command == "mesh-discover":
            payload = mesh_discover_payload(
                {
                    "config": args.config,
                    "scan_subnet": args.scan_subnet,
                }
            )
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
        elif args.command == "ensure-image":
            payload = ensure_image_payload(
                config=args.config,
                node=args.node,
                emit=_print_bridge_event,
            )
            print(json.dumps({"type": "result", **payload}), flush=True)
            return 0
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
                emit=_print_bridge_event,
            )
            print(json.dumps({"type": "result", **payload}), flush=True)
            return 0
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


def _print_bridge_event(event: FlashEvent) -> None:
    print(json.dumps(event.to_dict()), flush=True)


def _emit_download_event(
    event: dict[str, Any],
    emit: Callable[[FlashEvent], None] | None,
) -> None:
    if not emit:
        return
    event_type = str(event.get("type") or "download")
    message = str(event.get("message") or "")
    data = {key: value for key, value in event.items() if key not in {"type", "message"}}
    emit(FlashEvent(event_type=event_type, message=message, data=data))


def _best_image_details(
    image: dict[str, Any],
    *,
    config: str,
    node: str,
) -> dict[str, Any]:
    details = _safe_flash_image_details(config=config, node=node)
    image_path = str(image.get("path") or "")
    default_cached_path = str(details.get("cached_path") or "")
    uses_default_image = (
        not image_path
        or image_path.startswith("<")
        or (default_cached_path and image_path == default_cached_path)
    )
    merged = dict(details)
    if uses_default_image:
        merged.update({key: value for key, value in image.items() if value not in ("", None)})
    else:
        merged.update(image)
    path = str(merged.get("path") or "")
    if (
        path
        and not path.startswith("<")
        and ("path" in image or not merged.get("cached_path"))
    ):
        merged["cached_path"] = merged["path"]
    return merged


def _safe_flash_image_details(*, config: str, node: str) -> dict[str, Any]:
    try:
        return flash_image_details(config=config, node=node)
    except Exception as exc:  # noqa: BLE001 - best-effort metadata for JSON bridge.
        return {"errors": [str(exc)]}


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

    cached_path = str(image.get("cached_path") or image.get("path") or "")
    sha256 = str(image.get("sha256") or "")
    if cached_path:
        args.extend(["--base-image", cached_path])
        if sha256:
            args.extend(["--image-sha256", sha256])

    return " ".join(shlex.quote(part) for part in args)


def _bridge_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "easymanet_desktop.bridge"]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
