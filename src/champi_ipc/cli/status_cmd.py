"""Status command for champi-ipc CLI."""

import json

import click
from loguru import logger

from champi_ipc.utils.cleanup import get_region_info, list_regions


@click.command()
@click.option("--prefix", default="champi_ipc", help="Memory region prefix to check")
@click.option("--json", "output_json", is_flag=True, help="Output in JSON format")
def status(prefix: str, output_json: bool):
    """Show status of shared memory regions.

    This command lists all shared memory regions with the specified prefix
    and displays their status (size, accessibility).

    Example:
        champi-ipc status --prefix my_app
        champi-ipc status --prefix my_app --json
    """
    try:
        regions = list_regions(prefix)

        if not regions:
            click.echo(f"✅ No regions found with prefix: {prefix}")
            return

        # Gather info for each region
        region_info = []
        for region_name in regions:
            info = get_region_info(region_name)
            region_info.append(info)

        if output_json:
            click.echo(json.dumps(region_info, indent=2))
        else:
            click.echo(f"\n📊 Shared Memory Regions (prefix: {prefix})\n")
            click.echo(f"{'Region Name':<40} {'Size':<12} {'Status':<12}")
            click.echo("=" * 64)

            for info in region_info:
                name = info["name"]
                size = f"{info['size']} bytes" if info["size"] > 0 else "N/A"

                if info["exists"] and info["accessible"]:
                    status_icon = "✅ Active"
                elif info["exists"]:
                    status_icon = "⚠️  No Access"
                else:
                    status_icon = "❌ Missing"

                click.echo(f"{name:<40} {size:<12} {status_icon}")

            click.echo(f"\nTotal regions: {len(region_info)}")

    except Exception as e:
        logger.error(f"Status check failed: {e}")
        click.echo(f"❌ Error: {e}", err=True)
        raise click.Abort() from e
