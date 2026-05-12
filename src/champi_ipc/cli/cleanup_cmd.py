"""Cleanup command for champi-ipc CLI."""

from __future__ import annotations

import importlib
import sys

import click

from champi_ipc.utils.cleanup import cleanup_orphaned_regions, list_regions


@click.command("cleanup")
@click.option(
    "--prefix",
    default="champi_",
    show_default=True,
    help="Filter shared memory regions by name prefix.",
)
@click.option(
    "--signal-module",
    "signal_module",
    default=None,
    help="Dotted path of a module to import for custom struct resolution.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List matching regions without removing them.",
)
def cleanup(prefix: str, signal_module: str | None, dry_run: bool) -> None:
    """Remove orphaned shared memory regions matching PREFIX."""
    if signal_module is not None:
        try:
            importlib.import_module(signal_module)
        except ImportError as exc:
            click.secho(
                f"Error: cannot import module {signal_module!r}: {exc}",
                fg="red",
                err=True,
            )
            sys.exit(1)

    if dry_run:
        regions = list_regions(prefix)
        if not regions:
            click.secho("No matching regions found.", fg="green")
            return
        click.echo(f"Would remove {len(regions)} region(s):")
        for name in regions:
            click.secho(f"  {name}", fg="green")
        return

    result = cleanup_orphaned_regions(prefix)

    if len(result.removed) > 0:
        click.secho(f"Removed {len(result.removed)} region(s):", fg="green")
        for name in result.removed:
            click.secho(f"  {name}", fg="green")
    else:
        click.secho("No regions removed.", fg="green")

    if len(result.failed) > 0:
        click.secho(
            f"Failed to remove {len(result.failed)} region(s):", fg="red", err=True
        )
        for name in result.failed:
            click.secho(f"  {name}", fg="red", err=True)
        sys.exit(1)
