import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


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
