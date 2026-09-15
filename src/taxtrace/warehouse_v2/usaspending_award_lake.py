from __future__ import annotations

import csv
import hashlib
import json
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

# Complete award-family selections used by the official TaxTrace Custom Award
# Data Download request. Nonstandard subsets receive scoped release identities
# and cannot masquerade as federal-wide annual product coverage.
PRIME_AWARD_TYPES = (
    "A",
    "B",
    "C",
    "D",
    "IDV_A",
    "IDV_B",
    "IDV_B_A",
    "IDV_B_B",
    "IDV_B_C",
    "IDV_C",
    "IDV_D",
    "IDV_E",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
    "08",
    "09",
    "10",
    "11",
    "-1",
    "F001",
    "F002",
    "F003",
    "F004",
    "F005",
    "F006",
    "F007",
    "F008",
    "F009",
    "F010",
)
SUBAWARD_TYPES = ("grant", "procurement")


@dataclass(frozen=True)
class USAspendingAwardArchiveMember:
    member_name: str
    data_class: str
    dataset_key: str
    award_family: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class AwardReleaseIdentity:
    release_key: str
    reference_period: str
    coverage_type: str
    start_date: str
    end_date: str
    scope_complete: bool
    scope_key: str


def classify_award_columns(columns: list[str] | tuple[str, ...]) -> tuple[str, str]:
    """Classify a Custom Award Data Download member by its actual schema.

    Returns ``(data_class, award_family)``, where ``data_class`` is D1, D2,
    or F. File F contracts and assistance are one subaward grain, but the
    family is retained because their native schemas differ.
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
        if "prime_award_piid" in normalized:
            return "F", "contract"
        if "prime_award_fain" in normalized or "prime_award_uri" in normalized:
            return "F", "assistance"
        raise ValueError(
            "USAspending File F-shaped columns do not identify contract vs assistance: "
            + ", ".join(sorted(normalized)[:30])
        )

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


def _request_date_range(request: dict | None) -> tuple[str | None, str | None]:
    if not request:
        return None, None
    filters = request.get("filters")
    if not isinstance(filters, dict):
        return None, None

    date_range = filters.get("date_range")
    if isinstance(date_range, dict):
        start = date_range.get("start_date")
        end = date_range.get("end_date")
        return (str(start) if start else None, str(end) if end else None)

    time_period = filters.get("time_period")
    if isinstance(time_period, list) and time_period and isinstance(time_period[0], dict):
        start = time_period[0].get("start_date")
        end = time_period[0].get("end_date")
        return (str(start) if start else None, str(end) if end else None)
    return None, None


def _normalized_type_set(value: object) -> set[str] | None:
    if not isinstance(value, (list, tuple, set)):
        return None
    return {str(item) for item in value}


def _request_scope(request: dict | None) -> tuple[bool, str]:
    """Return whether the request represents complete federal award-family coverage.

    Date coverage is handled separately. This function prevents an agency-limited
    or award-type-limited full-year archive from receiving the same release key as
    the all-agency complete annual product release.
    """
    filters = request.get("filters") if isinstance(request, dict) else None
    if not isinstance(filters, dict):
        scope_payload = {"agency": None, "prime_award_types": None, "sub_award_types": None}
        digest = hashlib.sha256(
            json.dumps(scope_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:12]
        return False, digest

    agency = filters.get("agency")
    prime_types = _normalized_type_set(filters.get("prime_award_types"))
    subaward_types = _normalized_type_set(filters.get("sub_award_types"))

    agency_complete = isinstance(agency, str) and agency.casefold() == "all"
    requested_family_count = int(prime_types is not None) + int(subaward_types is not None)
    type_scope_complete = requested_family_count > 0
    if prime_types is not None:
        type_scope_complete = type_scope_complete and prime_types == set(PRIME_AWARD_TYPES)
    if subaward_types is not None:
        type_scope_complete = type_scope_complete and subaward_types == set(SUBAWARD_TYPES)

    scope_payload = {
        "agency": agency,
        "prime_award_types": sorted(prime_types) if prime_types is not None else None,
        "sub_award_types": sorted(subaward_types) if subaward_types is not None else None,
    }
    digest = hashlib.sha256(
        json.dumps(scope_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]
    return agency_complete and type_scope_complete, digest


def award_release_identity(fiscal_year: int, request: dict | None) -> AwardReleaseIdentity:
    if request is None:
        raise ValueError(
            "Exact USAspending award request JSON is required to identify the release period"
        )

    full_start = f"{fiscal_year - 1:04d}-10-01"
    full_end = f"{fiscal_year:04d}-09-30"
    start, end = _request_date_range(request)
    if not start or not end:
        raise ValueError(
            "USAspending award request must provide both start_date and end_date for provenance"
        )

    scope_complete, scope_key = _request_scope(request)
    full_year = start == full_start and end == full_end

    if full_year and scope_complete:
        return AwardReleaseIdentity(
            release_key=f"FY{fiscal_year}",
            reference_period=f"FY{fiscal_year}",
            coverage_type="FEDERAL_AWARD",
            start_date=start,
            end_date=end,
            scope_complete=True,
            scope_key=scope_key,
        )

    if full_year:
        return AwardReleaseIdentity(
            release_key=f"FY{fiscal_year}_SCOPE_{scope_key}",
            reference_period=f"FY{fiscal_year} scoped {scope_key}",
            coverage_type="FEDERAL_AWARD_SCOPED",
            start_date=start,
            end_date=end,
            scope_complete=False,
            scope_key=scope_key,
        )

    if scope_complete:
        return AwardReleaseIdentity(
            release_key=f"FY{fiscal_year}_{start}_{end}",
            reference_period=f"{start}/{end}",
            coverage_type="FEDERAL_AWARD_SLICE",
            start_date=start,
            end_date=end,
            scope_complete=True,
            scope_key=scope_key,
        )

    return AwardReleaseIdentity(
        release_key=f"FY{fiscal_year}_{start}_{end}_SCOPE_{scope_key}",
        reference_period=f"{start}/{end} scoped {scope_key}",
        coverage_type="FEDERAL_AWARD_SCOPED_SLICE",
        start_date=start,
        end_date=end,
        scope_complete=False,
        scope_key=scope_key,
    )


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
    identity = award_release_identity(fiscal_year, request)
    row = session.scalar(
        select(DatasetRelease).where(
            DatasetRelease.dataset_id == dataset.id,
            DatasetRelease.release_key == identity.release_key,
        )
    )
    if row is None:
        row = DatasetRelease(
            dataset_id=dataset.id,
            release_key=identity.release_key,
            reference_year=fiscal_year,
            reference_period=identity.reference_period,
            status="MATERIALIZING",
            coverage_type=identity.coverage_type,
            metadata_json={},
        )
        session.add(row)
        session.flush()
    metadata = dict(row.metadata_json or {})
    metadata["download_request"] = request
    metadata["requested_date_range"] = {
        "start_date": identity.start_date,
        "end_date": identity.end_date,
    }
    metadata["award_scope_complete"] = identity.scope_complete
    metadata["award_scope_key"] = identity.scope_key
    row.metadata_json = metadata
    row.status = "MATERIALIZING"
    row.reference_period = identity.reference_period
    row.coverage_type = identity.coverage_type
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

    The exact upstream request is required because the archive itself does not
    prove its date or agency/type coverage. Complete federal years, scoped
    full years, and partial slices therefore receive distinct immutable release
    identities.
    """
    lake = lake or LakeStore()
    identity = award_release_identity(fiscal_year, request)
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
                    "download_request": request,
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
                    identity.release_key,
                    "staging",
                    f"{member.data_class.lower()}_{member.award_family}_{part_number:04d}{suffix}",
                )
                with archive.open(member.member_name) as source, extracted.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)

                parquet = lake.path_for(
                    dataset_key,
                    identity.release_key,
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
                        "release_key": identity.release_key,
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
                    "award_scope_complete": identity.scope_complete,
                    "award_scope_key": identity.scope_key,
                }
            )
            release.metadata_json = metadata
            session.commit()
            results[dataset_key] = {
                "release_key": identity.release_key,
                "coverage_type": identity.coverage_type,
                "scope_complete": identity.scope_complete,
                "scope_key": identity.scope_key,
                "rows": total_rows,
                "members": len(members),
                "parts": part_results,
                "parquet_objects": parquet_objects,
            }

    return {
        "archive": str(zip_path),
        "fiscal_year": fiscal_year,
        "release_key": identity.release_key,
        "coverage_type": identity.coverage_type,
        "scope_complete": identity.scope_complete,
        "scope_key": identity.scope_key,
        "datasets": results,
    }
