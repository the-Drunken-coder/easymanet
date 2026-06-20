import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "packaging" / "cleanup_image_releases.py"


def load_cleanup():
    spec = importlib.util.spec_from_file_location("cleanup_image_releases", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_stable_cleanup_keeps_latest_five_and_preserves_just_published():
    cleanup = load_cleanup()
    now = datetime(2026, 6, 20, tzinfo=timezone.utc)
    releases = [
        cleanup.ReleaseRecord(f"images-v0.2.{index}", now - timedelta(days=10 - index))
        for index in range(7)
    ]

    delete = cleanup.planned_deletions(releases, just_published="images-v0.2.0", now=now)

    assert "images-v0.2.1" in delete
    assert "images-v0.2.0" not in delete


def test_candidate_cleanup_keeps_latest_three_or_ninety_days():
    cleanup = load_cleanup()
    now = datetime(2026, 6, 20, tzinfo=timezone.utc)
    releases = [
        cleanup.ReleaseRecord(f"images-v0.3.0-candidate.{index}", now - timedelta(days=index * 10), "rpi4-mm6108-spi")
        for index in range(1, 7)
    ]
    releases.append(
        cleanup.ReleaseRecord("images-v0.4.0-candidate.1", now - timedelta(days=100), "rpi4-mm6108-spi")
    )

    delete = cleanup.planned_deletions(releases, now=now)

    assert "images-v0.3.0-candidate.4" in delete
    assert "images-v0.4.0-candidate.1" in delete
    assert "images-v0.3.0-candidate.1" not in delete


def test_candidate_cleanup_keeps_latest_three_per_target():
    cleanup = load_cleanup()
    now = datetime(2026, 6, 20, tzinfo=timezone.utc)
    releases = [
        cleanup.ReleaseRecord(f"images-v0.3.0-candidate.{index}", now - timedelta(days=index), "rpi4-mm6108-spi")
        for index in range(1, 5)
    ]
    releases.extend(
        cleanup.ReleaseRecord(f"images-v0.4.0-candidate.{index}", now - timedelta(days=index), "rpi5-mm6108-spi")
        for index in range(1, 4)
    )

    delete = cleanup.planned_deletions(releases, now=now)

    assert "images-v0.3.0-candidate.4" in delete
    assert "images-v0.4.0-candidate.3" not in delete


def test_fetch_releases_paginates_and_derives_targets_from_assets(monkeypatch):
    cleanup = load_cleanup()
    calls = []

    def fake_run(args):
        calls.append(args)
        return SimpleNamespace(
            stdout="""[
              [
                {
                  "tag_name": "images-v0.3.0-candidate.1",
                  "created_at": "2026-06-20T00:00:00Z",
                  "assets": [{"name": "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"}]
                }
              ],
              [
                {
                  "tag_name": "images-v0.4.0-candidate.1",
                  "created_at": "2026-06-21T00:00:00Z",
                  "assets": [{"name": "openmanet-1.6.5-rpi5-mm6108-spi-squashfs-sysupgrade.img.gz"}]
                }
              ]
            ]"""
        )

    monkeypatch.setattr(cleanup, "run", fake_run)

    releases = cleanup.fetch_releases("owner/repo")

    assert calls == [["gh", "api", "repos/owner/repo/releases?per_page=100", "--paginate", "--slurp"]]
    assert [release.target for release in releases] == ["rpi4-mm6108-spi", "rpi5-mm6108-spi"]
