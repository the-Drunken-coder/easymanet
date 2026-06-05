"""Tests for CLI helpers."""

import pytest

from easymanet.cli import _resolve_flash_ssh_enabled


def test_resolve_flash_ssh_disable_overrides_gate():
    assert _resolve_flash_ssh_enabled(enable_ssh=False, disable_ssh=True) is False


def test_resolve_flash_ssh_enable_overrides_point():
    assert _resolve_flash_ssh_enabled(enable_ssh=True, disable_ssh=False) is True


def test_resolve_flash_ssh_role_defaults():
    assert _resolve_flash_ssh_enabled(enable_ssh=False, disable_ssh=False) is None


def test_flash_ssh_flags_mutually_exclusive():
    from typer.testing import CliRunner

    from easymanet.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "flash",
            "--config",
            "fleet.yml",
            "--node",
            "n1",
            "--device",
            "/dev/disk4",
            "--enable-ssh",
            "--disable-ssh",
            "--yes",
        ],
    )
    assert result.exit_code == 1
    assert "Cannot use --enable-ssh and --disable-ssh" in result.output


def test_flash_download_flags_mutually_exclusive():
    from typer.testing import CliRunner

    from easymanet.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "flash",
            "--config",
            "fleet.yml",
            "--node",
            "n1",
            "--device",
            "/dev/disk4",
            "--download",
            "--no-download",
            "--yes",
        ],
    )
    assert result.exit_code == 1
    assert "Cannot use --download and --no-download" in result.output


def test_image_build_chains_build_error(monkeypatch):
    from typer.testing import CliRunner

    from easymanet import cli_image
    from easymanet.build import BuildError
    from easymanet.cli import app

    def fail_build(**kwargs):
        del kwargs
        raise BuildError("docker is missing")

    monkeypatch.setattr(cli_image, "maybe_show_update_notice", lambda: None)
    monkeypatch.setattr(cli_image, "build_image", fail_build)

    result = CliRunner().invoke(app, ["image", "build", "--output-dir", "dist"])

    assert result.exit_code == 1
    assert "Build error: docker is missing" in result.output
