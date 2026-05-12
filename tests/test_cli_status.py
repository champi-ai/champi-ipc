"""Tests for the `champi-ipc status` CLI command."""

from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner

from champi_ipc.cli.main import cli


def _make_info(name: str, size: int) -> dict[str, object]:
    return {"name": name, "exists": True, "size": size}


class TestStatusCommand:
    """Tests for the status subcommand."""

    def test_no_regions_prints_clear_message(self) -> None:
        runner = CliRunner()
        with patch("champi_ipc.cli.status_cmd.list_regions", return_value=[]):
            result = runner.invoke(cli, ["status", "--prefix", "test_"])
        assert result.exit_code == 0
        assert "No regions found" in result.output

    def test_table_output_contains_region_name(self) -> None:
        runner = CliRunner()
        regions = ["test_region_a", "test_region_b"]
        infos = {r: _make_info(r, 1024) for r in regions}
        with (
            patch("champi_ipc.cli.status_cmd.list_regions", return_value=regions),
            patch(
                "champi_ipc.cli.status_cmd.get_region_info",
                side_effect=lambda n: infos[n],
            ),
            patch("champi_ipc.cli.status_cmd._last_modified", return_value="-"),
        ):
            result = runner.invoke(cli, ["status", "--prefix", "test_"])
        assert result.exit_code == 0
        assert "test_region_a" in result.output
        assert "test_region_b" in result.output

    def test_table_output_contains_size_column(self) -> None:
        runner = CliRunner()
        regions = ["test_region_a"]
        with (
            patch("champi_ipc.cli.status_cmd.list_regions", return_value=regions),
            patch(
                "champi_ipc.cli.status_cmd.get_region_info",
                return_value=_make_info("test_region_a", 2048),
            ),
            patch("champi_ipc.cli.status_cmd._last_modified", return_value="-"),
        ):
            result = runner.invoke(cli, ["status", "--prefix", "test_"])
        assert result.exit_code == 0
        assert "SIZE" in result.output

    def test_json_output_is_valid_json(self) -> None:
        runner = CliRunner()
        regions = ["test_region_a"]
        with (
            patch("champi_ipc.cli.status_cmd.list_regions", return_value=regions),
            patch(
                "champi_ipc.cli.status_cmd.get_region_info",
                return_value=_make_info("test_region_a", 4096),
            ),
            patch(
                "champi_ipc.cli.status_cmd._last_modified",
                return_value="2026-01-01 00:00:00",
            ),
        ):
            result = runner.invoke(cli, ["status", "--prefix", "test_", "--json"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "test_region_a"
        assert parsed[0]["size"] == 4096

    def test_json_empty_no_regions(self) -> None:
        runner = CliRunner()
        with patch("champi_ipc.cli.status_cmd.list_regions", return_value=[]):
            result = runner.invoke(cli, ["status", "--json"])
        assert result.exit_code == 0
        assert "No regions found" in result.output

    def test_default_prefix_is_champi(self) -> None:
        runner = CliRunner()
        with patch(
            "champi_ipc.cli.status_cmd.list_regions", return_value=[]
        ) as mock_list:
            runner.invoke(cli, ["status"])
        mock_list.assert_called_once_with("champi_")
