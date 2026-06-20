#!/usr/bin/env python3
"""Clean up public EasyMANET image releases according to retention policy."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

STABLE_KEEP = 5
CANDIDATE_KEEP = 3
CANDIDATE_MAX_DAYS = 90
STABLE_RE = re.compile(r"^images-v\d+\.\d+\.\d+$")
CANDIDATE_RE = re.compile(r"^images-v\d+\.\d+\.\d+-candidate\.\d+$")


@dataclass(frozen=True)
class ReleaseRecord:
    tag: str
    created_at: datetime
    target: str = ""


def planned_deletions(
    releases: list[ReleaseRecord],
    *,
    just_published: str = "",
    now: datetime | None = None,
) -> list[str]:
    now = now or datetime.now(timezone.utc)
    delete: list[str] = []

    stable = sorted(
        [release for release in releases if STABLE_RE.match(release.tag)],
        key=lambda release: release.created_at,
        reverse=True,
    )
    delete.extend(release.tag for release in stable[STABLE_KEEP:] if release.tag != just_published)

    candidates_by_target: dict[str, list[ReleaseRecord]] = {}
    for release in releases:
        if CANDIDATE_RE.match(release.tag):
            candidates_by_target.setdefault(release.target or "default", []).append(release)
    for candidates in candidates_by_target.values():
        ordered = sorted(candidates, key=lambda release: release.created_at, reverse=True)
        for index, release in enumerate(ordered):
            age_days = (now - release.created_at).days
            if release.tag == just_published:
                continue
            if index >= CANDIDATE_KEEP or age_days > CANDIDATE_MAX_DAYS:
                delete.append(release.tag)

    return sorted(set(delete))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--just-published", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    releases = fetch_releases(args.repo)
    deletions = planned_deletions(releases, just_published=args.just_published)
    for tag in deletions:
        print(f"delete {tag}")
        if not args.dry_run:
            run(["gh", "release", "delete", tag, "--repo", args.repo, "--yes", "--cleanup-tag"])
    if not deletions:
        print("no image releases to delete")
    return 0


def fetch_releases(repo: str) -> list[ReleaseRecord]:
    result = run(["gh", "release", "list", "--repo", repo, "--limit", "100", "--json", "tagName,createdAt"])
    data = json.loads(result.stdout)
    records: list[ReleaseRecord] = []
    for item in data:
        tag = str(item.get("tagName") or "")
        created = str(item.get("createdAt") or "")
        if not tag or not created:
            continue
        records.append(ReleaseRecord(tag=tag, created_at=_parse_time(created), target=_target_from_tag(tag)))
    return records


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _target_from_tag(tag: str) -> str:
    del tag
    return "rpi4-mm6108-spi"


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, text=True, capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
