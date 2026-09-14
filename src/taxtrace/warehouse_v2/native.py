from __future__ import annotations

import csv
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from taxtrace.db_models import Jurisdiction
from taxtrace.warehouse_v2.db_models import DatasetDefinition, DatasetRelease, DetailedSpendFact
from taxtrace.warehouse_v2.lake import LakeStore


@dataclass(frozen=True)
class NativeLedgerMapping:
    amount: str
    native_key: str | None = None
    fiscal_year: str | None = None
    department: str | None = None
    fund: str | None = None
    account: str | None = None
    program: str | None = None
    activity: str | None = None
    object_class: str | None = None
    project: str | None = None
    vendor: str | None = None
    recipient: str | None = None
    award_id: str | None = None
    description: str | None = None


def _text(row: dict[str, str], column: str | None) -> str | None:
    value = row.get(column) if column else None
    return value.strip() or None if value else None


def _money(value: str) -> Decimal:
    cleaned = value.strip().replace("$", "").replace(",", "").replace("(", "-").replace(")", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Cannot parse money value {value!r}") from exc


def _native_key(row: dict[str, str], explicit: str | None, row_number: int) -> str:
    if explicit and row.get(explicit, "").strip():
        return row[explicit].strip()
    digest = hashlib.sha256()
    for key in sorted(row):
        digest.update(key.encode())
        digest.update(b"\0")
        digest.update((row.get(key) or "").encode())
        digest.update(b"\0")
    return f"row-{row_number}-{digest.hexdigest()[:24]}"


def ingest_native_csv(
    session: Session,
    *,
    path: Path,
    jurisdiction_code: str,
    dataset_key: str,
    dataset_name: str,
    authority: str,
    release_key: str,
    default_fiscal_year: int,
    metric: str,
    mapping: NativeLedgerMapping,
    materialize_rows: bool = False,
    convert_to_parquet: bool = True,
    source_url: str | None = None,
    documentation_url: str | None = None,
    batch_size: int = 5000,
) -> dict[str, int | str]:
    """Store arbitrary official checkbooks/ledgers without requiring a bespoke schema per city.

    Raw data are always registered. Large ledgers should normally stay Parquet-first; selected
    jurisdictions or hot slices may also be materialized into DetailedSpendFact.
    """
    jurisdiction = session.scalar(select(Jurisdiction).where(Jurisdiction.code == jurisdiction_code))
    if jurisdiction is None:
        raise ValueError(f"Unknown jurisdiction code {jurisdiction_code}")
    definition = session.scalar(select(DatasetDefinition).where(DatasetDefinition.key == dataset_key))
    if definition is None:
        definition = DatasetDefinition(
            key=dataset_key,
            authority=authority,
            name=dataset_name,
            grain="native_transaction_or_budget_line",
            coverage_level="NATIVE_JURISDICTION",
            source_url=source_url,
            documentation_url=documentation_url,
            bulk_available=True,
            ingestion_status="IMPLEMENTED_NATIVE_MAPPING",
            priority=20,
            metadata_json={"jurisdiction_code": jurisdiction_code},
        )
        session.add(definition)
        session.flush()
    release = session.scalar(select(DatasetRelease).where(DatasetRelease.dataset_id == definition.id, DatasetRelease.release_key == release_key))
    if release is None:
        release = DatasetRelease(
            dataset_id=definition.id,
            release_key=release_key,
            reference_year=default_fiscal_year,
            reference_period=f"FY{default_fiscal_year}",
            status="INGESTING",
            coverage_type="NATIVE",
            raw_bytes=path.stat().st_size,
        )
        session.add(release)
        session.flush()
    else:
        release.status = "INGESTING"

    lake = LakeStore()
    lake.register_file(session, dataset_release_id=release.id, path=path, layer="raw", storage_format="CSV", metadata={"native_ledger": True})
    parquet_rows = 0
    if convert_to_parquet:
        parquet_path = lake.path_for(dataset_key, release_key, "normalized", "source.parquet")
        parquet_rows = lake.csv_to_parquet(path, parquet_path)
        lake.register_file(session, dataset_release_id=release.id, path=parquet_path, layer="normalized", storage_format="PARQUET", row_count=parquet_rows, metadata={"compression": "zstd", "schema": "native_source_columns"})

    materialized = 0
    if materialize_rows:
        session.execute(delete(DetailedSpendFact).where(DetailedSpendFact.dataset_release_id == release.id))
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or mapping.amount not in reader.fieldnames:
                raise ValueError(f"Amount column {mapping.amount!r} not found in {reader.fieldnames}")
            for row_number, row in enumerate(reader, start=1):
                raw_amount = row.get(mapping.amount, "").strip()
                if not raw_amount:
                    continue
                fiscal_year = default_fiscal_year
                if mapping.fiscal_year and _text(row, mapping.fiscal_year):
                    fiscal_year = int((_text(row, mapping.fiscal_year) or "")[:4])
                session.add(DetailedSpendFact(
                    jurisdiction_id=jurisdiction.id,
                    dataset_release_id=release.id,
                    fiscal_year=fiscal_year,
                    amount=_money(raw_amount),
                    metric=metric,
                    status="ACTUAL",
                    department=_text(row, mapping.department),
                    fund=_text(row, mapping.fund),
                    account=_text(row, mapping.account),
                    program=_text(row, mapping.program),
                    activity=_text(row, mapping.activity),
                    object_class=_text(row, mapping.object_class),
                    project=_text(row, mapping.project),
                    vendor=_text(row, mapping.vendor),
                    recipient=_text(row, mapping.recipient),
                    award_id=_text(row, mapping.award_id),
                    description=_text(row, mapping.description),
                    native_key=_native_key(row, mapping.native_key, row_number),
                    metadata_json={"source_row": row_number},
                ))
                materialized += 1
                if materialized % batch_size == 0:
                    session.commit()
        session.commit()

    release.status = "READY"
    release.row_count = parquet_rows or materialized
    release.ingested_at = datetime.now(timezone.utc)
    release.metadata_json = {"materialized_rows": materialized, "parquet_rows": parquet_rows, "mapping": asdict(mapping)}
    session.commit()
    return {"dataset": dataset_key, "release": release_key, "materialized_rows": materialized, "parquet_rows": parquet_rows}
