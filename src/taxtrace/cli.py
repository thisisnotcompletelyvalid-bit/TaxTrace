from __future__ import annotations

import json
from decimal import Decimal

import typer
from sqlalchemy import func, select

from taxtrace.allocation.engine import FederalAllocationEngine
from taxtrace.allocation.models import FederalReceiptRequest
from taxtrace.database import Base, SessionLocal, engine
from taxtrace.db_models import Agency, Award, SearchDocument, SourceSnapshot, SpendFact, TreasuryAggregate
from taxtrace.enums import FilingStatus, SourceKind
from taxtrace.finance.fixtures import ingest_all_fixtures
from taxtrace.finance.reconcile import reconcile_omb_outlays_to_treasury
from taxtrace.finance.seed import seed_federal_methodology_entities
from taxtrace.finance.sources.omb import OMBPublicBudgetDatabaseSource
from taxtrace.finance.sources.treasury import TreasuryCombinedStatementSource
from taxtrace.finance.sources.usaspending import USASpendingSource
from taxtrace.methodology.invariants import validate_revenue_pool_shares
from taxtrace.search import rebuild_search_index, search as search_index
from taxtrace.tax.engine import FederalTaxEngine
from taxtrace.tax.models import FederalTaxInput
from taxtrace.warehouse_v2.cli import app as data_app

app = typer.Typer(help="TaxTrace tax-attribution and national public-finance command line interface.")
db_app = typer.Typer(help="Database commands")
tax_app = typer.Typer(help="Tax-engine commands")
warehouse_app = typer.Typer(help="Legacy federal finance warehouse commands")
search_app = typer.Typer(help="Search-index commands")
receipt_app = typer.Typer(help="Federal receipt commands")
app.add_typer(db_app, name="db")
app.add_typer(tax_app, name="tax")
app.add_typer(warehouse_app, name="warehouse")
app.add_typer(data_app, name="data")
app.add_typer(search_app, name="search")
app.add_typer(receipt_app, name="receipt")


@db_app.command("init")
def db_init() -> None:
    """Create all tables directly. Alembic is preferred for production; this is convenient locally."""
    Base.metadata.create_all(engine)
    typer.echo("Database tables created.")


@warehouse_app.command("seed")
def warehouse_seed(year: int = 2026) -> None:
    with SessionLocal() as session:
        seed_federal_methodology_entities(session)
        problems = validate_revenue_pool_shares(session, year)
        if problems:
            raise typer.Exit(code=1)
    typer.echo("Federal jurisdictions, funding pools, revenue types, and mappings seeded.")


@warehouse_app.command("ingest-fixtures")
def warehouse_ingest_fixtures() -> None:
    with SessionLocal() as session:
        counts = ingest_all_fixtures(session)
        counts["search_documents"] = rebuild_search_index(session)
    typer.echo(json.dumps(counts, indent=2))


@warehouse_app.command("ingest-treasury")
def warehouse_ingest_treasury(fiscal_year: int = 2025) -> None:
    with SessionLocal() as session:
        count = TreasuryCombinedStatementSource().ingest(session, fiscal_year)
    typer.echo(f"Loaded {count} Treasury summary rows for FY{fiscal_year}.")


@warehouse_app.command("ingest-omb")
def warehouse_ingest_omb(fiscal_year: int = 2025) -> None:
    with SessionLocal() as session:
        count = OMBPublicBudgetDatabaseSource().ingest(session, fiscal_year)
        rebuild_search_index(session)
    typer.echo(f"Loaded {count} OMB PBD rows for FY{fiscal_year} and rebuilt search.")


@warehouse_app.command("ingest-usaspending")
def warehouse_ingest_usaspending(
    fiscal_year: int = 2025,
    agency: list[str] | None = typer.Option(None, "--agency", help="Repeatable toptier agency code"),
    all_agencies: bool = typer.Option(False, "--all-agencies", help="Ingest every toptier agency"),
    include_awards: bool = typer.Option(
        False, "--include-awards", help="Also ingest account-filtered award/recipient detail"
    ),
) -> None:
    if not all_agencies and not agency:
        raise typer.BadParameter("Pass at least one --agency CODE or --all-agencies")
    with SessionLocal() as session:
        count = USASpendingSource().ingest(
            session,
            fiscal_year=fiscal_year,
            agency_codes=None if all_agencies else agency,
            include_awards=include_awards,
        )
        rebuild_search_index(session)
    typer.echo(f"Loaded {count} USAspending facts/award records for FY{fiscal_year}.")


@warehouse_app.command("reconcile")
def warehouse_reconcile(fiscal_year: int = 2025) -> None:
    with SessionLocal() as session:
        result = reconcile_omb_outlays_to_treasury(session, fiscal_year)
    typer.echo(
        json.dumps(
            {
                "comparison": result.comparison_name,
                "left": str(result.left_value),
                "right": str(result.right_value),
                "absolute_difference": str(result.absolute_difference),
                "relative_difference": str(result.relative_difference),
                "status": result.status,
            },
            indent=2,
        )
    )


@warehouse_app.command("status")
def warehouse_status() -> None:
    with SessionLocal() as session:
        snapshots = session.scalar(select(func.count(SourceSnapshot.id))) or 0
        facts = session.scalar(select(func.count(SpendFact.id))) or 0
        agencies = session.scalar(select(func.count(Agency.id))) or 0
        treasury_rows = session.scalar(select(func.count(TreasuryAggregate.id))) or 0
        awards = session.scalar(select(func.count(Award.id))) or 0
        search_documents = session.scalar(select(func.count(SearchDocument.id))) or 0
        by_source = {
            kind.value: session.scalar(
                select(func.count(SourceSnapshot.id)).where(SourceSnapshot.source_kind == kind)
            )
            or 0
            for kind in SourceKind
        }
    typer.echo(
        json.dumps(
            {
                "source_snapshots": snapshots,
                "spend_facts": facts,
                "agencies": agencies,
                "treasury_aggregate_rows": treasury_rows,
                "awards": awards,
                "search_documents": search_documents,
                "snapshots_by_source": by_source,
            },
            indent=2,
        )
    )


@tax_app.command("federal")
def tax_federal(
    income: str = typer.Option(..., "--income"),
    filing_status: FilingStatus = typer.Option(FilingStatus.SINGLE, "--filing-status"),
    spouse_income: str = typer.Option("0", "--spouse-income"),
    qualifying_children: int = typer.Option(0, "--qualifying-children"),
    other_dependents: int = typer.Option(0, "--other-dependents"),
    tax_year: int = typer.Option(2026, "--tax-year"),
) -> None:
    result = FederalTaxEngine().calculate(
        FederalTaxInput(
            tax_year=tax_year,
            filing_status=filing_status,
            wage_income=Decimal(income),
            spouse_wage_income=Decimal(spouse_income),
            qualifying_children_under_17=qualifying_children,
            other_dependents=other_dependents,
        )
    )
    typer.echo(result.model_dump_json(indent=2))


@search_app.command("rebuild")
def search_rebuild() -> None:
    with SessionLocal() as session:
        count = rebuild_search_index(session)
    typer.echo(f"Indexed {count} searchable entities.")


@search_app.command("query")
def search_query(q: str, limit: int = 20) -> None:
    with SessionLocal() as session:
        response = search_index(session, q, limit=limit)
    typer.echo(response.model_dump_json(indent=2))


@receipt_app.command("federal")
def receipt_federal(
    income: str = typer.Option(..., "--income"),
    filing_status: FilingStatus = typer.Option(FilingStatus.SINGLE, "--filing-status"),
    spouse_income: str = typer.Option("0", "--spouse-income"),
    qualifying_children: int = typer.Option(0, "--qualifying-children"),
    other_dependents: int = typer.Option(0, "--other-dependents"),
    tax_year: int = typer.Option(2026, "--tax-year"),
    spending_fiscal_year: int = typer.Option(2025, "--spending-fiscal-year"),
) -> None:
    request = FederalReceiptRequest(
        tax_year=tax_year,
        filing_status=filing_status,
        wage_income=Decimal(income),
        spouse_wage_income=Decimal(spouse_income),
        qualifying_children_under_17=qualifying_children,
        other_dependents=other_dependents,
        spending_fiscal_year=spending_fiscal_year,
    )
    with SessionLocal() as session:
        result = FederalAllocationEngine().calculate(session, request)
    typer.echo(result.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
