"""Tests for CLI helpers."""

import pytest

from easymanet.cli import _resolve_flash_ssh_enabled


def test_resolve_flash_ssh_disable_overrides_gate():
    assert _resolve_flash_ssh_enabled("gate", enable_ssh=False, disable_ssh=True) is False


def test_resolve_flash_ssh_enable_overrides_point():
    assert _resolve_flash_ssh_enabled("point", enable_ssh=True, disable_ssh=False) is True


def test_resolve_flash_ssh_role_defaults():
    assert _resolve_flash_ssh_enabled("gate", enable_ssh=False, disable_ssh=False) is True
    assert _resolve_flash_ssh_enabled("point", enable_ssh=False, disable_ssh=False) is False


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
