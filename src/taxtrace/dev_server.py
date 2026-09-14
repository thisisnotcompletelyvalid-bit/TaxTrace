from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import and_, func, or_, select

from taxtrace.config import PROJECT_ROOT, get_settings
from taxtrace.database import SessionLocal
from taxtrace.db_models import Award, OMBAccountRecord, SearchDocument, SpendFact, TreasuryAggregate
from taxtrace.finance.fixtures import ingest_all_fixtures
from taxtrace.finance.reconcile import reconcile_omb_outlays_to_treasury
from taxtrace.finance.seed import seed_federal_methodology_entities
from taxtrace.jurisdictional.db_models import JurisdictionSpendFact
from taxtrace.methodology.invariants import validate_revenue_pool_shares
from taxtrace.search import rebuild_search_index


def _alembic_config() -> AlembicConfig:
    config_path = PROJECT_ROOT / "alembic.ini"
    config = AlembicConfig(str(config_path))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("prepend_sys_path", str(PROJECT_ROOT))
    return config


def _warehouse_counts() -> dict[str, int]:
    with SessionLocal() as session:
        phase46_detail = session.scalar(
            select(func.count(OMBAccountRecord.id)).where(
                OMBAccountRecord.fiscal_year == 2025,
                or_(
                    and_(OMBAccountRecord.agency_code == "012", OMBAccountRecord.account_code == "3505"),
                    and_(OMBAccountRecord.agency_code == "009", OMBAccountRecord.account_code == "5700"),
                ),
            )
        ) or 0
        return {
            "treasury_rows": session.scalar(
                select(func.count(TreasuryAggregate.id)).where(TreasuryAggregate.fiscal_year == 2025)
            )
            or 0,
            "omb_rows": session.scalar(
                select(func.count(OMBAccountRecord.id)).where(OMBAccountRecord.fiscal_year == 2025)
            )
            or 0,
            "phase46_omb_detail_rows": phase46_detail,
            "awards": session.scalar(
                select(func.count(Award.id)).where(Award.fiscal_year == 2025)
            )
            or 0,
            "search_documents": session.scalar(select(func.count(SearchDocument.id))) or 0,
            "program_activity_facts": session.scalar(
                select(func.count(SpendFact.id)).where(
                    SpendFact.fiscal_year == 2025,
                    SpendFact.record_scope == "usaspending_account_program_activity",
                )
            )
            or 0,
            "jurisdiction_spend_facts": session.scalar(
                select(func.count(JurisdictionSpendFact.id)).where(
                    JurisdictionSpendFact.fiscal_year == 2025
                )
            )
            or 0,
        }


def _fixture_layer_complete(counts: dict[str, int]) -> bool:
    return (
        counts["treasury_rows"] >= 32
        and counts["omb_rows"] >= 1
        and counts["phase46_omb_detail_rows"] >= 2
        and counts["awards"] >= 2
        and counts["search_documents"] >= 40
        and counts["program_activity_facts"] >= 1
        and counts["jurisdiction_spend_facts"] >= 16
    )


def bootstrap_local_database(*, refresh_fixtures: bool = False) -> dict[str, object]:
    settings = get_settings()
    command.upgrade(_alembic_config(), "head")

    with SessionLocal() as session:
        seed_federal_methodology_entities(session)
        share_problems = validate_revenue_pool_shares(session, 2026)
        if share_problems:
            raise RuntimeError(
                "Revenue-to-pool methodology validation failed: " + "; ".join(share_problems)
            )

    before = _warehouse_counts()
    refreshed = refresh_fixtures or not _fixture_layer_complete(before)
    if refreshed:
        with SessionLocal() as session:
            ingest_all_fixtures(session, root=PROJECT_ROOT / "data" / "fixtures")
            rebuild_search_index(session)

    after = _warehouse_counts()
    if not _fixture_layer_complete(after):
        raise RuntimeError(
            "The local warehouse is still incomplete after bootstrap. "
            f"Observed counts: {after}"
        )

    with SessionLocal() as session:
        reconciliation = reconcile_omb_outlays_to_treasury(session, 2025)
    if reconciliation.status != "PASS":
        raise RuntimeError(
            "FY2025 OMB/Treasury reconciliation failed: "
            f"left={reconciliation.left_value}, right={reconciliation.right_value}, "
            f"difference={reconciliation.absolute_difference}"
        )

    return {
        "status": "ready",
        "project_root": str(PROJECT_ROOT),
        "database_url": settings.database_url,
        "fixture_refresh_performed": refreshed,
        "warehouse": after,
        "reconciliation": {
            "status": reconciliation.status,
            "left": str(reconciliation.left_value),
            "right": str(reconciliation.right_value),
            "difference": str(reconciliation.absolute_difference),
        },
    }


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap and run the TaxTrace FastAPI backend for local development."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Enable Uvicorn source reload.")
    parser.add_argument(
        "--refresh-fixtures",
        action="store_true",
        help="Force deterministic federal + state/local fixture refresh before starting the API.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Migrate/bootstrap/verify the backend and exit without starting Uvicorn.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = bootstrap_local_database(refresh_fixtures=args.refresh_fixtures)
    except Exception as exc:
        print(f"TaxTrace backend bootstrap failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2))
    if args.check_only:
        return 0

    if _port_in_use(args.host, args.port):
        print(
            f"TaxTrace cannot start because {args.host}:{args.port} is already in use. "
            "Stop the existing process, or check whether an API is already running there.",
            file=sys.stderr,
        )
        return 2

    command_line = [
        sys.executable,
        "-m",
        "uvicorn",
        "apps.api.app.main:app",
        "--app-dir",
        str(PROJECT_ROOT),
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    if args.reload:
        command_line.extend(
            [
                "--reload",
                "--reload-dir",
                str(PROJECT_ROOT / "src"),
                "--reload-dir",
                str(PROJECT_ROOT / "apps" / "api"),
            ]
        )

    print(f"Starting TaxTrace API at http://{args.host}:{args.port}")
    print(f"API docs: http://{args.host}:{args.port}/docs")
    return subprocess.call(command_line, cwd=PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
