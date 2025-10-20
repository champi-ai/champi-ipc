"""champi-ipc CLI - Command-line interface for IPC utilities."""

import click

from champi_ipc.cli.cleanup_cmd import cleanup
from champi_ipc.cli.status_cmd import status


@click.group()
@click.version_option(version="0.1.0", prog_name="champi-ipc")
def cli():
    """champi-ipc CLI - Shared memory IPC utilities.

    Tools for managing and debugging shared memory regions used by champi-ipc.
    """
    pass


cli.add_command(cleanup)
cli.add_command(status)


if __name__ == "__main__":
    cli()
