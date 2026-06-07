"""Command line interface for generated public surface exports."""

from pathlib import Path
from typing import Optional

import typer

from .export import EXPORT_RECORD, export_public_surfaces

app = typer.Typer(
    name="easymanet-publish",
    help="Export generated EasyMANET public product surfaces",
    no_args_is_help=True,
)


@app.callback()
def publish_root() -> None:
    """Export generated EasyMANET public product surfaces."""


@app.command(name="export")
def export_cmd(
    output_dir: str = typer.Option(
        "dist/public-surfaces",
        "--output-dir",
        "-o",
        help="Directory for generated public surfaces",
    ),
    source_ref: Optional[str] = typer.Option(
        None,
        "--source-ref",
        help="Monorepo source commit or ref to record",
    ),
    clean: bool = typer.Option(
        False,
        "--clean",
        help="Remove the output directory before exporting",
    ),
) -> None:
    """Generate local public surface directories without setting up subrepos."""
    record = export_public_surfaces(
        Path(output_dir),
        source_ref=source_ref,
        clean=clean,
    )
    typer.secho("Exported EasyMANET public surfaces.", fg=typer.colors.GREEN)
    for name, surface in record["surfaces"].items():
        typer.echo(f"  {name}: {surface['path']}")
    typer.echo(f"  record: {record['record_path']} ({EXPORT_RECORD})")
