"""Export generated public product surfaces without configuring subrepos."""

import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .surfaces import (
    SURFACES,
    SurfaceSpec,
    materialize_commit,
    project_version,
    render_surface_pyproject,
    tracked_files,
)

EXPORT_RECORD = "easymanet-public-surfaces.json"


def export_public_surfaces(
    output_dir: Path,
    *,
    source_ref: Optional[str] = None,
    clean: bool = False,
    repo_root: Optional[Path] = None,
) -> dict[str, Any]:
    repo_root = repo_root or _repo_root()
    output_dir = output_dir.expanduser().resolve()
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    requested_ref = source_ref or _git_ref(repo_root)
    with tempfile.TemporaryDirectory(prefix="easymanet-export-source-") as temp_dir:
        source_root, source_sha = materialize_commit(
            repo_root,
            requested_ref,
            Path(temp_dir),
        )
        record: dict[str, Any] = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_ref": source_sha,
            "subrepos_configured": False,
            "surfaces": {},
        }

        for surface in SURFACES.values():
            surface_dir = output_dir / surface.local_name
            if surface_dir.exists():
                shutil.rmtree(surface_dir)
            surface_dir.mkdir(parents=True)
            copied = _copy_paths(source_root, surface_dir, surface.source_paths, tracked=False)
            copied.extend(_copy_templates(source_root, surface_dir, surface, tracked=False))
            copied.append(_write_surface_pyproject(source_root, surface_dir, surface))
            copied = sorted(set(copied))
            _write_surface_readme(surface_dir, surface.key, copied)
            record["surfaces"][surface.key] = {
                "path": str(surface_dir),
                "files": copied,
            }

    record_path = output_dir / EXPORT_RECORD
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    record["record_path"] = str(record_path)
    return record


def _copy_paths(
    repo_root: Path,
    surface_dir: Path,
    paths: Iterable[str],
    *,
    tracked: bool = True,
) -> list[str]:
    copied: list[str] = []
    for rel in paths:
        source_paths = tracked_files(repo_root, rel) if tracked else _snapshot_files(repo_root, rel)
        for tracked_path in source_paths:
            source = repo_root / tracked_path
            dest = surface_dir / tracked_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            copied.append(tracked_path)
    return sorted(set(copied))


def _copy_templates(
    repo_root: Path,
    surface_dir: Path,
    surface: SurfaceSpec,
    *,
    tracked: bool = True,
) -> list[str]:
    template_root = surface.template_dir(repo_root)
    if not template_root.exists():
        return []
    copied: list[str] = []
    template_path = template_root.relative_to(repo_root).as_posix()
    source_paths = (
        tracked_files(repo_root, template_path)
        if tracked
        else _snapshot_files(repo_root, template_path)
    )
    for tracked_path in source_paths:
        source = repo_root / tracked_path
        rel = source.relative_to(template_root)
        dest = surface_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        copied.append(rel.as_posix())
    return copied


def _snapshot_files(repo_root: Path, rel_path: str) -> tuple[str, ...]:
    source = repo_root / rel_path
    if source.is_file():
        return (rel_path,)
    if not source.is_dir():
        raise FileNotFoundError(f"Source path does not exist: {rel_path}")
    files = tuple(
        path.relative_to(repo_root).as_posix()
        for path in sorted(source.rglob("*"))
        if path.is_file()
    )
    if not files:
        raise FileNotFoundError(f"Source path has no files: {rel_path}")
    return files


def _write_surface_pyproject(repo_root: Path, surface_dir: Path, surface: SurfaceSpec) -> str:
    version = project_version(repo_root / "pyproject.toml")
    (surface_dir / "pyproject.toml").write_text(render_surface_pyproject(surface, version))
    return "pyproject.toml"


def _write_surface_readme(surface_dir: Path, surface: str, copied: list[str]) -> None:
    lines = [
        f"# EasyMANET {surface.title()} Surface",
        "",
        "Generated from the private EasyMANET monorepo.",
        "",
        "This export does not configure remotes, credentials, protected branches, or release dispatch.",
        "",
        "## Included Files",
        "",
    ]
    lines.extend(f"- `{path}`" for path in copied[:200])
    if len(copied) > 200:
        lines.append(f"- ... {len(copied) - 200} more files")
    (surface_dir / "README.generated.md").write_text("\n".join(lines) + "\n")


def _repo_root() -> Path:
    cwd = Path.cwd().resolve()
    module_path = Path(__file__).resolve()
    for candidate in (cwd, *cwd.parents):
        if (
            (candidate / "pyproject.toml").exists()
            and (candidate / "docs" / "monorepo.md").exists()
            and (candidate / "packages" / "core").exists()
        ):
            return candidate
    raise RuntimeError(
        "Could not locate the EasyMANET repo root from "
        f"{module_path}; checked for pyproject.toml, docs/monorepo.md, and packages/core."
    )


def _git_ref(repo_root: Path) -> str:
    git_path = shutil.which("git")
    if not git_path:
        return ""
    try:
        result = subprocess.run(
            [git_path, "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()
