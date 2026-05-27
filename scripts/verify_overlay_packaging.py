#!/usr/bin/env python3
"""Ensure provisioning/openwrt-overlay files are listed in pyproject.toml data-files."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "provisioning" / "openwrt-overlay"
PYPROJECT = (ROOT / "pyproject.toml").read_text()


def main() -> int:
    missing = []
    for path in sorted(OVERLAY.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel not in PYPROJECT:
            missing.append(rel)

    if missing:
        print("Overlay files missing from pyproject.toml [tool.setuptools.data-files]:", file=sys.stderr)
        for rel in missing:
            print(f"  {rel}", file=sys.stderr)
        return 1

    print(f"All {len(list(OVERLAY.rglob('*')))} overlay paths are referenced in pyproject.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
