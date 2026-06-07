import json

import pytest

from easymanet_publish import export as export_mod
from easymanet_publish.export import EXPORT_RECORD, export_public_surfaces


def test_export_public_surfaces_writes_local_outputs(tmp_path):
    output = tmp_path / "public"

    record = export_public_surfaces(output, source_ref="abc123")

    assert record["source_ref"] == "abc123"
    assert record["subrepos_configured"] is False
    for surface in ("image", "cli", "desktop"):
        assert (output / surface / "README.generated.md").exists()
        assert (output / surface / ".github" / "workflows" / "easymanet-bootstrap.yml").exists()
        assert surface in record["surfaces"]

    record_path = output / EXPORT_RECORD
    assert record_path.exists()
    payload = json.loads(record_path.read_text())
    assert payload["surfaces"]["image"]["files"]


def test_export_surfaces_include_installable_python_roots(tmp_path):
    output = tmp_path / "public"

    record = export_public_surfaces(output, source_ref="abc123")

    image_files = set(record["surfaces"]["image"]["files"])
    cli_files = set(record["surfaces"]["cli"]["files"])
    desktop_files = set(record["surfaces"]["desktop"]["files"])
    assert "pyproject.toml" in image_files
    assert any(path.startswith("packages/core/") for path in image_files)
    assert any(path.startswith("apps/cli/") for path in image_files)
    assert any(path.startswith("packages/image/") for path in cli_files)
    assert any(path.startswith("images/openmanet/") for path in cli_files)
    assert any(path.startswith("apps/desktop/") for path in desktop_files)
    assert not any(path.startswith("apps/cli/") for path in desktop_files)
    assert not any(path.startswith("packages/image/") for path in desktop_files)


def test_export_surfaces_generate_surface_specific_pyprojects(tmp_path):
    output = tmp_path / "public"

    export_public_surfaces(output, source_ref="abc123")

    image_pyproject = (output / "image" / "pyproject.toml").read_text()
    cli_pyproject = (output / "cli" / "pyproject.toml").read_text()
    desktop_pyproject = (output / "desktop" / "pyproject.toml").read_text()

    assert 'name = "easymanet-image"' in image_pyproject
    assert 'easymanet = "easymanet_cli.app:main"' in image_pyproject
    assert "apps/desktop/src" not in image_pyproject
    assert "tools/publish/src" not in image_pyproject
    assert "easymanet-desktop" not in image_pyproject
    assert "easymanet-publish" not in image_pyproject
    assert '"rich>=13"' not in image_pyproject

    assert 'name = "easymanet-cli"' in cli_pyproject
    assert 'easymanet = "easymanet_cli.app:main"' in cli_pyproject
    assert "apps/desktop/src" not in cli_pyproject
    assert "tools/publish/src" not in cli_pyproject
    assert "easymanet-desktop" not in cli_pyproject
    assert "easymanet-publish" not in cli_pyproject
    assert '"rich>=13"' not in cli_pyproject

    assert 'name = "easymanet-desktop"' in desktop_pyproject
    assert 'easymanet-desktop = "easymanet_desktop.server:main"' in desktop_pyproject
    assert "apps/cli/src" not in desktop_pyproject
    assert "packages/image/src" not in desktop_pyproject
    assert "tools/publish/src" not in desktop_pyproject
    assert "easymanet-publish" not in desktop_pyproject
    assert '"rich>=13"' not in desktop_pyproject


def test_export_templates_dispatch_and_checkout_requested_refs(tmp_path):
    output = tmp_path / "public"

    export_public_surfaces(output, source_ref="abc123")

    cli_bootstrap = (
        output / "cli" / ".github" / "workflows" / "easymanet-bootstrap.yml"
    ).read_text()
    image_bootstrap = (
        output / "image" / ".github" / "workflows" / "easymanet-bootstrap.yml"
    ).read_text()
    cli_release = (output / "cli" / ".github" / "workflows" / "release-cli.yml").read_text()
    desktop_release = (
        output / "desktop" / ".github" / "workflows" / "release-desktop.yml"
    ).read_text()

    assert "gh workflow run release-cli.yml -R ${{ github.repository }}" in cli_bootstrap
    assert "-R ${{ github.repository }}" in image_bootstrap
    assert "ref: ${{ inputs.source_ref || github.sha }}" in cli_release
    assert "ref: ${{ inputs.source_ref || github.sha }}" in desktop_release


def test_export_copy_paths_fails_on_missing_sources(tmp_path):
    source_root = tmp_path / "source"
    surface_dir = tmp_path / "surface"
    source_root.mkdir()
    surface_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="missing.yml"):
        export_mod._copy_paths(source_root, surface_dir, ["missing.yml"])


def test_export_copy_paths_ignores_dependency_artifacts(tmp_path):
    source_root = tmp_path / "source"
    surface_dir = tmp_path / "surface"
    node_modules = source_root / "apps" / "desktop" / "electron" / "node_modules" / "pkg"
    node_modules.mkdir(parents=True)
    (node_modules / "index.js").write_text("module.exports = {};\n")
    app_file = source_root / "apps" / "desktop" / "electron" / "main.js"
    app_file.parent.mkdir(parents=True, exist_ok=True)
    app_file.write_text("console.log('ok');\n")
    surface_dir.mkdir()

    copied = export_mod._copy_paths(source_root, surface_dir, ["apps/desktop"])

    assert "apps/desktop/electron/main.js" in copied
    assert not (surface_dir / "apps" / "desktop" / "electron" / "node_modules").exists()


def test_repo_root_fails_loudly_when_sentinels_are_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="pyproject.toml"):
        export_mod._repo_root()
