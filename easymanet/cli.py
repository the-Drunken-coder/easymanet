"""EasyMANET CLI — zero-touch OpenMANET provisioning and imaging.

Commands:
    easymanet disks                    List removable disks
    easymanet validate --config FILE   Validate fleet config
    easymanet render --config FILE     Render resolved provision.json
    easymanet flash --config FILE ...  Flash an image and stage node config
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer

from .manifest import load_manifest, ManifestError
from .validate import validate, ValidationResult
from .render import render, render_dict
from .disks import list_disks, find_disk, unmount_disk, DiskInfo
from .image import flash_image, finish_flash, FlashError
from .inject import inject, inject_dry_run_info, InjectError
from .platform import check_platform
from .download import (
    check_latest_version,
    download_image,
    get_cached_image,
    check_easymanet_update,
    get_image_config,
    set_image_config,
)
from .build import (
    build_image,
    BuildError,
    DEFAULT_BOARD,
    DEFAULT_OPENMANET_REPO,
    DEFAULT_OPENMANET_VERSION,
    DEFAULT_TARGET,
)
from .privileges import check_privileges

def _app_startup():
    update = check_easymanet_update()
    if update:
        typer.secho(
            f"EasyMANET {update} is available (you have 0.1.0). "
            f"Run: pip3 install --break-system-packages --upgrade easymanet",
            fg=typer.colors.YELLOW,
        )


app = typer.Typer(
    name="easymanet",
    help="Zero-touch OpenMANET provisioning and imaging",
    no_args_is_help=True,
    callback=_app_startup,
)
image_app = typer.Typer(help="Manage image URLs, cache, and firmware builds")
app.add_typer(image_app, name="image")


def _print_header(text: str) -> None:
    typer.secho(text, bold=True)


def _print_errors_and_warnings(result: ValidationResult) -> int:
    exit_code = 0
    if result.errors:
        typer.secho(f"\n{len(result.errors)} error(s):", fg=typer.colors.RED)
        for e in result.errors:
            typer.secho(f"  ✗ {e}", fg=typer.colors.RED)
        exit_code = 1
    if result.warnings:
        typer.secho(f"\n{len(result.warnings)} warning(s):", fg=typer.colors.YELLOW)
        for w in result.warnings:
            typer.secho(f"  ⚠ {w}", fg=typer.colors.YELLOW)
    if result.valid and not result.warnings:
        typer.secho("✓ Config is valid", fg=typer.colors.GREEN)
    elif result.valid:
        typer.secho("✓ Config is valid (with warnings)", fg=typer.colors.GREEN)
    return exit_code


@app.command(name="validate")
def validate_cmd(
    config: str = typer.Option(
        ..., "--config", "-c", help="Path to fleet.yml config file"
    ),
    node: Optional[str] = typer.Option(
        None, "--node", "-n", help="Validate a specific node"
    ),
):
    """Validate a fleet.yml config file."""
    try:
        manifest = load_manifest(config)
    except ManifestError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

    result = validate(manifest, node_name=node)
    typer.secho(f"Validating: {config}", bold=True)
    if node:
        typer.secho(f"Selected node: {node}")

    exit_code = _print_errors_and_warnings(result)
    raise typer.Exit(exit_code)


@app.command(name="render")
def render_cmd(
    config: str = typer.Option(
        ..., "--config", "-c", help="Path to fleet.yml config file"
    ),
    node: str = typer.Option(
        ..., "--node", "-n", help="Node name to render resolved config for"
    ),
):
    """Render the resolved provision.json for a node."""
    try:
        manifest = load_manifest(config)
    except ManifestError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

    result = validate(manifest, node_name=node)
    if result.errors:
        typer.secho("Config has validation errors:", fg=typer.colors.RED)
        for e in result.errors:
            typer.secho(f"  ✗ {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

    output = render(manifest, node)
    print(output)


@app.command(name="disks")
def disks_cmd():
    """List available disks for flashing."""
    check_platform()
    disks = list_disks()

    if not disks:
        typer.secho("No removable/external disks found.", fg=typer.colors.YELLOW)
        return

    for d in disks:
        removable = "yes" if d.removable else "no"
        mounted_str = ", ".join(d.mounted) if d.mounted else "(none)"
        typer.echo(f"  {d.device}")
        typer.echo(f"    Model:      {d.model}")
        typer.echo(f"    Size:       {d.size_human}")
        typer.echo(f"    Removable:  {removable}")
        typer.echo(f"    Mounted:    {mounted_str}")

        for w in d.warnings:
            typer.secho(f"    {w}", fg=typer.colors.RED)

        typer.echo()


@app.command()
def flash(
    config: str = typer.Option(
        ..., "--config", "-c", help="Path to fleet.yml config file"
    ),
    node: str = typer.Option(
        ..., "--node", "-n", help="Node name to provision"
    ),
    device: str = typer.Option(
        ..., "--device", "-d", help="Target device path (e.g., /dev/disk4)"
    ),
    base_image: Optional[str] = typer.Option(
        None, "--base-image", "-i", help="Path to OpenMANET base image (.img or .img.gz) — auto-downloaded if omitted"
    ),
    image_url: Optional[str] = typer.Option(
        None, "--image-url", help="URL to download the base image from (saved for future use)"
    ),
    download: bool = typer.Option(
        False, "--download", help="Force re-download of the latest base image"
    ),
    no_download: bool = typer.Option(
        False, "--no-download", help="Skip auto-download; requires --base-image"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompt"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show plan without writing anything"
    ),
    force: bool = typer.Option(
        False, "--force", help="Override system disk safety check"
    ),
    no_eject: bool = typer.Option(
        False, "--no-eject", help="Do not eject disk after flashing"
    ),
):
    """Flash an OpenMANET image and stage node config on the boot partition.

    If --base-image is omitted, EasyMANET auto-downloads the latest
    OpenMANET image from GitHub releases and caches it locally.

    Use --download to force re-download even if cached.

    Use --no-download to disable auto-download (requires --base-image).
    """
    check_platform()
    if not yes and not dry_run:
        typer.secho("--yes is required to flash. Use --dry-run to preview first.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    try:
        manifest = load_manifest(config)
    except ManifestError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

    result = validate(manifest, node_name=node)
    if result.errors:
        typer.secho("Config validation failed:", fg=typer.colors.RED)
        for e in result.errors:
            typer.secho(f"  ✗ {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

    resolved = render_dict(manifest, node)
    target = resolved["node"]["target"]

    image_path = _resolve_base_image(target, base_image, image_url, download, no_download, dry_run)

    _print_header("Flash Plan")
    typer.echo(f"  Config:       {config}")
    typer.echo(f"  Node:         {node}")
    typer.echo(f"  Hostname:     {resolved['node']['hostname']}")
    typer.echo(f"  Role:         {resolved['node']['role']}")
    typer.echo(f"  Target:       {target}")
    typer.echo(f"  Base image:   {image_path}")
    typer.echo(f"  Device:       {device}")
    typer.echo("  Boot payload: /easymanet/provision.json")
    typer.echo()

    disk = find_disk(device)
    if disk:
        typer.echo("  Disk details:")
        typer.echo(f"    Model:      {disk.model}")
        typer.echo(f"    Size:       {disk.size_human}")
        typer.echo(f"    Removable:  {'yes' if disk.removable else 'no'}")
        mounted_str = ", ".join(disk.mounted) if disk.mounted else "(none)"
        typer.echo(f"    Mounted:    {mounted_str}")
        for w in disk.warnings:
            typer.secho(f"    {w}", fg=typer.colors.RED)
        typer.echo()
    else:
        typer.secho(f"  Warning: Device {device} not found in disk list", fg=typer.colors.YELLOW)
        typer.echo()

    _print_header("Resolved provision.json")
    print(render(manifest, node))
    print()

    typer.echo(inject_dry_run_info(manifest, node))
    print()

    if dry_run:
        typer.secho("Dry run complete. No changes were made.", fg=typer.colors.GREEN)
        return

    if not yes:
        typer.secho("Use --yes to confirm and proceed with flashing.", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    check_privileges(device)

    try:
        flash_image(device=device, image_path=image_path, force=force)
    except FlashError as e:
        typer.secho(f"Flash error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.echo()
    _print_header("Writing boot-partition payload")
    try:
        results = inject(device=device, manifest=manifest, node_name=node)
        for path, ok in results:
            status = "✓" if ok else "✗"
            color = typer.colors.GREEN if ok else typer.colors.RED
            typer.secho(f"  {status} {path}", fg=color)
    except InjectError as e:
        typer.secho(f"Boot payload error: {e}", fg=typer.colors.RED)
        typer.secho(
            "Image was flashed but node provisioning could not be staged on the boot partition.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)

    finish_flash(device, eject=not no_eject)
    typer.secho(
        f"\nDone. Insert the drive into the Raspberry Pi for {node} and boot.",
        fg=typer.colors.GREEN,
    )


def _resolve_base_image(
    target: str,
    base_image: Optional[str],
    image_url: Optional[str],
    download: bool,
    no_download: bool,
    dry_run: bool,
) -> str:
    if base_image:
        return base_image

    if image_url:
        set_image_config(target, image_url, version="custom")
        typer.secho(f"Saved image URL for {target}. Run --download to fetch now.", fg=typer.colors.BLUE)
        if not download:
            typer.secho(
                f"Image URL saved but not downloaded. Re-run with --download to fetch the image, "
                f"or add --base-image to use a local file.",
                fg=typer.colors.BLUE,
            )
            raise typer.Exit(1)

    if no_download:
        typer.secho(
            "--no-download requires --base-image. No base image provided.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    if dry_run:
        cached = get_cached_image(target)
        if cached:
            return str(cached)
        return f"<auto-download for {target}>"

    if download:
        latest = check_latest_version(target)
        if not latest:
            typer.secho(
                f"No image URL configured for target '{target}'. "
                f"Configure one with --image-url or specify --base-image.\n"
                f"  easymanet flash --image-url https://example.com/image.img.gz ...",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        version, url = latest
        path = download_image(target, version, url, force=True)
        return str(path)

    cached = get_cached_image(target)
    if cached:
        typer.secho(f"Using cached image: {cached}", fg=typer.colors.BLUE)
    else:
        latest = check_latest_version(target)
        if not latest:
            typer.secho(
                f"No image configured for target '{target}' and no --base-image given.\n"
                f"\n"
                f"Configure an image URL with:\n"
                f"  easymanet flash --image-url <URL> ...\n"
                f"\n"
                f"Or download an image and pass it with:\n"
                f"  easymanet flash --base-image <path-to-image> ...\n"
                f"\n"
                f"OpenMANET firmware releases can be downloaded from:\n"
                f"  https://github.com/OpenMANET/firmware/releases",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        version, url = latest
        cached = download_image(target, version, url)
    return str(cached)


@image_app.callback(invoke_without_command=True)
def image_cmd(
    ctx: typer.Context,
    target: str = typer.Option(
        "rpi4-mm6108-spi", "--target", "-t", help="Target hardware"
    ),
    set_url: Optional[str] = typer.Option(
        None, "--set-url", help="Set the download URL for the target"
    ),
    set_version: Optional[str] = typer.Option(
        None, "--set-version", help="Set the version label"
    ),
    show: bool = typer.Option(
        False, "--show", help="Show current image config"
    ),
):
    """Manage base image download URLs and cache."""
    if ctx.invoked_subcommand:
        return

    if set_url:
        set_image_config(target, set_url, set_version or "custom")
        typer.secho(f"Image URL set for {target}:", fg=typer.colors.GREEN)
        typer.echo(f"  URL: {set_url}")
        typer.echo(f"  Version: {set_version or 'custom'}")
        return

    info = get_image_config(target)
    cached = get_cached_image(target)

    if not info and not cached:
        typer.secho(f"No image configured for {target}.", fg=typer.colors.YELLOW)
        typer.echo("")
        typer.echo("Configure one with:")
        typer.echo(f"  easymanet image --set-url <URL>")
        return

    _print_header(f"Image config: {target}")
    if info:
        typer.echo(f"  URL:     {info.get('url', '(none)')}")
        typer.echo(f"  Version: {info.get('version', '(none)')}")
        typer.echo(f"  Desc:    {info.get('description', '')}")
    if cached:
        size = cached.stat().st_size
        typer.echo(f"  Cached:  {cached} ({_human_size(size)})")
    else:
        typer.echo(f"  Cached:  none")


@image_app.command(name="build")
def image_build_cmd(
    output_dir: str = typer.Option(
        "dist", "--output-dir", "-o", help="Directory to copy the built image into"
    ),
    openmanet_version: str = typer.Option(
        DEFAULT_OPENMANET_VERSION,
        "--openmanet-version",
        help="OpenMANET/OpenWrt tag or branch to build",
    ),
    board: str = typer.Option(
        DEFAULT_BOARD,
        "--board",
        help="OpenMANET board profile passed to openmanet_setup.sh",
    ),
    target: str = typer.Option(
        DEFAULT_TARGET,
        "--target",
        "-t",
        help="Expected firmware artifact target suffix",
    ),
    repo_url: str = typer.Option(
        DEFAULT_OPENMANET_REPO,
        "--repo-url",
        help="OpenMANET/OpenWrt git repository URL",
    ),
    jobs: Optional[int] = typer.Option(
        None,
        "--jobs",
        "-j",
        help="Parallel make jobs inside the Docker builder",
    ),
    clean: bool = typer.Option(
        False,
        "--clean",
        help="Delete the cached OpenMANET source tree before cloning/building",
    ),
    rebuild_builder: bool = typer.Option(
        False,
        "--rebuild-builder",
        help="Force a rebuild of the Docker builder image",
    ),
    cache_dir: Optional[str] = typer.Option(
        None,
        "--cache-dir",
        help="Host directory to mount as the OpenMANET build cache instead of a Docker volume",
    ),
):
    """Build an EasyMANET-flavored OpenMANET image in Docker."""
    _print_header("Image Build")
    typer.echo(f"  Repo:         {repo_url}")
    typer.echo(f"  Version:      {openmanet_version}")
    typer.echo(f"  Board:        {board}")
    typer.echo(f"  Target:       {target}")
    typer.echo(f"  Output dir:   {output_dir}")
    if cache_dir:
        typer.echo(f"  Cache dir:    {cache_dir}")
    typer.echo("  Overlay:      provisioning/openwrt-overlay")
    typer.echo()

    try:
        artifact = build_image(
            output_dir=output_dir,
            openmanet_version=openmanet_version,
            board=board,
            target=target,
            repo_url=repo_url,
            jobs=jobs,
            clean=clean,
            rebuild_builder=rebuild_builder,
            cache_dir=cache_dir,
        )
    except BuildError as e:
        typer.secho(f"Build error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.secho("Build complete.", fg=typer.colors.GREEN)
    typer.echo(f"  Image: {artifact}")


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    elif n < 1024**2:
        return f"{n/1024:.1f} KB"
    elif n < 1024**3:
        return f"{n/1024**2:.1f} MB"
    else:
        return f"{n/1024**3:.1f} GB"


def main():
    app()


if __name__ == "__main__":
    main()
