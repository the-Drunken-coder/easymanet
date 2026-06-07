"""JSON bridge used by the Electron desktop shell."""

import argparse
import json
import sys
from typing import Any, Sequence

from .server import _disks_payload, _state_payload, _validate_payload


def state_payload() -> dict[str, Any]:
    return _state_payload()


def disks_payload(*, include_all: bool = False) -> dict[str, Any]:
    return _disks_payload(include_all=include_all)


def validate_payload(*, config: str, node: str = "") -> dict[str, Any]:
    return _validate_payload({"config": config, "node": node})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m easymanet_desktop.bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("state")

    disks = subparsers.add_parser("disks")
    disks.add_argument("--all", action="store_true", dest="include_all")

    validate = subparsers.add_parser("validate")
    validate.add_argument("--config", required=True)
    validate.add_argument("--node", default="")

    args = parser.parse_args(argv)
    try:
        if args.command == "state":
            payload = state_payload()
        elif args.command == "disks":
            payload = disks_payload(include_all=args.include_all)
        elif args.command == "validate":
            payload = validate_payload(config=args.config, node=args.node)
        else:
            raise ValueError(f"Unsupported bridge command: {args.command}")
    except Exception as exc:  # noqa: BLE001 - converted into bridge JSON.
        payload = {"ok": False, "errors": [str(exc)]}

    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
