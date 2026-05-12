"""Cleanup command for champi-ipc CLI."""

import importlib

import click
from loguru import logger

from champi_ipc.utils.cleanup import cleanup_orphaned_regions, list_regions


@click.command()
@click.option("--prefix", default="champi_ipc", help="Memory region prefix to clean up")
@click.option(
    "--signal-module",
    required=True,
    help="Python module path to signal enum (e.g., my_app.signals.MySignals)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be cleaned without actually cleaning",
)
def cleanup(prefix: str, signal_module: str, dry_run: bool):
    """Clean up orphaned shared memory regions.

    This command removes shared memory regions that were left behind by
    crashed processes or improper shutdowns.

    Example:
        champi-ipc cleanup --prefix my_app --signal-module my_app.signals.MySignals
        champi-ipc cleanup --prefix my_app --signal-module my_app.signals.MySignals --dry-run
    """
    try:
        # Import signal enum
        module_path, class_name = signal_module.rsplit(".", 1)
        module = importlib.import_module(module_path)
        signal_enum = getattr(module, class_name)

        logger.info(f"Cleaning up regions with prefix: {prefix}")

        if dry_run:
            click.echo("🔍 DRY RUN - No actual cleanup will be performed")
            # List regions without cleaning
            regions = list_regions(prefix)
            if regions:
                click.echo(f"\nWould clean {len(regions)} regions:")
                for region in regions:
                    click.echo(f"  • {region}")
            else:
                click.echo("\n✅ No regions found to clean")
        else:
            cleaned = cleanup_orphaned_regions(prefix, signal_enum)

            if cleaned:
                click.echo(f"\n✅ Cleaned {len(cleaned)} regions:")
                for region in cleaned:
                    click.echo(f"  • {region}")
            else:
                click.echo("\n✅ No orphaned regions found")

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        click.echo(f"❌ Error: {e}", err=True)
        raise click.Abort() from e
