#!/usr/bin/env python3
"""Ensure provisioning/openwrt-overlay files are listed in pyproject.toml data-files."""

from pathlib import Path
import sys

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "provisioning" / "openwrt-overlay"
PYPROJECT_PATH = ROOT / "pyproject.toml"


def _packaged_overlay_paths() -> set[str]:
    with PYPROJECT_PATH.open("rb") as f:
        data = tomllib.load(f)
    packaged: set[str] = set()
    overlay_prefix = "provisioning/openwrt-overlay/"
    for filenames in data["tool"]["setuptools"]["data-files"].values():
        for name in filenames:
            if name.startswith(overlay_prefix):
                packaged.add(name)
    return packaged


def main() -> int:
    packaged = _packaged_overlay_paths()
    if not OVERLAY.is_dir():
        print(f"Overlay directory not found: {OVERLAY}", file=sys.stderr)
        return 1

    overlay_files = sorted(
        path.relative_to(ROOT).as_posix()
        for path in OVERLAY.rglob("*")
        if path.is_file()
    )
    missing = [rel for rel in overlay_files if rel not in packaged]

    if missing:
        print(
            "Overlay files missing from pyproject.toml [tool.setuptools.data-files]:",
            file=sys.stderr,
        )
        for rel in missing:
            print(f"  {rel}", file=sys.stderr)
        return 1

    print(f"All {len(overlay_files)} overlay files are listed in pyproject.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
