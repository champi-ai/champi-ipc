"""Tests for the champi-ipc cleanup CLI command."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from champi_ipc.cli.main import cli
from champi_ipc.utils.cleanup import CleanupResult


def test_cleanup_dry_run_no_regions() -> None:
    """Dry-run with no matching regions prints a message and exits 0."""
    runner = CliRunner()
    with patch("champi_ipc.cli.cleanup_cmd.list_regions", return_value=[]):
        result = runner.invoke(cli, ["cleanup", "--dry-run", "--prefix", "test_"])
    assert result.exit_code == 0
    assert "No matching regions found" in result.output


def test_cleanup_dry_run_lists_regions() -> None:
    """Dry-run with matching regions lists them without removing."""
    runner = CliRunner()
    regions = ["test_alpha", "test_beta"]
    with patch("champi_ipc.cli.cleanup_cmd.list_regions", return_value=regions):
        result = runner.invoke(cli, ["cleanup", "--dry-run", "--prefix", "test_"])
    assert result.exit_code == 0
    assert "Would remove 2 region(s)" in result.output
    assert "test_alpha" in result.output
    assert "test_beta" in result.output


def test_cleanup_removes_regions() -> None:
    """Live run calls cleanup_orphaned_regions and reports removals."""
    runner = CliRunner()
    mock_result = CleanupResult(removed=["test_alpha", "test_beta"], failed=[])
    with patch("champi_ipc.cli.cleanup_cmd.cleanup_orphaned_regions", return_value=mock_result):
        result = runner.invoke(cli, ["cleanup", "--prefix", "test_"])
    assert result.exit_code == 0
    assert "Removed 2 region(s)" in result.output
    assert "test_alpha" in result.output
    assert "test_beta" in result.output


def test_cleanup_exits_1_on_failures() -> None:
    """Live run exits with code 1 when any region fails to be removed."""
    runner = CliRunner()
    mock_result = CleanupResult(removed=["test_alpha"], failed=["test_broken"])
    with patch("champi_ipc.cli.cleanup_cmd.cleanup_orphaned_regions", return_value=mock_result):
        result = runner.invoke(cli, ["cleanup", "--prefix", "test_"])
    assert result.exit_code == 1
    assert "Removed 1 region(s)" in result.output
    assert "Failed to remove 1 region(s)" in result.output
    assert "test_broken" in result.output


def test_cleanup_no_regions_removed() -> None:
    """Live run with no matching regions prints appropriate message."""
    runner = CliRunner()
    mock_result = CleanupResult(removed=[], failed=[])
    with patch("champi_ipc.cli.cleanup_cmd.cleanup_orphaned_regions", return_value=mock_result):
        result = runner.invoke(cli, ["cleanup", "--prefix", "test_"])
    assert result.exit_code == 0
    assert "No regions removed" in result.output


def test_cleanup_invalid_signal_module() -> None:
    """Invalid --signal-module exits with code 1 and a human-readable error."""
    runner = CliRunner()
    result = runner.invoke(cli, ["cleanup", "--signal-module", "no.such.module.ever"])
    assert result.exit_code == 1
    assert "cannot import module" in result.output


def test_help_output() -> None:
    """champi-ipc --help exits 0 and includes subcommand listing."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "cleanup" in result.output


def test_cleanup_help() -> None:
    """champi-ipc cleanup --help exits 0."""
    runner = CliRunner()
    result = runner.invoke(cli, ["cleanup", "--help"])
    assert result.exit_code == 0
    assert "--prefix" in result.output
    assert "--dry-run" in result.output
    assert "--signal-module" in result.output
