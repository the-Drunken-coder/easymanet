from easymanet import _download_release, download


def test_github_release_prefers_image_release_manifest(monkeypatch):
    image_name = "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    release = {
        "tag_name": "v1",
        "assets": [
            {
                "name": "easymanet-image-release.json",
                "browser_download_url": "https://example.invalid/easymanet-image-release.json",
            },
            {
                "name": image_name,
                "browser_download_url": f"https://example.invalid/{image_name}",
            },
        ],
    }
    manifest = {
        "target": "rpi4-mm6108-spi",
        "openmanet_version": "1.6.5",
        "artifact": {
            "filename": image_name,
            "sha256": "a" * 64,
        },
    }

    monkeypatch.setattr(_download_release, "_fetch_github_release", lambda _repo: release)
    monkeypatch.setattr(_download_release, "_fetch_release_manifest", lambda _url: manifest)

    ref = download._check_github_release("owner/repo", "rpi4-mm6108-spi")

    assert ref is not None
    assert ref.version == "v1"
    assert ref.url == f"https://example.invalid/{image_name}"
    assert ref.sha256 == "a" * 64


def test_release_manifest_ignores_wrong_target():
    ref = download._image_ref_from_release_manifest(
        {
            "target": "other-target",
            "artifact": {"filename": "image.img.gz", "sha256": "a" * 64},
        },
        [{"name": "image.img.gz", "browser_download_url": "https://example.invalid/image.img.gz"}],
        "rpi4-mm6108-spi",
    )

    assert ref is None
