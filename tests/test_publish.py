import json

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
