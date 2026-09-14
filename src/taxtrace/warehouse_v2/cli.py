from __future__ import annotations

import json
from datetime import date
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
from taxtrace.warehouse_v2.census_lake import materialize_finance_parquet
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
from taxtrace.warehouse_v2.usaspending_award_lake import (
    inspect_award_archive,
    materialize_award_archive,
)
from taxtrace.warehouse_v2.usaspending_awards import (
    materialize_requested_awards,
    request_award_archive,
)
from taxtrace.warehouse_v2.usaspending_bulk import USASpendingBulkClient, load_payload
from taxtrace.warehouse_v2.usaspending_lake import (
    inspect_account_archive,
    materialize_account_archive,
)

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
        "datasets": DatasetDefinition,
        "releases": DatasetRelease,
        "government_identifiers": GovernmentIdentifier,
        "finance_classifications": FinanceClassification,
        "government_finance_facts": GovernmentFinanceFact,
        "detailed_spend_facts": DetailedSpendFact,
        "coverage_records": CoverageRecord,
        "bulk_objects": BulkObject,
    }
    with SessionLocal() as session:
        result = {
            name: session.scalar(select(func.count(model.id))) or 0
            for name, model in models.items()
        }
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
    materialize_parquet: bool = typer.Option(
        True, "--materialize-parquet/--no-materialize-parquet"
    ),
) -> None:
    resolved_key = dataset_key or f"census-gov-finance-{year}"
    with SessionLocal() as session:
        result = ingest_finance_zip(
            session,
            file,
            year=year,
            coverage_type=coverage.upper(),
            dataset_key=resolved_key,
        )
        if materialize_parquet:
            result["parquet"] = materialize_finance_parquet(
                session,
                file,
                dataset_key=resolved_key,
                year=year,
            )
    typer.echo(json.dumps(result, indent=2))


@app.command("materialize-census-finance")
def materialize_census_finance(
    file: Path = typer.Option(..., "--file", exists=True),
    year: int = typer.Option(..., "--year"),
    dataset_key: str | None = typer.Option(None, "--dataset-key"),
) -> None:
    resolved_key = dataset_key or f"census-gov-finance-{year}"
    with SessionLocal() as session:
        result = materialize_finance_parquet(
            session,
            file,
            dataset_key=resolved_key,
            year=year,
        )
    typer.echo(json.dumps(result, indent=2))


@app.command("bootstrap-national")
def bootstrap_national(
    include_2024_sample: bool = typer.Option(
        True, "--include-2024-sample/--no-2024-sample"
    ),
    overwrite_downloads: bool = typer.Option(False, "--overwrite-downloads"),
    materialize_parquet: bool = typer.Option(
        True, "--materialize-parquet/--no-materialize-parquet"
    ),
) -> None:
    """Download and ingest the Census national registry + finance baseline and lake copies."""
    settings = get_settings()
    with SessionLocal() as session:
        result = bootstrap_national_census(
            session,
            include_2024_sample=include_2024_sample,
            overwrite_downloads=overwrite_downloads,
        )
        if materialize_parquet:
            result["government_finance_2022"]["parquet"] = materialize_finance_parquet(
                session,
                settings.raw_data_dir
                / "census"
                / "gov_finance"
                / "2022_Individual_Unit_File.zip",
                dataset_key="census-gov-finance-2022",
                year=2022,
            )
            if include_2024_sample:
                result["government_finance_2024"]["parquet"] = materialize_finance_parquet(
                    session,
                    settings.raw_data_dir
                    / "census"
                    / "gov_finance"
                    / "2024_Individual_Unit_Files.zip",
                    dataset_key="census-gov-finance-2024",
                    year=2024,
                )
    typer.echo(json.dumps(result, indent=2))


@app.command("inspect-usaspending-accounts")
def inspect_usaspending_accounts(
    file: Path = typer.Option(..., "--file", exists=True),
) -> None:
    members = inspect_account_archive(file)
    typer.echo(
        json.dumps(
            [
                {
                    "member": member.member_name,
                    "submission_type": member.submission_type,
                    "dataset_key": member.dataset_key,
                    "columns": list(member.columns),
                }
                for member in members
            ],
            indent=2,
        )
    )


@app.command("ingest-usaspending-accounts")
def ingest_usaspending_accounts(
    file: Path = typer.Option(..., "--file", exists=True),
    fiscal_year: int = typer.Option(..., "--fiscal-year"),
    request_json: Path | None = typer.Option(
        None, "--request-json", exists=True, help="Optional exact USAspending request JSON"
    ),
) -> None:
    request = json.loads(request_json.read_text()) if request_json else None
    with SessionLocal() as session:
        seed_catalog(session)
        result = materialize_account_archive(
            session,
            file,
            fiscal_year=fiscal_year,
            request=request,
        )
    typer.echo(json.dumps(result, indent=2))


@app.command("bootstrap-federal-accounts")
def bootstrap_federal_accounts(
    fiscal_year: int = typer.Option(2025, "--fiscal-year"),
    period: int = typer.Option(12, "--period", min=1, max=12),
    wait: bool = typer.Option(True, "--wait/--no-wait"),
) -> None:
    """Request, download, and normalize all-agency USAspending File A/B/C account data."""
    payload = {
        "account_level": "treasury_account",
        "file_format": "csv",
        "filters": {
            "agency": "all",
            "fy": str(fiscal_year),
            "period": str(period),
            "submission_types": [
                "account_balances",
                "object_class_program_activity",
                "award_financial",
            ],
        },
    }
    client = USASpendingBulkClient()
    job = client.submit("accounts", payload)
    response = client.wait(job) if wait else job.response
    result: dict[str, object] = {"request": payload, "response": response}
    if wait:
        url = response.get("file_url") or response.get("download_url") or response.get("url")
        if url:
            destination = (
                get_settings().raw_data_dir
                / "usaspending"
                / str(fiscal_year)
                / Path(url.split("?", 1)[0]).name
            )
            client.download_completed(response, destination)
            with SessionLocal() as session:
                seed_catalog(session)
                result["warehouse"] = materialize_account_archive(
                    session,
                    destination,
                    fiscal_year=fiscal_year,
                    request=payload,
                )
            result["response"] = {**response, "taxtrace_local_path": str(destination)}
    typer.echo(json.dumps(result, indent=2))


@app.command("inspect-usaspending-awards")
def inspect_usaspending_awards(
    file: Path = typer.Option(..., "--file", exists=True),
) -> None:
    members = inspect_award_archive(file)
    typer.echo(
        json.dumps(
            [
                {
                    "member": member.member_name,
                    "data_class": member.data_class,
                    "dataset_key": member.dataset_key,
                    "award_family": member.award_family,
                    "columns": list(member.columns),
                }
                for member in members
            ],
            indent=2,
        )
    )


@app.command("ingest-usaspending-awards")
def ingest_usaspending_awards(
    file: Path = typer.Option(..., "--file", exists=True),
    fiscal_year: int = typer.Option(..., "--fiscal-year"),
    request_json: Path | None = typer.Option(
        None, "--request-json", exists=True, help="Optional exact USAspending request JSON"
    ),
) -> None:
    request = json.loads(request_json.read_text()) if request_json else None
    with SessionLocal() as session:
        seed_catalog(session)
        result = materialize_award_archive(
            session,
            file,
            fiscal_year=fiscal_year,
            request=request,
        )
    typer.echo(json.dumps(result, indent=2))


@app.command("bootstrap-federal-awards")
def bootstrap_federal_awards(
    fiscal_year: int = typer.Option(2025, "--fiscal-year"),
    agency: str = typer.Option(
        "all",
        "--agency",
        help="USAspending toptier agency ID, or 'all' for the whole federal government",
    ),
    include_prime_awards: bool = typer.Option(
        True, "--prime-awards/--no-prime-awards"
    ),
    include_subawards: bool = typer.Option(True, "--subawards/--no-subawards"),
    start_date: date | None = typer.Option(
        None, "--start-date", help="Optional YYYY-MM-DD date within the fiscal year"
    ),
    end_date: date | None = typer.Option(
        None, "--end-date", help="Optional YYYY-MM-DD date within the fiscal year"
    ),
    wait: bool = typer.Option(True, "--wait/--no-wait"),
) -> None:
    """Request USAspending D1/D2 prime awards and/or File F subawards."""
    agency_value: int | str = int(agency) if agency.isdigit() else agency
    result = request_award_archive(
        fiscal_year,
        agency=agency_value,
        include_prime_awards=include_prime_awards,
        include_subawards=include_subawards,
        start_date=start_date,
        end_date=end_date,
        wait=wait,
    )
    if wait:
        with SessionLocal() as session:
            result["warehouse"] = materialize_requested_awards(
                session,
                result,
                fiscal_year=fiscal_year,
            )
    typer.echo(json.dumps(result, indent=2))


@app.command("usaspending-submit")
def usaspending_submit(
    kind: str = typer.Option(
        ...,
        "--kind",
        help="accounts, awards, bulk_awards, search, contracts, assistance",
    ),
    payload: Path = typer.Option(..., "--payload", exists=True, help="Exact USAspending JSON request"),
    wait: bool = typer.Option(False, "--wait"),
) -> None:
    client = USASpendingBulkClient()
    job = client.submit(kind, load_payload(payload))
    response = client.wait(job) if wait else job.response
    typer.echo(json.dumps(response, indent=2))


if __name__ == "__main__":
    app()
