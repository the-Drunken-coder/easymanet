import importlib.util
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFY_PATH = ROOT / "tools" / "verify.py"


def load_verify_module():
    spec = importlib.util.spec_from_file_location("verify", VERIFY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fast_profile_runs_existing_fast_checks(monkeypatch):
    verify = load_verify_module()
    commands = []
    envs = []

    def fake_run_step(step):
        commands.append(step.command)
        envs.append(step.env or {})

    monkeypatch.delenv("EASYMANET_PYTHON", raising=False)
    monkeypatch.setenv("EASYMANET_VERIFY_PYTHON", "/tmp/verify-python")
    monkeypatch.setattr(verify, "run_step", fake_run_step)

    assert verify.run_fast() == 0

    assert commands[0] == ["/tmp/verify-python", "-m", "pytest", "-q"]
    assert ["/tmp/verify-python", "-m", "pytest", "-q"] in commands
    assert ["sh", "-n", "images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/provision.sh"] in commands
    assert ["npm", "--prefix", "apps/desktop/electron", "run", "check"] in commands
    electron_index = commands.index(["npm", "--prefix", "apps/desktop/electron", "run", "check"])
    assert envs[electron_index]["EASYMANET_PYTHON"] == "/tmp/verify-python"
    assert ["/tmp/verify-python", "tools/packaging/verify_overlay_packaging.py"] in commands
    assert commands[-1] == ["git", "diff", "--check"]


def test_package_profile_bootstraps_release_smoke_in_temp_venv(monkeypatch):
    verify = load_verify_module()
    commands = []

    def fake_run_step(step):
        commands.append(step.command)

    monkeypatch.setenv("EASYMANET_VERIFY_PACKAGE_PYTHON", "/usr/bin/python3.11")
    monkeypatch.setattr(verify, "run_step", fake_run_step)

    assert verify.run_package() == 0

    assert commands[0][0:3] == ["/usr/bin/python3.11", "-m", "venv"]
    runner_python = commands[1][0]
    assert runner_python.endswith(os.path.join("package-runner", "bin", "python"))
    assert commands[1][1:] == [
        "-m",
        "pip",
        "install",
        "--upgrade",
        "pip",
        "setuptools>=68",
        "wheel",
    ]
    assert commands[2][0] == runner_python
    assert commands[2][1:3] == ["tools/release_smoke.py", "--skip-electron"]
    assert "--temp-root" in commands[2]
