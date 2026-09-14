from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from taxtrace.config import PROJECT_ROOT
from taxtrace.db_models import OMBAccountRecord, SpendFact, TreasuryAggregate
from taxtrace.enums import DataStatus, FinancialMetric, SourceKind
from taxtrace.finance.snapshot import SnapshotStore
from taxtrace.finance.sources.omb import (
    OMBPublicBudgetDatabaseSource,
    _get_or_create_account,
    _get_or_create_agency,
    _get_or_create_subfunction,
)
from taxtrace.finance.sources.usaspending import USASpendingSource


class FixtureFetcher:
    """Small deterministic fetcher used to exercise production USAspending ingestion paths."""

    def __init__(self, bundle: dict):
        self.bundle = bundle

    def get_json(self, url: str, params: dict | None = None) -> dict:
        path = urlparse(url).path
        if path.endswith("/references/toptier_agencies/"):
            return self.bundle["toptier_agencies"]
        parts = [part for part in path.split("/") if part]
        if "treasury_account" in parts and "program_activity" in parts:
            idx = parts.index("treasury_account")
            tas = parts[idx + 1]
            return self.bundle[f"tas:{tas}:program_activity"]
        # .../api/v2/agency/{code}/{dimension}/
        try:
            agency_idx = parts.index("agency")
            code = parts[agency_idx + 1]
            dimension = parts[agency_idx + 2]
        except (ValueError, IndexError) as exc:
            raise KeyError(f"No fixture for URL {url}") from exc
        key = f"{code}:{dimension}"
        return self.bundle[key]

    def post_json(self, url: str, json_body: dict) -> dict:
        path = urlparse(url).path
        if path.endswith("/search/spending_by_award/"):
            require = (((json_body.get("filters") or {}).get("tas_codes") or {}).get("require") or [])
            account = None
            if require and require[0]:
                account = require[0][-1]
            if account:
                return self.bundle[f"awards:{account}"]
        raise KeyError(f"No fixture for POST {url}")

    def get_bytes(self, url: str) -> bytes:
        raise NotImplementedError("FixtureFetcher only serves JSON")


def ingest_treasury_fixture(session: Session, fixture_path: Path, fiscal_year: int = 2025) -> int:
    bundle = json.loads(fixture_path.read_text())
    snapshot = SnapshotStore().register_local_file(
        session,
        source_kind=SourceKind.FIXTURE,
        source_name=f"Treasury FY{fiscal_year} official-summary fixture",
        source_url=bundle["source_url"],
        path=fixture_path,
        reference_period=f"FY{fiscal_year}",
        parser_version="fixture-v1",
        metadata={"fixture": True, "transcription": bundle.get("transcription_note")},
    )
    session.execute(delete(TreasuryAggregate).where(TreasuryAggregate.fiscal_year == fiscal_year))
    count = 0
    for aggregate_type in ("receipts", "outlays"):
        for row in bundle[aggregate_type]:
            session.add(
                TreasuryAggregate(
                    fiscal_year=fiscal_year,
                    aggregate_type=aggregate_type,
                    category_code=row.get("code"),
                    category_name=row["name"],
                    amount=row["amount_dollars"],
                    source_snapshot_id=snapshot.id,
                    metadata_json={"fixture": True, "unit": "dollars"},
                )
            )
            count += 1
    session.commit()
    return count


def ingest_omb_fixtures(
    session: Session,
    outlays_path: Path,
    receipts_path: Path,
    fiscal_year: int = 2025,
    supplemental_path: Path | None = None,
) -> int:
    count = OMBPublicBudgetDatabaseSource().ingest_local(
        session,
        fiscal_year,
        outlays_path=outlays_path,
        receipts_path=receipts_path,
        actual_through_year=2025,
        fixture=True,
    )
    if supplemental_path is not None:
        count += _apply_omb_fixture_supplement(session, supplemental_path, fiscal_year)
    return count


def _apply_omb_fixture_supplement(
    session: Session, supplemental_path: Path, fiscal_year: int
) -> int:
    bundle = json.loads(supplemental_path.read_text())
    snapshot = SnapshotStore().register_local_file(
        session,
        source_kind=SourceKind.FIXTURE,
        source_name=f"OMB FY{fiscal_year} Phase 4-6 detail supplement",
        source_url="fixture://omb/phase4_detail.json",
        path=supplemental_path,
        reference_period=f"FY{fiscal_year}",
        parser_version="fixture-phase46-v1",
        metadata={"fixture": True, "notice": bundle.get("fixture_notice")},
    )

    reduction = sum(Decimal(str(row["amount"])) for row in bundle.get("rows", []))
    reduce_code = bundle["reduce_account_code"]
    reduce_account = session.scalar(
        select(OMBAccountRecord).where(
            OMBAccountRecord.fiscal_year == fiscal_year,
            OMBAccountRecord.agency_code == reduce_code.split("-", 1)[0],
            OMBAccountRecord.account_code == reduce_code.split("-", 1)[1],
        )
    )
    if reduce_account is None:
        raise ValueError(f"Fixture supplement reduction account {reduce_code} was not loaded")
    reduce_account.amount = Decimal(reduce_account.amount) - reduction
    reduce_fact = session.scalar(
        select(SpendFact).where(
            SpendFact.fiscal_year == fiscal_year,
            SpendFact.record_scope == "omb_account_outlay",
            SpendFact.native_key.like(f"{reduce_account.agency_code}:%:{reduce_account.account_code}:%"),
        )
    )
    if reduce_fact is None:
        raise ValueError(f"Fixture supplement spend fact for {reduce_code} was not loaded")
    reduce_fact.amount = Decimal(reduce_fact.amount) - reduction

    for row in bundle.get("rows", []):
        agency = _get_or_create_agency(session, row["agency_code"], row["agency_name"])
        account = _get_or_create_account(
            session, agency.id, row["federal_account_code"], row["account_name"]
        )
        subfunction = _get_or_create_subfunction(
            session, row.get("subfunction_code"), row.get("subfunction_title")
        )
        amount = Decimal(str(row["amount"]))
        session.add(
            OMBAccountRecord(
                fiscal_year=fiscal_year,
                status=DataStatus.ACTUAL,
                agency_code=row["agency_code"],
                agency_name=row["agency_name"],
                bureau_code=row["bureau_code"],
                bureau_name=row["bureau_name"],
                account_code=row["account_code"],
                account_name=row["account_name"],
                treasury_agency_code=row.get("treasury_agency_code"),
                cgac_agency_code=row.get("cgac_agency_code"),
                subfunction_code=row.get("subfunction_code"),
                subfunction_title=row.get("subfunction_title"),
                bea_category=row.get("bea_category"),
                grant_split=row.get("grant_split"),
                on_off_budget=row.get("on_off_budget"),
                amount=amount,
                source_snapshot_id=snapshot.id,
            )
        )
        session.add(
            SpendFact(
                fiscal_year=fiscal_year,
                metric=FinancialMetric.OUTLAY,
                status=DataStatus.ACTUAL,
                amount=amount,
                source_snapshot_id=snapshot.id,
                agency_id=agency.id,
                federal_account_id=account.id,
                budget_subfunction_id=subfunction.id if subfunction else None,
                record_scope="omb_account_outlay",
                native_key=(
                    f"{row['agency_code']}:{row['bureau_code']}:{row['account_code']}:"
                    f"{row.get('subfunction_code')}"
                ),
                metadata_json={"fixture_supplement": True},
            )
        )
    session.commit()
    return len(bundle.get("rows", []))


def ingest_usaspending_fixture(session: Session, bundle_path: Path, fiscal_year: int = 2025) -> int:
    bundle = json.loads(bundle_path.read_text())
    source = USASpendingSource(fetcher=FixtureFetcher(bundle))
    return source.ingest(session, fiscal_year=fiscal_year, agency_codes=["012"], include_awards=True)


def ingest_all_fixtures(session: Session, root: Path | None = None) -> dict[str, int]:
    fixture_root = root or (PROJECT_ROOT / "data" / "fixtures")
    return {
        "treasury": ingest_treasury_fixture(
            session, fixture_root / "treasury" / "fy2025_summary.json", fiscal_year=2025
        ),
        "omb": ingest_omb_fixtures(
            session,
            fixture_root / "omb" / "outlays_fixture.xlsx",
            fixture_root / "omb" / "receipts_fixture.xlsx",
            fiscal_year=2025,
            supplemental_path=fixture_root / "omb" / "phase4_detail.json",
        ),
        "usaspending": ingest_usaspending_fixture(
            session, fixture_root / "usaspending" / "usda_fy2025.json", fiscal_year=2025
        ),
    }
