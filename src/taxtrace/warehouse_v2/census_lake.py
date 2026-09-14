from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from taxtrace.warehouse_v2.census import iter_finance_records
from taxtrace.warehouse_v2.db_models import DatasetDefinition, DatasetRelease
from taxtrace.warehouse_v2.lake import LakeStore


CENSUS_PARQUET_COLUMNS = (
    "government_id",
    "item_code",
    "amount_dollars",
    "survey_year",
    "year_of_data",
    "origin_code",
)


def materialize_finance_parquet(
    session: Session,
    zip_path: Path,
    *,
    dataset_key: str,
    year: int,
    lake: LakeStore | None = None,
) -> dict[str, object]:
    """Stream a Census individual-unit finance ZIP into compressed normalized Parquet.

    The relational GovernmentFinanceFact table remains the hot path for API lookups. This copy is
    the analytical/lake representation used for whole-country scans and future cross-government
    comparisons. A temporary CSV is intentionally used as a bounded-memory bridge into DuckDB.
    """
    definition = session.scalar(
        select(DatasetDefinition).where(DatasetDefinition.key == dataset_key)
    )
    if definition is None:
        raise ValueError(f"Dataset {dataset_key!r} must be seeded before lake materialization")
    release = session.scalar(
        select(DatasetRelease).where(
            DatasetRelease.dataset_id == definition.id,
            DatasetRelease.release_key == f"FY{year}",
        )
    )
    if release is None:
        raise ValueError(
            f"Dataset release {dataset_key!r}/FY{year} must be ingested before lake materialization"
        )

    lake = lake or LakeStore()
    destination = lake.path_for(
        dataset_key,
        f"FY{year}",
        "normalized",
        f"census_finance_{year}.parquet",
    )
    staging = destination.with_suffix(".csv.tmp")
    row_count = 0
    staging.parent.mkdir(parents=True, exist_ok=True)
    try:
        with staging.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(CENSUS_PARQUET_COLUMNS)
            for record in iter_finance_records(zip_path):
                writer.writerow(
                    (
                        record.government_id,
                        record.item_code,
                        format(record.amount_dollars, "f"),
                        record.survey_year or "",
                        record.year_of_data or "",
                        record.origin_code or "",
                    )
                )
                row_count += 1
        parquet_rows = lake.csv_to_parquet(staging, destination)
    finally:
        staging.unlink(missing_ok=True)

    if parquet_rows != row_count:
        raise RuntimeError(
            f"Census Parquet row mismatch: parser={row_count}, parquet={parquet_rows}"
        )

    bulk = lake.register_file(
        session,
        dataset_release_id=release.id,
        path=destination,
        layer="normalized",
        storage_format="PARQUET",
        row_count=row_count,
        partition={"fiscal_year": year, "dataset": dataset_key},
        metadata={
            "grain": "government_unit_item_code",
            "raw_rows_additive": False,
            "amount_unit": "dollars",
            "source_archive": zip_path.name,
        },
    )
    release.normalized_bytes = bulk.byte_count
    metadata = dict(release.metadata_json or {})
    metadata["normalized_parquet_object"] = bulk.object_key
    release.metadata_json = metadata
    session.commit()
    return {
        "rows": row_count,
        "path": str(destination),
        "object_key": bulk.object_key,
        "bytes": bulk.byte_count or 0,
        "sha256": bulk.sha256,
    }
