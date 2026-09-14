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

PRIME_DATASET = "usaspending-file-d1-d2"
SUBAWARD_DATASET = "usaspending-file-f"


@dataclass(frozen=True)
class USAspendingAwardArchiveMember:
    member_name: str
    data_class: str
    dataset_key: str
    award_family: str
    columns: tuple[str, ...]


def classify_award_columns(columns: list[str] | tuple[str, ...]) -> tuple[str, str]:
    """Classify a Custom Award Data Download member by its actual schema.

    Returns `(data_class, award_family)`, where data_class is D1, D2, or F.
    File F contract and assistance subaward members intentionally share one data
    class because they are the same subaward grain even when their attributes differ.
    """
    normalized = {str(column).strip().lower() for column in columns}

    subaward_markers = {
        "subaward_number",
        "subaward_amount",
        "subaward_description",
        "subaward_type",
        "subawardee_name",
        "sub_awardee_or_recipient_legal",
    }
    if normalized & subaward_markers:
        family = "contract" if "award_id_piid" in normalized or "prime_award_id" in normalized else "assistance"
        return "F", family

    if "contract_award_unique_key" in normalized or "award_id_piid" in normalized:
        return "D1", "contract"

    if (
        "assistance_award_unique_key" in normalized
        or "award_id_fain" in normalized
        or "award_id_uri" in normalized
    ):
        return "D2", "assistance"

    raise ValueError(
        "Unable to classify USAspending award download columns as D1, D2, or File F: "
        + ", ".join(sorted(normalized)[:30])
    )


def inspect_award_archive(zip_path: Path) -> list[USAspendingAwardArchiveMember]:
    members: list[USAspendingAwardArchiveMember] = []
    with ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir() or not member.filename.lower().endswith((".csv", ".tsv")):
                continue
            delimiter = "\t" if member.filename.lower().endswith(".tsv") else ","
            with archive.open(member) as raw:
                line = raw.readline().decode("utf-8-sig", errors="replace")
            columns = tuple(next(csv.reader([line], delimiter=delimiter)))
            data_class, award_family = classify_award_columns(columns)
            dataset_key = SUBAWARD_DATASET if data_class == "F" else PRIME_DATASET
            members.append(
                USAspendingAwardArchiveMember(
                    member_name=member.filename,
                    data_class=data_class,
                    dataset_key=dataset_key,
                    award_family=award_family,
                    columns=columns,
                )
            )
    if not members:
        raise ValueError(f"USAspending award archive {zip_path} contained no CSV/TSV members")
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
            coverage_type="FEDERAL_AWARD",
            metadata_json={},
        )
        session.add(row)
        session.flush()
    metadata = dict(row.metadata_json or {})
    if request is not None:
        metadata["download_request"] = request
    row.metadata_json = metadata
    row.status = "MATERIALIZING"
    return row


def materialize_award_archive(
    session: Session,
    zip_path: Path,
    *,
    fiscal_year: int,
    request: dict | None = None,
    lake: LakeStore | None = None,
) -> dict[str, object]:
    """Materialize prime D1/D2-shaped award data and File F-shaped subawards.

    Prime award summaries and subawards are separate dataset releases. Individual
    contract/assistance members stay separate Parquet objects so their native
    schemas are preserved rather than coerced into a lossy union.
    """
    lake = lake or LakeStore()
    inspected = inspect_award_archive(zip_path)
    by_dataset: dict[str, list[USAspendingAwardArchiveMember]] = {}
    for member in inspected:
        by_dataset.setdefault(member.dataset_key, []).append(member)

    releases: dict[str, DatasetRelease] = {}
    for dataset_key in by_dataset:
        dataset = _definition(session, dataset_key)
        releases[dataset_key] = _release(
            session,
            dataset,
            fiscal_year=fiscal_year,
            request=request,
        )
    session.commit()

    results: dict[str, dict[str, object]] = {}
    with ZipFile(zip_path) as archive:
        for dataset_key, members in by_dataset.items():
            release = releases[dataset_key]
            raw_object = lake.register_file(
                session,
                dataset_release_id=release.id,
                path=zip_path,
                layer="raw",
                storage_format="ZIP",
                metadata={
                    "shared_award_archive": True,
                    "download_request": request or {},
                    "native_data_classes": sorted({member.data_class for member in members}),
                },
            )

            total_rows = 0
            parquet_objects: list[str] = []
            part_results: list[dict[str, object]] = []
            for part_number, member in enumerate(members, start=1):
                suffix = ".tsv" if member.member_name.lower().endswith(".tsv") else ".csv"
                delimiter = "\t" if suffix == ".tsv" else ","
                extracted = lake.path_for(
                    dataset_key,
                    f"FY{fiscal_year}",
                    "staging",
                    f"{member.data_class.lower()}_{member.award_family}_{part_number:04d}{suffix}",
                )
                with archive.open(member.member_name) as source, extracted.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)

                parquet = lake.path_for(
                    dataset_key,
                    f"FY{fiscal_year}",
                    "normalized",
                    f"{member.data_class.lower()}_{member.award_family}_{part_number:04d}.parquet",
                )
                row_count = lake.csv_to_parquet(
                    extracted,
                    parquet,
                    delimiter=delimiter,
                )
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
                        "data_class": member.data_class,
                        "award_family": member.award_family,
                        "part": part_number,
                    },
                    metadata={
                        "source_member": member.member_name,
                        "columns": list(member.columns),
                        "grain_is_additive_with_other_dataset_grains": False,
                    },
                )
                total_rows += row_count
                parquet_objects.append(bulk.object_key)
                part_results.append(
                    {
                        "data_class": member.data_class,
                        "award_family": member.award_family,
                        "rows": row_count,
                        "source_member": member.member_name,
                        "parquet_object": bulk.object_key,
                    }
                )

            release.status = "READY"
            release.row_count = total_rows
            release.raw_bytes = raw_object.byte_count
            release.normalized_bytes = sum(
                (lake.root / object_key).stat().st_size
                for object_key in parquet_objects
                if (lake.root / object_key).exists()
            )
            release.ingested_at = datetime.now(timezone.utc)
            metadata = dict(release.metadata_json or {})
            metadata.update(
                {
                    "source_archive": zip_path.name,
                    "source_members": [member.member_name for member in members],
                    "native_data_classes": sorted({member.data_class for member in members}),
                    "parquet_objects": parquet_objects,
                    "grain_is_additive_with_other_dataset_grains": False,
                }
            )
            release.metadata_json = metadata
            session.commit()
            results[dataset_key] = {
                "rows": total_rows,
                "members": len(members),
                "parts": part_results,
                "parquet_objects": parquet_objects,
            }

    return {
        "archive": str(zip_path),
        "fiscal_year": fiscal_year,
        "datasets": results,
    }
