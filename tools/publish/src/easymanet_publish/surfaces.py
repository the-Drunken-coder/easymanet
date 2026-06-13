"""Authoritative EasyMANET public product surface definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SurfaceSpec:
    key: str
    local_name: str
    repo_name: str
    description: str
    source_paths: tuple[str, ...]
    package_roots: tuple[str, ...]
    package_includes: tuple[str, ...]
    scripts: tuple[tuple[str, str], ...]
    dispatch_event: str
    release_workflow: str
    package_name: str | None = None
    package_data: tuple[tuple[str, tuple[str, ...]], ...] = ()
    include_image_data: bool = False
    dependencies: tuple[str, ...] = ("typer>=0.9", "pyyaml>=6")
    dev_dependencies: tuple[str, ...] = (
        "pytest>=7",
        "pytest-cov",
        "setuptools>=68",
        "tomli>=2; python_version < '3.11'",
        "wheel",
    )

    @property
    def name(self) -> str:
        return self.repo_name

    @property
    def python_project_name(self) -> str:
        return self.package_name or self.repo_name

    def template_dir(self, repo_root: Path) -> Path:
        return repo_root / "product_repos" / "templates" / self.key


PRODUCT_DOC_PATHS = (
    "docs/README.md",
    "docs/architecture.md",
    "docs/flashing.md",
    "docs/lessons-learned.md",
    "docs/manifest.md",
    "docs/openmanet-config-investigation.md",
)

PRODUCT_TEST_PATHS = (
    "tests/shell_harness",
    "tests/test_build.py",
    "tests/test_cli.py",
    "tests/test_cli_common.py",
    "tests/test_disks.py",
    "tests/test_download.py",
    "tests/test_extra_packages.py",
    "tests/test_firstboot.py",
    "tests/test_image.py",
    "tests/test_inject.py",
    "tests/test_led_status.py",
    "tests/test_manifest.py",
    "tests/test_packaging.py",
    "tests/test_privileges.py",
    "tests/test_provision_behavior.py",
    "tests/test_render.py",
    "tests/test_sysctl.py",
    "tests/test_validate.py",
)

COMMON_PRODUCT_SOURCE_PATHS = (
    ".gitignore",
    "pyproject.toml",
    *PRODUCT_DOC_PATHS,
    "packages/core/src/easymanet",
    "examples/three-node-field-mesh.yml",
    "images/openmanet/provisioning",
    "tools/packaging/verify_overlay_packaging.py",
    "tools/release_smoke.py",
    *PRODUCT_TEST_PATHS,
)

CLI_RUNTIME_SOURCE_PATHS = (
    "apps/cli",
    "packages/image",
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
            "images/openmanet/provisioning/openwrt-overlay/etc/init.d/easymanet-led-status",
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
            "images/openmanet/provisioning/openwrt-overlay/etc/uci-defaults/96-easymanet-led-status",
            "images/openmanet/provisioning/openwrt-overlay/etc/uci-defaults/97-easymanet-management-lan",
            "images/openmanet/provisioning/openwrt-overlay/etc/uci-defaults/98-easymanet-boot-report",
            "images/openmanet/provisioning/openwrt-overlay/etc/uci-defaults/99-easymanet",
        ),
    ),
    (
        "share/easymanet/images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet",
        (
            "images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/api.sh",
            "images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/boot-report.sh",
            "images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/led-status.sh",
            "images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/network.sh",
            "images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/provision-lib.sh",
            "images/openmanet/provisioning/openwrt-overlay/usr/lib/easymanet/provision.sh",
        ),
    ),
    (
        "share/easymanet/images/openmanet/provisioning/openwrt-overlay/www/easymanet-api/v1",
        (
            "images/openmanet/provisioning/openwrt-overlay/www/easymanet-api/v1/identity",
            "images/openmanet/provisioning/openwrt-overlay/www/easymanet-api/v1/neighbors",
            "images/openmanet/provisioning/openwrt-overlay/www/easymanet-api/v1/topology",
        ),
    ),
)

SURFACES = {
    "images": SurfaceSpec(
        key="images",
        local_name="images",
        repo_name="easymanet-images",
        description="Public firmware image factory for EasyMANET/OpenMANET releases.",
        source_paths=COMMON_PRODUCT_SOURCE_PATHS + CLI_RUNTIME_SOURCE_PATHS + (
            "tests/test_image_workflows.py",
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
        scripts=(("easymanet", "easymanet_cli.app:main"),),
        dispatch_event="easymanet-image-release",
        release_workflow="image-release.yml",
        include_image_data=True,
    ),
    "cli": SurfaceSpec(
        key="cli",
        local_name="cli",
        repo_name="easymanet-cli",
        description="Public CLI and automation surface for EasyMANET.",
        source_paths=COMMON_PRODUCT_SOURCE_PATHS + CLI_RUNTIME_SOURCE_PATHS,
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
        scripts=(("easymanet", "easymanet_cli.app:main"),),
        dispatch_event="easymanet-cli-release",
        release_workflow="cli-release.yml",
        package_name="easymanet",
        include_image_data=True,
    ),
    "desktop": SurfaceSpec(
        key="desktop",
        local_name="desktop",
        repo_name="easymanet-desktop",
        description="Public local-first desktop operator console for EasyMANET.",
        source_paths=(
            ".gitignore",
            "docs/manifest.md",
            "examples/three-node-field-mesh.yml",
            "packages/core/src/easymanet",
            "apps/desktop",
            "tests/test_desktop.py",
        ),
        package_roots=(
            "packages/core/src",
            "apps/desktop/src",
        ),
        package_includes=(
            "easymanet*",
            "easymanet_desktop*",
        ),
        scripts=(("easymanet-desktop", "easymanet_desktop.server:main"),),
        package_data=(("easymanet_desktop", ("static/*",)),),
        dispatch_event="easymanet-desktop-release",
        release_workflow="desktop-release.yml",
    ),
}


def selected_surface_specs(product: str) -> list[SurfaceSpec]:
    if product == "all":
        return list(SURFACES.values())
    return [SURFACES[product]]


def render_surface_pyproject(surface: SurfaceSpec, version: str) -> str:
    lines = [
        "[build-system]",
        'requires = ["setuptools>=68", "wheel"]',
        'build-backend = "setuptools.build_meta"',
        "",
        "[project]",
        f"name = {_toml_string(surface.python_project_name)}",
        f"version = {_toml_string(version)}",
        f"description = {_toml_string(surface.description)}",
        'readme = "README.md"',
        'requires-python = ">=3.10"',
        'license = "MIT"',
        "authors = [",
        '    {name = "EasyMANET Contributors"}',
        "]",
        'keywords = ["openmanet", "mesh", "provisioning", "openwrt"]',
        "classifiers = [",
        '    "Development Status :: 3 - Alpha",',
        '    "Environment :: Console",',
        '    "Intended Audience :: System Administrators",',
        '    "Operating System :: MacOS",',
        '    "Operating System :: POSIX :: Linux",',
        '    "Programming Language :: Python :: 3",',
        '    "Programming Language :: Python :: 3.10",',
        '    "Programming Language :: Python :: 3.11",',
        '    "Topic :: System :: Installation/Setup",',
        '    "Topic :: System :: Systems Administration",',
        "]",
        "dependencies = [",
    ]
    lines.extend(f"    {_toml_string(dependency)}," for dependency in surface.dependencies)
    lines.extend(
        [
            "]",
            "",
            "[project.optional-dependencies]",
            "dev = [",
        ]
    )
    lines.extend(f"    {_toml_string(dependency)}," for dependency in surface.dev_dependencies)
    lines.extend(["]", ""])

    if surface.scripts:
        lines.append("[project.scripts]")
        lines.extend(f"{name} = {_toml_string(target)}" for name, target in surface.scripts)
        lines.append("")

    lines.extend(
        [
            "[tool.setuptools.packages.find]",
            "where = [",
        ]
    )
    lines.extend(f"    {_toml_string(root)}," for root in surface.package_roots)
    lines.extend(
        [
            "]",
            "include = [",
        ]
    )
    lines.extend(f"    {_toml_string(include)}," for include in surface.package_includes)
    lines.append("]")

    if surface.package_data:
        lines.extend(["", "[tool.setuptools.package-data]"])
        for package, patterns in surface.package_data:
            lines.append(f"{_toml_string(package)} = [{_quoted_csv(patterns)}]")

    if surface.include_image_data:
        lines.extend(["", "[tool.setuptools.data-files]"])
        for target, paths in IMAGE_DATA_FILES:
            lines.append(f"{_toml_string(target)} = [")
            lines.extend(f"    {_toml_string(path)}," for path in paths)
            lines.append("]")

    lines.extend(
        [
            "",
            "[tool.pytest.ini_options]",
            'testpaths = ["tests"]',
            'python_files = ["test_*.py"]',
            "pythonpath = [",
        ]
    )
    lines.extend(f"    {_toml_string(root)}," for root in (*surface.package_roots, "."))
    lines.append("]")
    return "\n".join(lines) + "\n"


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _quoted_csv(values: tuple[str, ...]) -> str:
    return ", ".join(_toml_string(value) for value in values)
