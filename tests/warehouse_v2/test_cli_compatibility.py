from typer.testing import CliRunner

from taxtrace.cli import app

runner = CliRunner()


def test_top_level_cli_builds_with_warehouse_v2_date_options() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "warehouse" in result.output
    assert "data" in result.output


def test_federal_award_subcommand_help_constructs_without_date_type_crash() -> None:
    result = runner.invoke(app, ["data", "bootstrap-federal-awards", "--help"])
    assert result.exit_code == 0, result.output
    assert "Request USAspending D1/D2 prime awards" in result.output
