#!/usr/bin/env python3
"""Freeze the EasyMANET desktop bridge for Electron packaging."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
ELECTRON_ROOT = ROOT / "apps" / "desktop" / "electron"
ENTRYPOINT = ELECTRON_ROOT / "scripts" / "bridge-entry.py"
BUILD_ROOT = ROOT / "build" / "desktop-electron"
DIST_ROOT = BUILD_ROOT / "backend"
WORK_ROOT = BUILD_ROOT / "pyinstaller-work"
SPEC_ROOT = BUILD_ROOT / "pyinstaller-spec"
APP_NAME = "easymanet-bridge"
SOURCE_PATHS = (
    ROOT / "packages" / "core" / "src",
    ROOT / "apps" / "cli" / "src",
    ROOT / "apps" / "desktop" / "src",
)


def main() -> int:
    if importlib.util.find_spec("PyInstaller") is None:
        raise SystemExit(
            "PyInstaller is required. Install it with "
            "`python -m pip install pyinstaller` before packaging."
        )

    shutil.rmtree(BUILD_ROOT, ignore_errors=True)
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    SPEC_ROOT.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        APP_NAME,
        "--distpath",
        str(DIST_ROOT),
        "--workpath",
        str(WORK_ROOT),
        "--specpath",
        str(SPEC_ROOT),
        "--paths",
        str(SOURCE_PATHS[0]),
        "--paths",
        str(SOURCE_PATHS[1]),
        "--paths",
        str(SOURCE_PATHS[2]),
        "--collect-data",
        "easymanet_desktop",
        "--collect-submodules",
        "easymanet",
        "--collect-submodules",
        "easymanet_cli",
        "--collect-submodules",
        "easymanet_desktop",
        str(ENTRYPOINT),
    ]
    run(command)

    binary = DIST_ROOT / APP_NAME / executable_name()
    if not binary.exists():
        raise SystemExit(f"PyInstaller did not produce expected bridge binary: {binary}")
    print(f"Bundled bridge: {binary}")
    return 0


def executable_name() -> str:
    return f"{APP_NAME}.exe" if sys.platform == "win32" else APP_NAME


def run(command: list[str]) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
