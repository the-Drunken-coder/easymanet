from pathlib import Path


def test_extra_packages_referenced_by_image_workflow():
    root = Path(__file__).resolve().parents[1]
    workflow_paths = (
        root / ".github" / "workflows" / "build-openmanet-image.yml",
        root / ".github" / "workflows" / "image-release.yml",
    )
    texts = [path.read_text(encoding="utf-8") for path in workflow_paths if path.exists()]

    assert texts, "image workflow missing from image-capable repo"
    text = "\n".join(texts)
    assert "image build" in text
    assert "easymanet" in text
    assert "extra-packages.txt" in text
    assert "easymanet-image-release.json" in text
    assert "easymanet-image-manifest.json" not in text


def test_public_image_readme_documents_workflow_steps_that_exist():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / "product_repos" / "templates" / "images" / ".github" / "workflows" / "image-release.yml").read_text(
        encoding="utf-8"
    )
    readme = (root / "product_repos" / "templates" / "images" / "README.md").read_text(encoding="utf-8")

    documented = {
        "easymanet-image-release.json": "Generate release manifest",
        "artifact attestations": "Attest release artifacts",
        "Sigstore/cosign": "Sign release manifest",
        "release notes": "Generate release notes",
        "GitHub Release": "Create GitHub release",
    }
    for phrase, step in documented.items():
        assert phrase in readme
        assert step in workflow
