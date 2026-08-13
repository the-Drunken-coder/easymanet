"""Packaging tests for installed overlay artifacts."""

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OVERLAY_INSTALL_ROOT = Path("share/easymanet/images/openmanet/provisioning/openwrt-overlay")
EXECUTABLE_OVERLAY_FILES = [
    "etc/init.d/easymanet-boot-report",
    "etc/init.d/easymanet-display-status",
    "etc/init.d/easymanet-led-status",
    "etc/init.d/easymanet-management-lan",
    "etc/init.d/easymanet-status-cache",
    "etc/uci-defaults/94-easymanet-status-cache",
    "etc/uci-defaults/95-easymanet-display-status",
    "etc/uci-defaults/96-easymanet-led-status",
    "etc/uci-defaults/97-easymanet-management-lan",
    "etc/uci-defaults/98-easymanet-boot-report",
    "etc/uci-defaults/99-easymanet",
    "usr/lib/easymanet/api.sh",
    "usr/lib/easymanet/boot-report.sh",
    "usr/lib/easymanet/display-status.sh",
    "usr/lib/easymanet/led-status.sh",
    "usr/lib/easymanet/network.sh",
    "usr/lib/easymanet/provision.sh",
    "usr/lib/easymanet/status-cache.sh",
    "www/easymanet-api/v1/identity",
    "www/easymanet-api/v1/neighbors",
    "www/easymanet-api/v1/status",
    "www/easymanet-api/v1/topology",
]
INTERNAL_OVERLAY_FILES = [
    "usr/lib/easymanet/api-lib.sh",
    "usr/lib/easymanet/provision-lib.sh",
    "usr/lib/easymanet/provision-runtime.sh",
    "usr/lib/easymanet/status-lib.sh",
]
PACKAGING_COMMAND_TIMEOUT = 180


def _load_release_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "release_smoke", ROOT / "tools" / "release_smoke.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run_packaging_command(args, env):
    try:
        return subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            env=env,
            timeout=PACKAGING_COMMAND_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        pytest.fail(
            f"packaging command timed out after {e.timeout}s: {' '.join(args)}\n"
            f"stdout:\n{e.output or ''}\n"
            f"stderr:\n{e.stderr or ''}"
        )


def test_installed_wheel_preserves_overlay_executable_modes(tmp_path):
    wheel_dir = tmp_path / "wheelhouse"
    install_dir = tmp_path / "install"
    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

    release_smoke = _load_release_smoke_module()
    wheel = release_smoke.build_wheel(ROOT, wheel_dir)

    _run_packaging_command(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(install_dir),
            str(wheel),
        ],
        env=env,
    )

    for rel_path in EXECUTABLE_OVERLAY_FILES:
        installed = install_dir / OVERLAY_INSTALL_ROOT / rel_path
        assert installed.exists(), rel_path
        assert installed.stat().st_mode & stat.S_IXUSR, rel_path

    for rel_path in INTERNAL_OVERLAY_FILES:
        installed = install_dir / OVERLAY_INSTALL_ROOT / rel_path
        assert installed.exists(), rel_path


def test_release_smoke_installs_wheel_in_temp_venv(tmp_path):
    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

    result = _run_packaging_command(
        [
            sys.executable,
            str(ROOT / "tools" / "release_smoke.py"),
            "--temp-root",
            str(tmp_path / "release-smoke"),
            "--skip-electron",
        ],
        env=env,
    )

    assert "Release smoke passed." in result.stdout


def test_release_smoke_build_command_uses_isolated_build_defaults(tmp_path):
    release_smoke = _load_release_smoke_module()
    wheelhouse = tmp_path / "wheelhouse"

    command = release_smoke.build_wheel_command(
        "/usr/bin/python3", wheelhouse, ROOT
    )

    assert command == [
        "/usr/bin/python3",
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(wheelhouse),
        str(ROOT),
    ]
    assert "--no-build-isolation" not in command


def test_release_smoke_surfaces_packaging_command_failure(monkeypatch):
    release_smoke = _load_release_smoke_module()

    def fake_subprocess_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=23,
            stdout="",
            stderr="build backend unavailable",
        )

    monkeypatch.setattr(release_smoke.subprocess, "run", fake_subprocess_run)

    with pytest.raises(SystemExit) as exc_info:
        release_smoke.run(["python", "-m", "pip", "wheel"])

    assert exc_info.value.code == 23


def test_release_smoke_builds_from_temporary_tracked_source(tmp_path, monkeypatch):
    release_smoke = _load_release_smoke_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "pyproject.toml").write_text(
        '[project]\nname = "easymanet"\nversion = "0.2.4"\n'
    )
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    subprocess.run(["git", "add", "pyproject.toml"], cwd=repo_root, check=True)
    wheelhouse = tmp_path / "wheelhouse"
    wheel = wheelhouse / "easymanet-0.2.4-py3-none-any.whl"
    source_paths = []

    def fake_run(command, **kwargs):
        del kwargs
        source_paths.append(Path(command[-1]))
        assert source_paths[-1] != repo_root
        assert (source_paths[-1] / "pyproject.toml").is_file()
        wheelhouse.mkdir(parents=True, exist_ok=True)
        wheel.touch()

    monkeypatch.setattr(release_smoke, "run", fake_run)

    assert release_smoke.build_wheel(repo_root, tmp_path) == wheel
    assert not source_paths[0].exists()


def test_release_smoke_preserves_existing_source_build_content(tmp_path, monkeypatch):
    release_smoke = _load_release_smoke_module()
    repo_root = tmp_path / "repo"
    build_dir = repo_root / "build"
    build_dir.mkdir(parents=True)
    keep = build_dir / "keep.txt"
    keep.write_text("operator content\n")
    (repo_root / "pyproject.toml").write_text(
        '[project]\nname = "easymanet"\nversion = "0.2.4"\n'
    )
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    subprocess.run(["git", "add", "pyproject.toml"], cwd=repo_root, check=True)

    def fake_run(*_args, **_kwargs):
        raise SystemExit(23)

    monkeypatch.setattr(release_smoke, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        release_smoke.build_wheel(repo_root, tmp_path)

    assert exc_info.value.code == 23
    assert keep.read_text() == "operator content\n"


def test_release_smoke_run_passes_timeout_to_subprocess(monkeypatch):
    release_smoke = _load_release_smoke_module()
    captured = {}

    def fake_run(*args, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(release_smoke.subprocess, "run", fake_run)

    release_smoke.run(["echo", "ok"], timeout=7)

    assert captured["timeout"] == 7


def test_release_smoke_wheel_glob_uses_normalized_project_name(tmp_path):
    release_smoke = _load_release_smoke_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "easymanet-images"\nversion = "0.2.0"\n'
    )

    assert release_smoke.wheel_glob_pattern(repo) == "easymanet_images-*.whl"
