"""Status command for champi-ipc CLI."""

from __future__ import annotations

import datetime
import json
import os
import platform

import click

from champi_ipc.utils.cleanup import get_region_info, list_regions


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size //= 1024
    return f"{size:.1f} TB"


def _last_modified(region_name: str) -> str:
    if platform.system() != "Linux":
        return "-"
    path = os.path.join("/dev/shm", region_name)
    try:
        mtime = os.path.getmtime(path)
        return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return "-"


@click.command("status")
@click.option(
    "--prefix",
    default="champi_",
    show_default=True,
    help="Filter regions by name prefix.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Output as JSON array.",
)
def status(prefix: str, as_json: bool) -> None:
    """Show active shared memory regions matching PREFIX."""
    names = list_regions(prefix)

    if not names:
        click.echo("No regions found")
        return

    rows: list[dict[str, str | int]] = []
    for name in names:
        info = get_region_info(name)
        size = info["size"]
        rows.append(
            {
                "name": name,
                "size": int(size) if isinstance(size, (int, float)) else 0,
                "last_modified": _last_modified(name),
            }
        )

    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return

    col_name = max(len(str(r["name"])) for r in rows)
    col_name = max(col_name, 4)
    header = f"{'NAME':<{col_name}}  {'SIZE':>10}  LAST MODIFIED"
    click.echo(header)
    click.echo("-" * len(header))
    for row in rows:
        size_val = row["size"]
        size_str = _human_size(size_val) if isinstance(size_val, int) else "?"
        click.echo(
            f"{row['name']!s:<{col_name}}  {size_str:>10}  {row['last_modified']}"
        )
