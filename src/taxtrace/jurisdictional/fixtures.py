from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from taxtrace.config import PROJECT_ROOT
from taxtrace.db_models import Jurisdiction
from taxtrace.enums import DataStatus, FinancialMetric, JurisdictionLevel, SourceKind
from taxtrace.finance.snapshot import SnapshotStore
from taxtrace.jurisdictional.db_models import JurisdictionSpendFact


def _ensure_jurisdiction(
    session: Session,
    code: str,
    name: str,
    level: JurisdictionLevel,
    parent_code: str | None = None,
) -> Jurisdiction:
    row = session.scalar(select(Jurisdiction).where(Jurisdiction.code == code))
    parent_id = None
    if parent_code:
        parent = session.scalar(select(Jurisdiction).where(Jurisdiction.code == parent_code))
        if parent is None:
            raise ValueError(f"Parent jurisdiction {parent_code} must be created first")
        parent_id = parent.id
    if row is None:
        row = Jurisdiction(code=code, name=name, level=level, parent_id=parent_id)
        session.add(row)
        session.flush()
    else:
        row.name = name
        row.level = level
        row.parent_id = parent_id
    return row


def _load_bundle(session: Session, path: Path) -> int:
    bundle = json.loads(path.read_text())
    level = JurisdictionLevel(bundle["jurisdiction_level"])
    jurisdiction = _ensure_jurisdiction(
        session,
        bundle["jurisdiction_code"],
        bundle["jurisdiction_name"],
        level,
        bundle.get("parent_code"),
    )
    snapshot = SnapshotStore().register_local_file(
        session,
        source_kind=SourceKind.FIXTURE,
        source_name=bundle["source_name"],
        source_url=bundle["source_url"],
        path=path,
        reference_period=bundle["reference_period"],
        parser_version="jurisdiction-acfr-v1",
        metadata={
            "fixture": True,
            "official_source_transcription": True,
            "transcription_note": bundle.get("transcription_note"),
        },
    )
    session.execute(
        delete(JurisdictionSpendFact).where(
            JurisdictionSpendFact.jurisdiction_id == jurisdiction.id,
            JurisdictionSpendFact.fiscal_year == bundle["fiscal_year"],
            JurisdictionSpendFact.record_scope == bundle["record_scope"],
        )
    )
    for row in bundle["rows"]:
        session.add(
            JurisdictionSpendFact(
                jurisdiction_id=jurisdiction.id,
                fiscal_year=bundle["fiscal_year"],
                metric=FinancialMetric.EXPENDITURE,
                status=DataStatus.ACTUAL,
                category_code=row["code"],
                category_name=row["name"],
                amount=Decimal(row["amount"]),
                source_snapshot_id=snapshot.id,
                record_scope=bundle["record_scope"],
                metadata_json={"official_source_transcription": True},
            )
        )
    session.commit()
    return len(bundle["rows"])


def ingest_jurisdiction_fixtures(session: Session, root: Path | None = None) -> int:
    fixture_root = root or (PROJECT_ROOT / "data" / "fixtures")
    _ensure_jurisdiction(session, "FL", "Florida", JurisdictionLevel.STATE)
    _ensure_jurisdiction(session, "FL-ALACHUA", "Alachua County", JurisdictionLevel.COUNTY, "FL")
    _ensure_jurisdiction(
        session, "FL-ALACHUA-SCHOOL", "School Board of Alachua County", JurisdictionLevel.SCHOOL, "FL-ALACHUA"
    )
    session.commit()
    return _load_bundle(session, fixture_root / "florida" / "fy2025_state_activities.json") + _load_bundle(
        session, fixture_root / "gainesville" / "fy2025_governmental_activities.json"
    )
