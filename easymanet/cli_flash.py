"""Flash command and image resolution helpers."""

from typing import Optional

import typer

from .cli_common import maybe_show_update_notice, print_header
from .disks import assert_flash_allowed, lookup_device
from .download import check_latest_version, download_image, get_cached_image, set_image_config
from .image import FlashError, finish_flash, flash_image
from .inject import InjectError, inject, inject_dry_run_info
from .manifest import ManifestError, load_manifest
from .platform import check_platform
from .privileges import PrivilegeError, check_privileges
from .render import render, render_dict
from .validate import validate


def resolve_flash_ssh_enabled(
    *,
    enable_ssh: bool,
    disable_ssh: bool,
) -> Optional[bool]:
    if disable_ssh:
        return False
    if enable_ssh:
        return True
    return None


def flash_ssh_note(
    role: str,
    *,
    enable_ssh: bool,
    disable_ssh: bool,
) -> str:
    if disable_ssh:
        return "no (--disable-ssh)"
    if enable_ssh:
        return "yes (--enable-ssh)"
    if role == "gate":
        return "yes (gate role default)"
    return "no (point role default)"


def resolve_base_image(
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
                "Image URL saved but not downloaded. Re-run with --download to fetch the image, "
                "or add --base-image to use a local file.",
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


def register_flash_command(app: typer.Typer) -> None:
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
            None,
            "--base-image",
            "-i",
            help="Path to OpenMANET base image (.img or .img.gz) — auto-downloaded if omitted",
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
            False,
            "--force",
            help="Override blocking disk safety checks (system disk, large fixed disk, device not in default list)",
        ),
        no_eject: bool = typer.Option(
            False, "--no-eject", help="Do not eject disk after flashing"
        ),
        skip_overlay_wipe: bool = typer.Option(
            False,
            "--skip-overlay-wipe",
            help="Skip wiping stale OpenWrt overlay data after writing the image (not recommended)",
        ),
        enable_ssh: bool = typer.Option(
            False,
            "--enable-ssh",
            help="Enable SSH (dropbear) on this node at first boot.",
        ),
        disable_ssh: bool = typer.Option(
            False,
            "--disable-ssh",
            help="Disable SSH at first boot, including on gate nodes.",
        ),
    ):
        """Flash an OpenMANET image and stage node config on the boot partition."""
        check_platform()
        if enable_ssh and disable_ssh:
            typer.secho(
                "Cannot use --enable-ssh and --disable-ssh together.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        if not yes and not dry_run:
            typer.secho(
                "--yes is required to flash. Use --dry-run to preview first.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        maybe_show_update_notice()

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
        role = resolved["node"]["role"]
        ssh_enabled = resolve_flash_ssh_enabled(
            enable_ssh=enable_ssh, disable_ssh=disable_ssh
        )

        image_path = resolve_base_image(
            target, base_image, image_url, download, no_download, dry_run
        )

        print_header("Flash Plan")
        typer.echo(f"  Config:       {config}")
        typer.echo(f"  Node:         {node}")
        typer.echo(f"  Hostname:     {resolved['node']['hostname']}")
        typer.echo(f"  Role:         {role}")
        typer.echo(f"  Target:       {target}")
        typer.echo(f"  Base image:   {image_path}")
        typer.echo(f"  Device:       {device}")
        typer.echo("  Boot payload: /easymanet/provision.json")
        typer.echo(
            f"  SSH:          {flash_ssh_note(role, enable_ssh=enable_ssh, disable_ssh=disable_ssh)}"
        )
        typer.echo()

        try:
            disk = lookup_device(device)
            if disk:
                typer.echo("  Disk details:")
                typer.echo(f"    Model:      {disk.model}")
                typer.echo(f"    Size:       {disk.size_human}")
                typer.echo(f"    Removable:  {'yes' if disk.removable else 'no'}")
                mounted_str = ", ".join(disk.mounted) if disk.mounted else "(none)"
                typer.echo(f"    Mounted:    {mounted_str}")
                for w in disk.blocking_warnings:
                    typer.secho(f"    {w}", fg=typer.colors.RED)
                typer.echo()
            assert_flash_allowed(device, force=force)
        except ValueError as e:
            typer.secho(f"  Flash safety: {e}", fg=typer.colors.RED)
            if not dry_run:
                raise typer.Exit(1)
            typer.echo()

        print_header("Resolved provision.json")
        print(render(manifest, node, ssh_enabled=ssh_enabled))
        print()

        typer.echo(inject_dry_run_info(manifest, node))
        print()

        if dry_run:
            typer.secho("Dry run complete. No changes were made.", fg=typer.colors.GREEN)
            return

        try:
            check_privileges(device)
        except PrivilegeError as e:
            typer.secho(str(e), fg=typer.colors.RED)
            raise typer.Exit(1)

        try:
            flash_image(
                device=device,
                image_path=image_path,
                force=force,
                skip_overlay_wipe=skip_overlay_wipe,
            )
        except FlashError as e:
            typer.secho(f"Flash error: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)

        typer.echo()
        print_header("Writing boot-partition payload")
        try:
            results = inject(
                device=device,
                manifest=manifest,
                node_name=node,
                ssh_enabled=ssh_enabled,
            )
            for path, ok in results:
                status = "✓" if ok else "✗"
                color = typer.colors.GREEN if ok else typer.colors.RED
                typer.secho(f"  {status} {path}", fg=color)
        except InjectError as e:
            typer.secho(f"Boot payload error: {e}", fg=typer.colors.RED)
            typer.secho(
                "Image was written but boot-partition provisioning failed. "
                "Re-run the full flash command (same --base-image or cached image) after fixing the issue.",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        finish_flash(device, eject=not no_eject)
        typer.secho(
            f"\nDone. Insert the drive into the Raspberry Pi for {node} and boot.",
            fg=typer.colors.GREEN,
        )
