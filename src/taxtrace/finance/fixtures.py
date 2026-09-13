from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import delete
from sqlalchemy.orm import Session

from taxtrace.db_models import TreasuryAggregate
from taxtrace.enums import SourceKind
from taxtrace.finance.snapshot import SnapshotStore
from taxtrace.finance.sources.omb import OMBPublicBudgetDatabaseSource
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
        # .../api/v2/agency/{code}/{dimension}/
        try:
            agency_idx = parts.index("agency")
            code = parts[agency_idx + 1]
            dimension = parts[agency_idx + 2]
        except (ValueError, IndexError) as exc:
            raise KeyError(f"No fixture for URL {url}") from exc
        key = f"{code}:{dimension}"
        return self.bundle[key]

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
) -> int:
    return OMBPublicBudgetDatabaseSource().ingest_local(
        session,
        fiscal_year,
        outlays_path=outlays_path,
        receipts_path=receipts_path,
        actual_through_year=2025,
        fixture=True,
    )


def ingest_usaspending_fixture(session: Session, bundle_path: Path, fiscal_year: int = 2025) -> int:
    bundle = json.loads(bundle_path.read_text())
    source = USASpendingSource(fetcher=FixtureFetcher(bundle))
    return source.ingest(session, fiscal_year=fiscal_year, agency_codes=["012"])


def ingest_all_fixtures(session: Session, root: Path = Path("data/fixtures")) -> dict[str, int]:
    return {
        "treasury": ingest_treasury_fixture(
            session, root / "treasury" / "fy2025_summary.json", fiscal_year=2025
        ),
        "omb": ingest_omb_fixtures(
            session,
            root / "omb" / "outlays_fixture.xlsx",
            root / "omb" / "receipts_fixture.xlsx",
            fiscal_year=2025,
        ),
        "usaspending": ingest_usaspending_fixture(
            session, root / "usaspending" / "usda_fy2025.json", fiscal_year=2025
        ),
    }
