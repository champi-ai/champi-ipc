"""CLI entry point for champi-ipc."""

import click


@click.group()
@click.version_option()
def cli() -> None:
    """champi-ipc — shared memory IPC utilities."""
