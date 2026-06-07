"""Export generated public product surfaces without configuring subrepos."""

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class Surface:
    name: str
    paths: tuple[str, ...]
    package_roots: tuple[str, ...]
    package_includes: tuple[str, ...]
    scripts: tuple[tuple[str, str], ...]
    package_data: tuple[tuple[str, tuple[str, ...]], ...] = ()
    include_image_data: bool = False


SURFACES = (
    Surface(
        "image",
        (
            "README.md",
            "planning.md",
            "images/openmanet",
            "packages/core",
            "packages/image",
            "apps/cli",
            ".github/workflows/build-openmanet-image.yml",
        ),
        package_roots=(
            "packages/core/src",
            "packages/image/src",
            "apps/cli/src",
        ),
        package_includes=(
            "easymanet*",
            "easymanet_cli*",
            "easymanet_image*",
        ),
        scripts=(
            ("easymanet", "easymanet_cli.app:main"),
        ),
        include_image_data=True,
    ),
    Surface(
        "cli",
        (
            "README.md",
            "docs/README.md",
            "docs/architecture.md",
            "docs/flashing.md",
            "docs/manifest.md",
            "examples",
            "images/openmanet",
            "packages/core",
            "packages/image",
            "apps/cli",
        ),
        package_roots=(
            "packages/core/src",
            "packages/image/src",
            "apps/cli/src",
        ),
        package_includes=(
            "easymanet*",
            "easymanet_cli*",
            "easymanet_image*",
        ),
        scripts=(
            ("easymanet", "easymanet_cli.app:main"),
        ),
        include_image_data=True,
    ),
    Surface(
        "desktop",
        (
            "README.md",
            "docs/manifest.md",
            "examples",
            "packages/core",
            "apps/desktop",
        ),
        package_roots=(
            "packages/core/src",
            "apps/desktop/src",
        ),
        package_includes=(
            "easymanet*",
            "easymanet_desktop*",
        ),
        scripts=(
            ("easymanet-desktop", "easymanet_desktop.server:main"),
        ),
        package_data=(
            ("easymanet_desktop", ("static/*",)),
        ),
    ),
)

EXPORT_RECORD = "easymanet-public-surfaces.json"
EXPORT_IGNORE = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    "*.egg-info",
    ".pytest_cache",
    "build",
    "dist",
    "node_modules",
    "out",
)
IMAGE_DATA_FILES = (
    (
        "share/easymanet/images/openmanet/provisioning",
        ("images/openmanet/provisioning/extra-packages.txt",),
    ),
    (
        "share/easymanet/images/openmanet/provisioning/openwrt-overlay",
        ("images/openmanet/provisioning/openwrt-overlay/README.md",),
    ),
    (
        "share/easymanet/images/openmanet/provisioning/openwrt-overlay/etc/easymanet",
        ("images/openmanet/provisioning/openwrt-overlay/etc/easymanet/provision.json",),
    ),
    (
        "share/easymanet/images/openmanet/provisioning/openwrt-overlay/etc/init.d",
        (
            "images/openmanet/provisioning/openwrt-overlay/etc/init.d/easymanet-boot-report",
            "images/openmanet/provisioning/openwrt-overlay/etc/init.d/easymanet-management-lan",
        ),
    ),
    (
        "share/easymanet/images/openmanet/provisioning/openwrt-overlay/etc/sysctl.d",
        ("images/openmanet/provisioning/openwrt-overlay/etc/sysctl.d/99-easymanet.conf",),
    ),
    (
        "share/easymanet/images/openmanet/provisioning/openwrt-overlay/etc/uci-defaults",
        (
            "images/openmanet/provisioning/openwrt-overlay/etc/uci-defaults/97-easymanet-management-lan",
            "images/openmanet/provisioning/openwrt-overlay/etc/uci-defaults/98-easymanet-boot-report",
            "images/openmanet/provisioning/openwrt-overlay/etc/uci-defaults/99-easymanet",
        ),
    ),
    (
        "share/easymanet/images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet",
        (
            "images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/boot-report.sh",
            "images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/network.sh",
            "images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/provision-lib.sh",
            "images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/provision.sh",
        ),
    ),
)


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

    record: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_ref": source_ref or _git_ref(repo_root),
        "subrepos_configured": False,
        "surfaces": {},
    }

    for surface in SURFACES:
        surface_dir = output_dir / surface.name
        if surface_dir.exists():
            shutil.rmtree(surface_dir)
        surface_dir.mkdir(parents=True)
        copied = _copy_paths(repo_root, surface_dir, surface.paths)
        copied.extend(_copy_templates(surface_dir, surface.name))
        copied.append(_write_surface_pyproject(repo_root, surface_dir, surface))
        copied = sorted(set(copied))
        _write_surface_readme(surface_dir, surface.name, copied)
        record["surfaces"][surface.name] = {
            "path": str(surface_dir),
            "files": copied,
        }

    record_path = output_dir / EXPORT_RECORD
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    record["record_path"] = str(record_path)
    return record


def _copy_paths(repo_root: Path, surface_dir: Path, paths: Iterable[str]) -> list[str]:
    copied: list[str] = []
    missing: list[str] = []
    for rel in paths:
        source = repo_root / rel
        if not source.exists():
            missing.append(rel)
            continue
        dest = surface_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, dest, ignore=EXPORT_IGNORE)
            copied.extend(_relative_files(dest, surface_dir))
        else:
            shutil.copy2(source, dest)
            copied.append(rel)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise FileNotFoundError(f"Export source path(s) missing: {missing_text}")
    return sorted(set(copied))


def _copy_templates(surface_dir: Path, surface: str) -> list[str]:
    template_root = Path(__file__).resolve().parent / "templates" / surface
    if not template_root.exists():
        return []
    copied: list[str] = []
    for source in template_root.rglob("*"):
        if not source.is_file():
            continue
        rel = source.relative_to(template_root)
        dest = surface_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        copied.append(rel.as_posix())
    return copied


def _write_surface_pyproject(repo_root: Path, surface_dir: Path, surface: Surface) -> str:
    version = _project_version(repo_root / "pyproject.toml")
    lines = [
        "[build-system]",
        'requires = ["setuptools>=68", "wheel"]',
        'build-backend = "setuptools.build_meta"',
        "",
        "[project]",
        f'name = "easymanet-{surface.name}"',
        f'version = "{version}"',
        'description = "Zero-touch OpenMANET provisioning and imaging"',
        'readme = "README.md"',
        'requires-python = ">=3.9"',
        'license = {text = "MIT"}',
        "authors = [",
        '    {name = "EasyMANET Contributors"}',
        "]",
        'keywords = ["openmanet", "mesh", "provisioning", "openwrt"]',
        "classifiers = [",
        '    "Development Status :: 3 - Alpha",',
        '    "Environment :: Console",',
        '    "Intended Audience :: System Administrators",',
        '    "License :: OSI Approved :: MIT License",',
        '    "Operating System :: MacOS",',
        '    "Operating System :: POSIX :: Linux",',
        '    "Programming Language :: Python :: 3",',
        '    "Programming Language :: Python :: 3.9",',
        '    "Topic :: System :: Installation/Setup",',
        '    "Topic :: System :: Systems Administration",',
        "]",
        "dependencies = [",
        '    "typer>=0.9",',
        '    "pyyaml>=6",',
        "]",
        "",
        "[project.optional-dependencies]",
        "dev = [",
        '    "pytest>=7",',
        '    "pytest-cov",',
        '    "setuptools>=68",',
        '    "tomli>=2",',
        '    "wheel",',
        "]",
        "",
        "[project.scripts]",
    ]
    lines.extend(f'{name} = "{target}"' for name, target in surface.scripts)
    lines.extend(
        [
            "",
            "[tool.setuptools.packages.find]",
            "where = [",
        ]
    )
    lines.extend(f'    "{root}",' for root in surface.package_roots)
    lines.extend(
        [
            "]",
            "include = [",
        ]
    )
    lines.extend(f'    "{include}",' for include in surface.package_includes)
    lines.append("]")

    if surface.package_data:
        lines.extend(["", "[tool.setuptools.package-data]"])
        for package, patterns in surface.package_data:
            lines.append(f'"{package}" = [{_quoted_csv(patterns)}]')

    if surface.include_image_data:
        lines.extend(["", "[tool.setuptools.data-files]"])
        for target, paths in IMAGE_DATA_FILES:
            lines.append(f'"{target}" = [')
            lines.extend(f'    "{path}",' for path in paths)
            lines.append("]")

    (surface_dir / "pyproject.toml").write_text("\n".join(lines) + "\n")
    return "pyproject.toml"


def _project_version(pyproject: Path) -> str:
    match = re.search(r'^version = "([^"]+)"$', pyproject.read_text(), re.MULTILINE)
    if not match:
        raise ValueError(f"Could not find project version in {pyproject}")
    return match.group(1)


def _quoted_csv(values: tuple[str, ...]) -> str:
    return ", ".join(f'"{value}"' for value in values)


def _relative_files(path: Path, root: Path) -> list[str]:
    return [
        item.relative_to(root).as_posix()
        for item in path.rglob("*")
        if item.is_file()
    ]


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
            and (candidate / "planning.md").exists()
            and (candidate / "packages" / "core").exists()
        ):
            return candidate
    raise RuntimeError(
        "Could not locate the EasyMANET repo root from "
        f"{module_path}; checked for pyproject.toml, planning.md, and packages/core."
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
