#!/usr/bin/env python3
"""Run standard EasyMANET verification profiles."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "images" / "openmanet" / "provisioning" / "openwrt-overlay"


@dataclass(frozen=True)
class Step:
    name: str
    command: list[str]
    env: dict[str, str] | None = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("fast", "package"))
    args = parser.parse_args(argv)

    if args.profile == "fast":
        return run_fast()
    if args.profile == "package":
        return run_package()

    raise AssertionError(f"unhandled profile: {args.profile}")


def run_fast() -> int:
    python = verification_python()
    steps = fast_steps(python)
    run_steps(steps)
    print("Verification profile 'fast' passed.")
    return 0


def run_package() -> int:
    package_python = package_venv_python()
    with tempfile.TemporaryDirectory(prefix="easymanet-verify-package-") as tmp:
        temp_root = Path(tmp)
        runner_venv = temp_root / "package-runner"
        release_smoke_root = temp_root / "release-smoke"
        steps = package_steps(package_python, runner_venv, release_smoke_root)
        run_steps(steps)
    print("Verification profile 'package' passed.")
    return 0


def verification_python() -> str:
    return os.environ.get("EASYMANET_VERIFY_PYTHON", sys.executable)


def package_venv_python() -> str:
    requested = os.environ.get("EASYMANET_VERIFY_PACKAGE_PYTHON")
    if requested:
        return requested

    python_311 = shutil.which("python3.11")
    if python_311:
        return python_311

    return sys.executable


def fast_steps(python: str) -> list[Step]:
    electron_env = {"EASYMANET_PYTHON": python}
    steps = [
        Step("Python tests", [python, "-m", "pytest", "-q"]),
    ]
    steps.extend(
        Step("Overlay shell syntax", ["sh", "-n", str(path)])
        for path in overlay_shell_files()
    )
    steps.extend(
        [
            Step(
                "Electron desktop check",
                ["npm", "--prefix", "apps/desktop/electron", "run", "check"],
                electron_env,
            ),
            Step(
                "Overlay packaging check",
                [python, "tools/packaging/verify_overlay_packaging.py"],
            ),
            Step("Whitespace diff check", ["git", "diff", "--check"]),
        ]
    )
    return steps


def package_steps(package_python: str, runner_venv: Path, release_smoke_root: Path) -> list[Step]:
    runner_python = venv_python(runner_venv)
    return [
        Step("Create package verification venv", [package_python, "-m", "venv", str(runner_venv)]),
        Step(
            "Install package build tooling",
            [
                str(runner_python),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "pip",
                "setuptools>=68",
                "wheel",
            ],
        ),
        Step(
            "Installed-wheel smoke",
            [
                str(runner_python),
                "tools/release_smoke.py",
                "--skip-electron",
                "--temp-root",
                str(release_smoke_root),
            ],
        ),
    ]


def overlay_shell_files() -> list[Path]:
    if not OVERLAY.is_dir():
        raise SystemExit(f"Overlay directory not found: {OVERLAY}")

    return [
        path.relative_to(ROOT)
        for path in sorted(OVERLAY.rglob("*"))
        if is_overlay_shell_file(path)
    ]


def is_overlay_shell_file(path: Path) -> bool:
    if not path.is_file():
        return False
    rel = path.relative_to(OVERLAY).as_posix()
    return path.suffix == ".sh" or rel.startswith("etc/init.d/") or rel.startswith("etc/uci-defaults/")


def venv_python(venv_dir: Path) -> Path:
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    exe = "python.exe" if os.name == "nt" else "python"
    return venv_dir / bin_dir / exe


def run_steps(steps: list[Step]) -> None:
    for step in steps:
        run_step(step)


def run_step(step: Step) -> None:
    print(f"\n== {step.name} ==", flush=True)
    print("+ " + " ".join(step.command), flush=True)

    env = os.environ.copy()
    if step.env:
        env.update(step.env)

    try:
        result = subprocess.run(
            step.command,
            cwd=ROOT,
            env=env,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"Command not found while running {step.name}: {exc.filename}") from exc

    if result.returncode != 0:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
