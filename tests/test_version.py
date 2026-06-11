"""Tests for EasyMANET version sourcing."""

import easymanet


def test_version_prefers_installed_package_metadata(monkeypatch):
    monkeypatch.setattr(easymanet.metadata, "version", lambda name: "9.8.7")

    assert easymanet._version() == "9.8.7"


def test_version_falls_back_to_source_pyproject(monkeypatch, tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "easymanet"\nversion = "1.2.3"\n')

    def missing_metadata(_name):
        raise easymanet.metadata.PackageNotFoundError

    monkeypatch.setattr(easymanet.metadata, "version", missing_metadata)
    monkeypatch.setattr(easymanet, "_source_pyproject", lambda: pyproject)

    assert easymanet._version() == "1.2.3"
