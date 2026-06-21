import json
import zipfile
from pathlib import Path

from easymanet import support_bundle
from easymanet.workspace import WORKSPACE_ENV, ensure_workspace


FLEET = """\
version: 1
mesh:
  id: field
  password: mesh-secret
  channel: 42
  bandwidth_mhz: 2
  country: US
defaults:
  target: rpi4-mm6108-spi
  local_ap:
    enabled: true
    password: ap-secret
nodes:
  point01:
    role: point
    hostname: point01
    ip: 10.41.2.1
"""


def test_support_bundle_zip_contains_redacted_diagnostics(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    fleet = workspace / "Fleets" / "field.yml"
    fleet.write_text(FLEET)
    boot = tmp_path / "boot-report-latest"
    boot.mkdir()
    (boot / "logread.txt").write_text("wifi password='boot-secret'\n")

    result = support_bundle.create_support_bundle(
        config="field",
        node="point01",
        boot_report=str(boot),
        output=str(tmp_path / "support.zip"),
        flash_log="api_key=secret-token\n",
    )

    assert result.path.name == "support.zip"
    with zipfile.ZipFile(result.path) as archive:
        names = set(archive.namelist())
        assert "support-bundle.json" in names
        assert "workspace/state.json" in names
        assert "images/inventory.json" in names
        assert "fleet/redacted-config.yml" in names
        assert "fleet/validation.json" in names
        assert "boot-reports/logread.txt" in names
        assert "flash/log.txt" in names
        redacted = archive.read("fleet/redacted-config.yml").decode()
        assert "mesh-secret" not in redacted
        assert "ap-secret" not in redacted
        assert "<redacted>" in redacted
        assert "boot-secret" not in archive.read("boot-reports/logread.txt").decode()
        assert "secret-token" not in archive.read("flash/log.txt").decode()
        report = json.loads(archive.read("redaction-report.json"))
        assert report["redacted"]


def test_default_support_bundle_path_uses_diagnostics_dir(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()

    path = support_bundle.default_support_bundle_path()

    assert path.parent == workspace / "Diagnostics"
    assert path.name.startswith("easymanet-support-")
    assert path.suffix == ".zip"


def test_support_bundle_redacts_quoted_secrets_containing_hash(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    fleet = workspace / "Fleets" / "field.yml"
    fleet.write_text(FLEET.replace("mesh-secret", "mesh#secret").replace("ap-secret", "ap#secret"))
    boot = tmp_path / "boot-report-latest"
    boot.mkdir()
    (boot / "logread.txt").write_text('password="abc#123"\ntoken=abc#123\n')

    result = support_bundle.create_support_bundle(
        config="field",
        node="point01",
        boot_report=str(boot),
        output=str(tmp_path / "support.zip"),
        flash_log="token='tok#en'\n",
    )

    with zipfile.ZipFile(result.path) as archive:
        config_text = archive.read("fleet/redacted-config.yml").decode()
        boot_text = archive.read("boot-reports/logread.txt").decode()
        flash_text = archive.read("flash/log.txt").decode()
        combined = f"{config_text}\n{boot_text}\n{flash_text}"
        assert "mesh#secret" not in combined
        assert "ap#secret" not in combined
        assert "abc#123" not in combined
        assert "tok#en" not in combined
        assert '<redacted>' in boot_text
        assert "token=<redacted>" in boot_text
        assert "'<redacted>'" in flash_text


def test_support_bundle_preserves_non_utf_boot_report_file(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    boot = tmp_path / "boot-report-latest"
    boot.mkdir()
    binary = b"\xff\xfe\x00\x01"
    (boot / "capture.bin").write_bytes(binary)

    result = support_bundle.create_support_bundle(
        boot_report=str(boot),
        output=str(tmp_path / "support.zip"),
    )

    with zipfile.ZipFile(result.path) as archive:
        assert archive.read("boot-reports/capture.bin") == binary


def test_support_bundle_redacts_private_key_blocks_in_boot_reports(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    boot = tmp_path / "boot-report-latest"
    boot.mkdir()
    private_key = """-----BEGIN OPENSSH PRIVATE KEY-----
abc123
-----END OPENSSH PRIVATE KEY-----
"""
    (boot / "logread.txt").write_text(f"before\n{private_key}after\n")

    result = support_bundle.create_support_bundle(
        boot_report=str(boot),
        output=str(tmp_path / "support.zip"),
    )

    with zipfile.ZipFile(result.path) as archive:
        text = archive.read("boot-reports/logread.txt").decode()
        assert "OPENSSH PRIVATE KEY" not in text
        assert "abc123" not in text
        assert "<redacted>" in text
        report = json.loads(archive.read("redaction-report.json"))
        assert "private_key" in report["redacted"]


def test_support_bundle_redacts_sensitive_boot_report_filenames(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    boot = tmp_path / "boot-report-latest"
    ssh_dir = boot / ".ssh"
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "id_rsa").write_text("super-secret-private-key-material")

    result = support_bundle.create_support_bundle(
        boot_report=str(boot),
        output=str(tmp_path / "support.zip"),
    )

    with zipfile.ZipFile(result.path) as archive:
        assert archive.read("boot-reports/.ssh/id_rsa").decode() == "<redacted>\n"
        report = json.loads(archive.read("redaction-report.json"))
        assert "private_key_file" in report["redacted"]


def test_support_bundle_skips_boot_report_symlink_file(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("password=outside-secret\n")
    boot_link = tmp_path / "boot-link.txt"
    boot_link.symlink_to(outside)

    result = support_bundle.create_support_bundle(
        boot_report=str(boot_link),
        output=str(tmp_path / "support.zip"),
    )

    with zipfile.ZipFile(result.path) as archive:
        names = set(archive.namelist())
        assert "boot-reports/boot-link.txt" not in names
        assert "outside-secret" not in "\n".join(
            archive.read(name).decode(errors="ignore") for name in names
        )
        error = json.loads(archive.read("boot-reports/error.json"))
        assert "symlink skipped" in error["errors"][0]


def test_support_bundle_skips_boot_report_symlink_directory(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    outside = tmp_path / "outside-dir"
    outside.mkdir()
    (outside / "password.txt").write_text("password=outside-secret\n")
    boot_link = tmp_path / "boot-link"
    boot_link.symlink_to(outside, target_is_directory=True)

    result = support_bundle.create_support_bundle(
        boot_report=str(boot_link),
        output=str(tmp_path / "support.zip"),
    )

    with zipfile.ZipFile(result.path) as archive:
        names = set(archive.namelist())
        assert "boot-reports/boot-link/password.txt" not in names
        assert "outside-secret" not in "\n".join(
            archive.read(name).decode(errors="ignore") for name in names
        )
        error = json.loads(archive.read("boot-reports/error.json"))
        assert "symlink skipped" in error["errors"][0]


def test_support_bundle_skips_broken_symlink(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    boot_link = tmp_path / "broken-boot-link"
    boot_link.symlink_to(tmp_path / "missing-boot-report")

    result = support_bundle.create_support_bundle(
        boot_report=str(boot_link),
        output=str(tmp_path / "support.zip"),
    )

    with zipfile.ZipFile(result.path) as archive:
        error = json.loads(archive.read("boot-reports/error.json"))
        assert "Boot report not found" in error["errors"][0]


def test_support_bundle_skips_symlinks_inside_boot_report_dir(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("token=outside-secret\n")
    boot = tmp_path / "boot-report-latest"
    boot.mkdir()
    (boot / "logread.txt").write_text("normal log\n")
    (boot / "linked-secret.txt").symlink_to(outside)

    result = support_bundle.create_support_bundle(
        boot_report=str(boot),
        output=str(tmp_path / "support.zip"),
    )

    with zipfile.ZipFile(result.path) as archive:
        names = set(archive.namelist())
        assert "boot-reports/logread.txt" in names
        assert "boot-reports/linked-secret.txt" not in names
        assert "outside-secret" not in "\n".join(
            archive.read(name).decode(errors="ignore") for name in names
        )


def test_support_bundle_skips_symlinked_directory_inside_boot_report(tmp_path, monkeypatch):
    workspace = tmp_path / "EasyMANET"
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    ensure_workspace()
    outside = tmp_path / "outside-dir"
    outside.mkdir()
    (outside / "password.txt").write_text("password=outside-secret\n")
    nested = outside / "nested"
    nested.mkdir()
    (nested / "token.txt").write_text("token=outside-token\n")
    boot = tmp_path / "boot-report-latest"
    boot.mkdir()
    (boot / "logread.txt").write_text("normal log\n")
    (boot / "linked-dir").symlink_to(outside, target_is_directory=True)

    result = support_bundle.create_support_bundle(
        boot_report=str(boot),
        output=str(tmp_path / "support.zip"),
    )

    with zipfile.ZipFile(result.path) as archive:
        names = set(archive.namelist())
        assert "boot-reports/logread.txt" in names
        assert "boot-reports/linked-dir" not in names
        assert "boot-reports/linked-dir/password.txt" not in names
        assert "boot-reports/linked-dir/nested/token.txt" not in names
        assert "outside-secret" not in "\n".join(
            archive.read(name).decode(errors="ignore") for name in names
        )
        assert "outside-token" not in "\n".join(
            archive.read(name).decode(errors="ignore") for name in names
        )
