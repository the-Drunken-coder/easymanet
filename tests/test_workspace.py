from easymanet import workspace


def test_workspace_payload_creates_shared_folders(tmp_path, monkeypatch):
    root = tmp_path / "EasyMANET"
    monkeypatch.setenv(workspace.WORKSPACE_ENV, str(root))

    payload = workspace.workspace_payload()

    assert payload["root"] == str(root)
    assert (root / "Fleets").is_dir()
    assert (root / "Images").is_dir()
    assert (root / "Diagnostics").is_dir()
    assert (root / "Builds").is_dir()
    assert (root / "README.txt").read_text().startswith("EasyMANET workspace")


def test_fleet_files_are_listed_and_resolved_from_workspace(tmp_path, monkeypatch):
    root = tmp_path / "EasyMANET"
    monkeypatch.setenv(workspace.WORKSPACE_ENV, str(root))
    workspace.ensure_workspace()
    (root / "Fleets" / "field.yml").write_text("version: 1\n")
    nested = root / "Fleets" / "sites"
    nested.mkdir()
    (nested / "lab.yaml").write_text("version: 1\n")
    (root / "Fleets" / "notes.txt").write_text("not a fleet\n")

    records = workspace.fleet_file_records()

    assert [record["relative_path"] for record in records] == [
        "field.yml",
        "sites/lab.yaml",
    ]
    assert workspace.resolve_fleet_config("field") == root / "Fleets" / "field.yml"
    assert workspace.resolve_fleet_config("sites/lab") == nested / "lab.yaml"


def test_resolve_fleet_config_keeps_local_path_suffix_lookup(tmp_path, monkeypatch):
    root = tmp_path / "EasyMANET"
    local = tmp_path / "local-fleet.yml"
    monkeypatch.setenv(workspace.WORKSPACE_ENV, str(root))
    local.write_text("version: 1\n")

    assert workspace.resolve_fleet_config(str(tmp_path / "local-fleet")) == local
