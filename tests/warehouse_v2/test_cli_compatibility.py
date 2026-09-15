from typer.testing import CliRunner

from taxtrace.cli import app

runner = CliRunner()


def test_top_level_cli_builds_with_warehouse_v2_date_options() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "warehouse" in result.output
    assert "data" in result.output


def test_federal_award_date_options_are_strings_at_cli_boundary() -> None:
    result = runner.invoke(app, ["data", "bootstrap-federal-awards", "--help"])
    assert result.exit_code == 0, result.output
    assert "--start-date" in result.output
    assert "--end-date" in result.output
