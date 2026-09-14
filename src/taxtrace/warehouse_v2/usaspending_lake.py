from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from taxtrace.warehouse_v2.db_models import DatasetDefinition, DatasetRelease
from taxtrace.warehouse_v2.lake import LakeStore


@dataclass(frozen=True)
class USAspendingArchiveMember:
    member_name: str
    submission_type: str
    dataset_key: str
    columns: tuple[str, ...]


SUBMISSION_DATASETS = {
    "A": "usaspending-file-a",
    "B": "usaspending-file-b",
    "C": "usaspending-file-c",
}


def classify_account_columns(columns: list[str] | tuple[str, ...]) -> str:
    normalized = {str(column).strip().lower() for column in columns}
    if "financial_accounts_by_awards_id" in normalized or "award_unique_key" in normalized:
        return "C"
    if (
        "financial_accounts_by_program_activity_object_class_id" in normalized
        or (
            "program_activity_name" in normalized
            and "object_class_name" in normalized
            and "award_unique_key" not in normalized
        )
    ):
        return "B"
    if (
        "appropriation_account_balances_id" in normalized
        or (
            "treasury_account_symbol" in normalized
            and "gross_outlay_amount" in normalized
            and "program_activity_name" not in normalized
        )
    ):
        return "A"
    raise ValueError(
        "Unable to classify USAspending account download columns as File A, B, or C: "
        + ", ".join(sorted(normalized)[:25])
    )


def inspect_account_archive(zip_path: Path) -> list[USAspendingArchiveMember]:
    members: list[USAspendingArchiveMember] = []
    with ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir() or not member.filename.lower().endswith((".csv", ".tsv")):
                continue
            delimiter = "\t" if member.filename.lower().endswith(".tsv") else ","
            with archive.open(member) as raw:
                line = raw.readline().decode("utf-8-sig", errors="replace")
            columns = tuple(next(csv.reader([line], delimiter=delimiter)))
            submission_type = classify_account_columns(columns)
            members.append(
                USAspendingArchiveMember(
                    member_name=member.filename,
                    submission_type=submission_type,
                    dataset_key=SUBMISSION_DATASETS[submission_type],
                    columns=columns,
                )
            )
    if not members:
        raise ValueError(f"USAspending account archive {zip_path} contained no CSV/TSV members")
    return members


def _definition(session: Session, dataset_key: str) -> DatasetDefinition:
    row = session.scalar(select(DatasetDefinition).where(DatasetDefinition.key == dataset_key))
    if row is None:
        raise ValueError(f"Dataset {dataset_key!r} is not present in the TaxTrace V2 catalog")
    return row


def _release(
    session: Session,
    dataset: DatasetDefinition,
    *,
    fiscal_year: int,
    request: dict | None,
) -> DatasetRelease:
    release_key = f"FY{fiscal_year}"
    row = session.scalar(
        select(DatasetRelease).where(
            DatasetRelease.dataset_id == dataset.id,
            DatasetRelease.release_key == release_key,
        )
    )
    if row is None:
        row = DatasetRelease(
            dataset_id=dataset.id,
            release_key=release_key,
            reference_year=fiscal_year,
            reference_period=release_key,
            status="MATERIALIZING",
            coverage_type="FEDERAL_SUBMISSION",
            metadata_json={},
        )
        session.add(row)
        session.flush()
    metadata = dict(row.metadata_json or {})
    if request is not None:
        metadata["download_request"] = request
    metadata["submission_file"] = dataset.metadata_json.get("submission_file") if dataset.metadata_json else None
    row.metadata_json = metadata
    row.status = "MATERIALIZING"
    return row


def materialize_account_archive(
    session: Session,
    zip_path: Path,
    *,
    fiscal_year: int,
    request: dict | None = None,
    lake: LakeStore | None = None,
) -> dict[str, object]:
    """Materialize USAspending account bulk archive members as separate A/B/C Parquet grains."""
    lake = lake or LakeStore()
    inspected = inspect_account_archive(zip_path)
    by_type: dict[str, list[USAspendingArchiveMember]] = {}
    for member in inspected:
        by_type.setdefault(member.submission_type, []).append(member)

    releases: dict[str, DatasetRelease] = {}
    for submission_type in by_type:
        dataset = _definition(session, SUBMISSION_DATASETS[submission_type])
        releases[submission_type] = _release(
            session,
            dataset,
            fiscal_year=fiscal_year,
            request=request,
        )
    session.commit()

    results: dict[str, dict[str, object]] = {}
    with ZipFile(zip_path) as archive:
        for submission_type, members in by_type.items():
            dataset_key = SUBMISSION_DATASETS[submission_type]
            release = releases[submission_type]
            raw_object = lake.register_file(
                session,
                dataset_release_id=release.id,
                path=zip_path,
                layer="raw",
                storage_format="ZIP",
                metadata={
                    "shared_account_archive": True,
                    "submission_type": submission_type,
                    "download_request": request or {},
                },
            )
            total_rows = 0
            parquet_objects: list[str] = []
            for part_number, member in enumerate(members, start=1):
                suffix = ".tsv" if member.member_name.lower().endswith(".tsv") else ".csv"
                extracted = lake.path_for(
                    dataset_key,
                    f"FY{fiscal_year}",
                    "staging",
                    f"file_{submission_type}_{part_number:04d}{suffix}",
                )
                extracted.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member.member_name) as source, extracted.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)

                parquet = lake.path_for(
                    dataset_key,
                    f"FY{fiscal_year}",
                    "normalized",
                    f"file_{submission_type}_{part_number:04d}.parquet",
                )
                if suffix == ".csv":
                    row_count = lake.csv_to_parquet(extracted, parquet)
                else:
                    # DuckDB handles TSV explicitly here rather than relying on extension guessing.
                    import duckdb

                    connection = duckdb.connect()
                    try:
                        connection.execute(
                            "COPY (SELECT * FROM read_csv_auto(?, header=true, delim='\\t', all_varchar=true, sample_size=-1)) "
                            "TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                            [str(extracted), str(parquet)],
                        )
                        row_count = int(
                            connection.execute(
                                "SELECT count(*) FROM read_parquet(?)", [str(parquet)]
                            ).fetchone()[0]
                        )
                    finally:
                        connection.close()
                extracted.unlink(missing_ok=True)

                bulk = lake.register_file(
                    session,
                    dataset_release_id=release.id,
                    path=parquet,
                    layer="normalized",
                    storage_format="PARQUET",
                    row_count=row_count,
                    partition={
                        "fiscal_year": fiscal_year,
                        "submission_type": submission_type,
                        "part": part_number,
                    },
                    metadata={
                        "source_member": member.member_name,
                        "columns": list(member.columns),
                        "grain_is_additive_with_other_submission_files": False,
                    },
                )
                total_rows += row_count
                parquet_objects.append(bulk.object_key)

            release.status = "READY"
            release.row_count = total_rows
            release.raw_bytes = raw_object.byte_count
            release.normalized_bytes = sum(
                path.stat().st_size
                for path in [
                    lake.root / object_key for object_key in parquet_objects
                ]
                if path.exists()
            )
            release.ingested_at = datetime.now(timezone.utc)
            metadata = dict(release.metadata_json or {})
            metadata.update(
                {
                    "source_archive": zip_path.name,
                    "source_members": [member.member_name for member in members],
                    "parquet_objects": parquet_objects,
                    "grain_is_additive_with_other_submission_files": False,
                }
            )
            release.metadata_json = metadata
            session.commit()
            results[submission_type] = {
                "dataset_key": dataset_key,
                "rows": total_rows,
                "members": len(members),
                "parquet_objects": parquet_objects,
            }

    return {
        "archive": str(zip_path),
        "fiscal_year": fiscal_year,
        "submission_files": results,
    }
