from __future__ import annotations

import json
from pathlib import Path

import typer
from sqlalchemy import func, select

from taxtrace.config import get_settings
from taxtrace.database import SessionLocal
from taxtrace.warehouse_v2.catalog import load_catalog, seed_catalog
from taxtrace.warehouse_v2.census import (
    bootstrap_national_census,
    ingest_finance_zip,
    ingest_government_units_zip,
    inspect_finance_zip,
)
from taxtrace.warehouse_v2.db_models import (
    BulkObject,
    CoverageRecord,
    DatasetDefinition,
    DatasetRelease,
    DetailedSpendFact,
    FinanceClassification,
    GovernmentFinanceFact,
    GovernmentIdentifier,
)
from taxtrace.warehouse_v2.usaspending_bulk import USASpendingBulkClient, load_payload

app = typer.Typer(help="TaxTrace national multi-jurisdiction public-finance warehouse.")


@app.command("catalog")
def catalog() -> None:
    typer.echo(json.dumps(load_catalog(), indent=2))


@app.command("seed")
def seed() -> None:
    with SessionLocal() as session:
        count = seed_catalog(session)
    typer.echo(f"Seeded/updated {count} dataset definitions.")


@app.command("stats")
def stats() -> None:
    models = {
        "datasets": DatasetDefinition, "releases": DatasetRelease,
        "government_identifiers": GovernmentIdentifier,
        "finance_classifications": FinanceClassification,
        "government_finance_facts": GovernmentFinanceFact,
        "detailed_spend_facts": DetailedSpendFact,
        "coverage_records": CoverageRecord, "bulk_objects": BulkObject,
    }
    with SessionLocal() as session:
        result = {name: session.scalar(select(func.count(model.id))) or 0 for name, model in models.items()}
    typer.echo(json.dumps(result, indent=2))


@app.command("inspect-census-finance")
def inspect_census_finance(
    file: Path = typer.Option(..., "--file", exists=True),
    max_records: int | None = typer.Option(None, "--max-records"),
) -> None:
    typer.echo(json.dumps(inspect_finance_zip(file, max_records=max_records), indent=2))


@app.command("ingest-government-units")
def ingest_government_units(file: Path = typer.Option(..., "--file", exists=True)) -> None:
    with SessionLocal() as session:
        result = ingest_government_units_zip(session, file)
    typer.echo(json.dumps(result, indent=2))


@app.command("ingest-census-finance")
def ingest_census_finance(
    file: Path = typer.Option(..., "--file", exists=True),
    year: int = typer.Option(..., "--year"),
    coverage: str = typer.Option("CENSUS", "--coverage"),
    dataset_key: str | None = typer.Option(None, "--dataset-key"),
) -> None:
    with SessionLocal() as session:
        result = ingest_finance_zip(session, file, year=year, coverage_type=coverage.upper(), dataset_key=dataset_key)
    typer.echo(json.dumps(result, indent=2))


@app.command("bootstrap-national")
def bootstrap_national(
    include_2024_sample: bool = typer.Option(True, "--include-2024-sample/--no-2024-sample"),
    overwrite_downloads: bool = typer.Option(False, "--overwrite-downloads"),
) -> None:
    """Download and ingest the national Census government registry and finance baseline."""
    with SessionLocal() as session:
        result = bootstrap_national_census(session, include_2024_sample=include_2024_sample, overwrite_downloads=overwrite_downloads)
    typer.echo(json.dumps(result, indent=2))


@app.command("bootstrap-federal-accounts")
def bootstrap_federal_accounts(
    fiscal_year: int = typer.Option(2025, "--fiscal-year"),
    period: int = typer.Option(12, "--period", min=1, max=12),
    wait: bool = typer.Option(True, "--wait/--no-wait"),
) -> None:
    """Request all-agency USAspending File A/B/C account data for a fiscal year."""
    payload = {
        "account_level": "treasury_account",
        "file_format": "csv",
        "filters": {
            "agency": "all",
            "fy": str(fiscal_year),
            "period": str(period),
            "submission_types": ["account_balances", "object_class_program_activity", "award_financial"],
        },
    }
    client = USASpendingBulkClient()
    job = client.submit("accounts", payload)
    response = client.wait(job) if wait else job.response
    if wait:
        url = response.get("file_url") or response.get("download_url") or response.get("url")
        if url:
            destination = get_settings().raw_data_dir / "usaspending" / str(fiscal_year) / Path(url.split("?", 1)[0]).name
            client.download_completed(response, destination)
            response = {**response, "taxtrace_local_path": str(destination)}
    typer.echo(json.dumps({"request": payload, "response": response}, indent=2))


@app.command("usaspending-submit")
def usaspending_submit(
    kind: str = typer.Option(..., "--kind", help="accounts, awards, search, contracts, assistance"),
    payload: Path = typer.Option(..., "--payload", exists=True, help="Exact USAspending JSON request"),
    wait: bool = typer.Option(False, "--wait"),
) -> None:
    client = USASpendingBulkClient()
    job = client.submit(kind, load_payload(payload))
    response = client.wait(job) if wait else job.response
    typer.echo(json.dumps(response, indent=2))


if __name__ == "__main__":
    app()
