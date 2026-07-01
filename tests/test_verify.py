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


def test_openwrt_sim_profile_runs_targeted_harness_tests(monkeypatch):
    verify = load_verify_module()
    commands = []

    def fake_run_step(step):
        commands.append(step.command)

    monkeypatch.setenv("EASYMANET_VERIFY_PYTHON", "/tmp/verify-python")
    monkeypatch.setattr(verify, "run_step", fake_run_step)

    assert verify.run_openwrt_sim() == 0

    assert commands == [
        [
            "/tmp/verify-python",
            "-m",
            "pytest",
            "-q",
            "tests/test_firstboot.py",
            "tests/test_provision_behavior.py",
            "tests/test_led_status.py",
        ]
    ]


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
    assert commands[2] == ["npm", "--prefix", "apps/desktop/electron", "ci"]
    assert commands[3][0] == runner_python
    assert commands[3][1] == "tools/release_smoke.py"
    assert "--skip-electron" not in commands[3]
    assert "--temp-root" in commands[3]


def test_artifact_profile_delegates_to_artifact_verifier(monkeypatch):
    verify = load_verify_module()
    commands = []

    def fake_run_step(step):
        commands.append(step.command)

    monkeypatch.setenv("EASYMANET_VERIFY_PYTHON", "/tmp/verify-python")
    monkeypatch.setattr(verify, "run_step", fake_run_step)

    args = [
        "--artifact",
        "dist/release/images/image.img.gz",
        "--release-manifest",
        "dist/release/images/easymanet-image-release.json",
    ]

    assert verify.run_artifact(args) == 0

    assert commands == [
        [
            "/tmp/verify-python",
            "tools/packaging/verify_artifacts.py",
            *args,
        ]
    ]


def test_hil_profile_delegates_to_hil_runner(monkeypatch):
    verify = load_verify_module()
    commands = []

    def fake_run_step(step):
        commands.append(step.command)

    monkeypatch.setenv("EASYMANET_VERIFY_PYTHON", "/tmp/verify-python")
    monkeypatch.setattr(verify, "run_step", fake_run_step)

    args = [
        "--config",
        "examples/three-node-field-mesh.yml",
        "--gate-node",
        "gate01",
        "--point-node",
        "point01",
        "--dry-run",
    ]

    assert verify.run_hil(args) == 0

    assert commands == [
        [
            "/tmp/verify-python",
            "tools/hil_verify.py",
            *args,
        ]
    ]


def test_profile_argument_separator_is_optional(monkeypatch):
    verify = load_verify_module()
    commands = []

    def fake_run_step(step):
        commands.append(step.command)

    monkeypatch.setenv("EASYMANET_VERIFY_PYTHON", "/tmp/verify-python")
    monkeypatch.setattr(verify, "run_step", fake_run_step)

    assert verify.main(["artifact", "--target", "rpi4-mm6108-spi"]) == 0

    assert commands == [
        [
            "/tmp/verify-python",
            "tools/packaging/verify_artifacts.py",
            "--target",
            "rpi4-mm6108-spi",
        ]
    ]
