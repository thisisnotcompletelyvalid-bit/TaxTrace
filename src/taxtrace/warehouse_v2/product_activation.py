from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from taxtrace.config import get_settings
from taxtrace.database import SessionLocal
from taxtrace.db_models import OMBAccountRecord, SourceSnapshot, TreasuryAggregate
from taxtrace.enums import SourceKind
from taxtrace.finance.reconcile import reconcile_omb_outlays_to_treasury
from taxtrace.finance.seed import seed_federal_methodology_entities
from taxtrace.finance.sources.omb import OMBPublicBudgetDatabaseSource
from taxtrace.finance.sources.treasury import TreasuryCombinedStatementSource
from taxtrace.search import rebuild_search_index
from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.census import bootstrap_national_census
from taxtrace.warehouse_v2.census_lake import materialize_finance_parquet
from taxtrace.warehouse_v2.db_models import BulkObject, DatasetDefinition, DatasetRelease
from taxtrace.warehouse_v2.lake import LakeStore
from taxtrace.warehouse_v2.usaspending_accounts import activate_federal_account_archives

MIN_GOVERNMENT_REGISTRY_ROWS = 90_000
MIN_CENSUS_2022_FINANCE_ROWS = 1_300_000
MIN_CENSUS_2022_GOVERNMENTS = 88_000
MIN_REAL_OMB_ACCOUNT_ROWS = 500
MIN_REAL_TREASURY_ROWS = 10


@dataclass(frozen=True)
class DatasetReadiness:
    dataset_key: str
    release_key: str | None
    status: str
    coverage_type: str | None
    row_count: int
    government_count: int
    parquet_objects: int
    local_parquet_objects: int
    full_fiscal_year: bool
    ready: bool


@dataclass(frozen=True)
class ProductDataReadiness:
    mode: str
    national_state_local_ready: bool
    federal_core_ready: bool
    federal_account_detail_ready: bool
    federal_account_sources_ready: bool
    government_registry: DatasetReadiness
    census_finance_2022: DatasetReadiness
    census_finance_2024: DatasetReadiness
    usaspending_file_a: DatasetReadiness
    usaspending_file_b: DatasetReadiness
    usaspending_file_c: DatasetReadiness
    real_omb_account_rows: int
    real_treasury_rows: int
    fixture_snapshot_count: int
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _dataset_release_status(
    session: Session,
    *,
    dataset_key: str,
    release_key: str,
    min_rows: int = 0,
    min_governments: int = 0,
    require_full_fiscal_year: bool = False,
    require_local_parquet: bool = False,
) -> DatasetReadiness:
    row = session.execute(
        select(DatasetDefinition, DatasetRelease)
        .join(DatasetRelease, DatasetRelease.dataset_id == DatasetDefinition.id)
        .where(
            DatasetDefinition.key == dataset_key,
            DatasetRelease.release_key == release_key,
        )
    ).first()
    if row is None:
        return DatasetReadiness(
            dataset_key=dataset_key,
            release_key=None,
            status="MISSING",
            coverage_type=None,
            row_count=0,
            government_count=0,
            parquet_objects=0,
            local_parquet_objects=0,
            full_fiscal_year=False,
            ready=False,
        )

    dataset, release = row
    objects = session.scalars(
        select(BulkObject).where(
            BulkObject.dataset_release_id == release.id,
            BulkObject.storage_format == "PARQUET",
        )
    ).all()
    lake_root = LakeStore().root
    local_objects = sum(1 for obj in objects if (lake_root / obj.object_key).exists())
    request = (release.metadata_json or {}).get("download_request") or {}
    filters = request.get("filters") or {}
    full_fiscal_year = str(filters.get("period") or "") == "12"
    row_count = int(release.row_count or 0)
    government_count = int(release.government_count or 0)
    ready = (
        release.status == "READY"
        and row_count >= min_rows
        and government_count >= min_governments
        and (not require_full_fiscal_year or full_fiscal_year)
        and (not require_local_parquet or (len(objects) > 0 and local_objects == len(objects)))
    )
    return DatasetReadiness(
        dataset_key=dataset.key,
        release_key=release.release_key,
        status=release.status,
        coverage_type=release.coverage_type,
        row_count=row_count,
        government_count=government_count,
        parquet_objects=len(objects),
        local_parquet_objects=local_objects,
        full_fiscal_year=full_fiscal_year,
        ready=ready,
    )


def _real_omb_account_rows(session: Session, fiscal_year: int) -> int:
    return int(
        session.scalar(
            select(func.count(OMBAccountRecord.id))
            .join(SourceSnapshot, OMBAccountRecord.source_snapshot_id == SourceSnapshot.id)
            .where(
                OMBAccountRecord.fiscal_year == fiscal_year,
                SourceSnapshot.source_kind == SourceKind.OMB,
            )
        )
        or 0
    )


def _real_treasury_rows(session: Session, fiscal_year: int) -> int:
    return int(
        session.scalar(
            select(func.count(TreasuryAggregate.id))
            .join(SourceSnapshot, TreasuryAggregate.source_snapshot_id == SourceSnapshot.id)
            .where(
                TreasuryAggregate.fiscal_year == fiscal_year,
                SourceSnapshot.source_kind == SourceKind.TREASURY,
            )
        )
        or 0
    )


def product_data_readiness(session: Session, *, federal_fiscal_year: int = 2025) -> ProductDataReadiness:
    registry = _dataset_release_status(
        session,
        dataset_key="census-government-units-2022",
        release_key="2022",
        min_rows=MIN_GOVERNMENT_REGISTRY_ROWS,
        min_governments=MIN_GOVERNMENT_REGISTRY_ROWS,
    )
    census_2022 = _dataset_release_status(
        session,
        dataset_key="census-gov-finance-2022",
        release_key="FY2022",
        min_rows=MIN_CENSUS_2022_FINANCE_ROWS,
        min_governments=MIN_CENSUS_2022_GOVERNMENTS,
    )
    census_2024 = _dataset_release_status(
        session,
        dataset_key="census-gov-finance-2024",
        release_key="FY2024",
    )
    account_statuses = {
        key: _dataset_release_status(
            session,
            dataset_key=f"usaspending-file-{key.lower()}",
            release_key=f"FY{federal_fiscal_year}",
            require_full_fiscal_year=True,
            require_local_parquet=True,
        )
        for key in ("A", "B", "C")
    }
    real_omb_rows = _real_omb_account_rows(session, federal_fiscal_year)
    real_treasury_rows = _real_treasury_rows(session, federal_fiscal_year)
    fixture_snapshots = int(
        session.scalar(
            select(func.count(SourceSnapshot.id)).where(SourceSnapshot.source_kind == SourceKind.FIXTURE)
        )
        or 0
    )

    national_ready = registry.ready and census_2022.ready
    federal_ready = (
        real_omb_rows >= MIN_REAL_OMB_ACCOUNT_ROWS
        and real_treasury_rows >= MIN_REAL_TREASURY_ROWS
    )
    account_detail_ready = account_statuses["B"].ready and account_statuses["C"].ready
    account_sources_ready = all(account_statuses[key].ready for key in ("A", "B", "C"))

    if national_ready and federal_ready and account_detail_ready:
        mode = "NATIONAL_REAL_DATA_WITH_FEDERAL_DETAIL"
    elif national_ready and federal_ready:
        mode = "NATIONAL_REAL_DATA"
    elif national_ready:
        mode = "NATIONAL_STATE_LOCAL_WITH_LIMITED_FEDERAL"
    elif federal_ready:
        mode = "REAL_FEDERAL_WITH_LIMITED_STATE_LOCAL"
    else:
        mode = "FIXTURE_OR_EMPTY"

    warnings: list[str] = []
    if not national_ready:
        warnings.append(
            "The complete national Census government/finance baseline is not active. "
            "Government search and state/local detail will be sparse or empty."
        )
    if not federal_ready:
        warnings.append(
            "The federal core is not backed by a full real OMB + Treasury ingestion for FY"
            f"{federal_fiscal_year}; fixture-scale federal detail may still be visible."
        )
    if not account_detail_ready:
        warnings.append(
            "Full-year USAspending File B/C account detail is not queryable on this runtime. "
            "Program-activity/object-class and award-financial drilldown will remain limited."
        )
    if census_2022.ready and census_2022.parquet_objects == 0:
        warnings.append(
            "The 2022 Census relational baseline is READY but no normalized Parquet mirror is registered."
        )
    if fixture_snapshots and mode not in {
        "NATIONAL_REAL_DATA",
        "NATIONAL_REAL_DATA_WITH_FEDERAL_DETAIL",
    }:
        warnings.append(
            f"{fixture_snapshots} fixture source snapshots are present. Fixture data is for deterministic "
            "tests/demos and should not be mistaken for national product coverage."
        )

    return ProductDataReadiness(
        mode=mode,
        national_state_local_ready=national_ready,
        federal_core_ready=federal_ready,
        federal_account_detail_ready=account_detail_ready,
        federal_account_sources_ready=account_sources_ready,
        government_registry=registry,
        census_finance_2022=census_2022,
        census_finance_2024=census_2024,
        usaspending_file_a=account_statuses["A"],
        usaspending_file_b=account_statuses["B"],
        usaspending_file_c=account_statuses["C"],
        real_omb_account_rows=real_omb_rows,
        real_treasury_rows=real_treasury_rows,
        fixture_snapshot_count=fixture_snapshots,
        warnings=tuple(warnings),
    )


def _materialize_census_parquet(
    session: Session,
    *,
    year: int,
    dataset_key: str,
    source_path: Path,
) -> dict | None:
    release = session.execute(
        select(DatasetRelease)
        .join(DatasetDefinition, DatasetRelease.dataset_id == DatasetDefinition.id)
        .where(
            DatasetDefinition.key == dataset_key,
            DatasetRelease.release_key == f"FY{year}",
            DatasetRelease.status == "READY",
        )
    ).scalar_one_or_none()
    if release is None or not source_path.exists():
        return None
    existing = session.scalar(
        select(func.count(BulkObject.id)).where(
            BulkObject.dataset_release_id == release.id,
            BulkObject.storage_format == "PARQUET",
        )
    ) or 0
    if existing:
        return {"status": "already_ready", "parquet_objects": int(existing)}
    return materialize_finance_parquet(
        session,
        source_path,
        dataset_key=dataset_key,
        year=year,
    )


def _activate_federal_accounts(session: Session, *, fiscal_year: int) -> dict:
    """Activate exact USAspending source grains used by the federal product."""
    return activate_federal_account_archives(
        session,
        fiscal_year=fiscal_year,
        period=12,
    )


def activate_product_data(
    session: Session,
    *,
    federal_fiscal_year: int = 2025,
    include_2024_sample: bool = True,
    include_federal_core: bool = True,
    include_federal_accounts: bool = True,
    overwrite_downloads: bool = False,
) -> dict:
    """Populate the substantive public-data baseline, skipping already-ready expensive work."""
    seed_catalog(session)
    seed_federal_methodology_entities(session)
    session.commit()

    before = product_data_readiness(session, federal_fiscal_year=federal_fiscal_year)
    actions: dict[str, object] = {}
    settings = get_settings()

    if not before.national_state_local_ready or (
        include_2024_sample and not before.census_finance_2024.ready
    ):
        actions["census"] = bootstrap_national_census(
            session,
            include_2024_sample=include_2024_sample,
            overwrite_downloads=overwrite_downloads,
        )
    else:
        actions["census"] = {"status": "already_ready"}

    parquet: dict[str, object] = {}
    result_2022 = _materialize_census_parquet(
        session,
        year=2022,
        dataset_key="census-gov-finance-2022",
        source_path=settings.raw_data_dir / "census" / "gov_finance" / "2022_Individual_Unit_File.zip",
    )
    if result_2022 is not None:
        parquet["2022"] = result_2022
    if include_2024_sample:
        result_2024 = _materialize_census_parquet(
            session,
            year=2024,
            dataset_key="census-gov-finance-2024",
            source_path=settings.raw_data_dir / "census" / "gov_finance" / "2024_Individual_Unit_Files.zip",
        )
        if result_2024 is not None:
            parquet["2024"] = result_2024
    actions["census_parquet"] = parquet

    if include_federal_core:
        current = product_data_readiness(session, federal_fiscal_year=federal_fiscal_year)
        federal_actions: dict[str, object] = {}
        if current.real_treasury_rows < MIN_REAL_TREASURY_ROWS:
            federal_actions["treasury_rows_loaded"] = TreasuryCombinedStatementSource().ingest(
                session, federal_fiscal_year
            )
        else:
            federal_actions["treasury"] = "already_ready"
        current = product_data_readiness(session, federal_fiscal_year=federal_fiscal_year)
        if current.real_omb_account_rows < MIN_REAL_OMB_ACCOUNT_ROWS:
            federal_actions["omb_rows_loaded"] = OMBPublicBudgetDatabaseSource().ingest(
                session, federal_fiscal_year
            )
        else:
            federal_actions["omb"] = "already_ready"
        federal_actions["search_documents"] = rebuild_search_index(session)
        reconciliation = reconcile_omb_outlays_to_treasury(session, federal_fiscal_year)
        federal_actions["reconciliation"] = {
            "status": reconciliation.status,
            "left": str(reconciliation.left_value),
            "right": str(reconciliation.right_value),
            "difference": str(reconciliation.absolute_difference),
        }
        actions["federal_core"] = federal_actions

    if include_federal_accounts:
        current = product_data_readiness(session, federal_fiscal_year=federal_fiscal_year)
        if current.federal_account_sources_ready:
            actions["federal_accounts"] = {"status": "already_ready"}
        else:
            actions["federal_accounts"] = _activate_federal_accounts(
                session,
                fiscal_year=federal_fiscal_year,
            )

    after = product_data_readiness(session, federal_fiscal_year=federal_fiscal_year)
    return {
        "before": before.to_dict(),
        "actions": actions,
        "after": after.to_dict(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Populate TaxTrace with its substantive national public-data baseline."
    )
    parser.add_argument("--federal-fiscal-year", type=int, default=2025)
    parser.add_argument("--no-2024-sample", action="store_true")
    parser.add_argument("--skip-federal-core", action="store_true")
    parser.add_argument("--skip-federal-accounts", action="store_true")
    parser.add_argument("--overwrite-downloads", action="store_true")
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Print readiness without downloading or modifying product data.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with SessionLocal() as session:
        if args.status_only:
            result = product_data_readiness(
                session,
                federal_fiscal_year=args.federal_fiscal_year,
            ).to_dict()
        else:
            result = activate_product_data(
                session,
                federal_fiscal_year=args.federal_fiscal_year,
                include_2024_sample=not args.no_2024_sample,
                include_federal_core=not args.skip_federal_core,
                include_federal_accounts=not args.skip_federal_accounts,
                overwrite_downloads=args.overwrite_downloads,
            )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
