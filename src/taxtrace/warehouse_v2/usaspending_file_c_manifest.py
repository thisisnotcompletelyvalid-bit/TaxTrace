from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

FILE_C_SOURCE_GRAIN = "federal_account_award"
FILE_C_ACCOUNT_LEVEL = "federal_account"
FILE_C_SUBMISSION_TYPE = "award_financial"
OFFICIAL_GENERATED_DOWNLOAD_PREFIX = "https://files.usaspending.gov/generated_downloads/"
EXPECTED_FILE_C_TOTAL_COLUMNS = 240

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def manifest_path(fiscal_year: int, fiscal_period: int) -> Path:
    return _DATA_DIR / f"usaspending_file_c_manifest_FY{fiscal_year}_P{fiscal_period:02d}.json"


def load_file_c_manifest(fiscal_year: int, fiscal_period: int) -> dict | None:
    path = manifest_path(fiscal_year, fiscal_period)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"USAspending File C manifest {path.name} is not a JSON object")
    return payload


def _manifest_entries(manifest: dict) -> list[dict]:
    entries = manifest.get("agencies")
    if not isinstance(entries, list):
        raise RuntimeError("USAspending File C manifest agencies must be a list")
    return entries


def validate_file_c_manifest(
    manifest: dict,
    *,
    fiscal_year: int,
    fiscal_period: int,
    reporting_agencies: list[dict],
) -> list[dict]:
    expected_metadata = {
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "account_level": FILE_C_ACCOUNT_LEVEL,
        "source_grain": FILE_C_SOURCE_GRAIN,
        "submission_type": FILE_C_SUBMISSION_TYPE,
    }
    for key, expected in expected_metadata.items():
        observed = manifest.get(key)
        if observed != expected:
            raise RuntimeError(
                f"USAspending File C manifest {key} mismatch: expected {expected!r}, "
                f"observed {observed!r}"
            )

    current_by_id: dict[int, dict] = {}
    for agency in reporting_agencies:
        agency_id = int(agency["toptier_agency_id"])
        if agency_id in current_by_id:
            raise RuntimeError(
                f"Current USAspending reporting universe contains duplicate agency id {agency_id}"
            )
        current_by_id[agency_id] = agency

    manifest_by_id: dict[int, dict] = {}
    for entry in _manifest_entries(manifest):
        try:
            agency_id = int(entry["toptier_agency_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("USAspending File C manifest entry has invalid agency id") from exc
        if agency_id in manifest_by_id:
            raise RuntimeError(
                f"USAspending File C manifest contains duplicate agency id {agency_id}"
            )

        status = str(entry.get("status") or "").lower()
        if status != "finished":
            raise RuntimeError(
                f"USAspending File C manifest agency {agency_id} is not terminal-success: {status!r}"
            )
        file_name = str(entry.get("file_name") or "")
        file_url = str(entry.get("file_url") or "")
        if not file_name or not file_url.startswith(OFFICIAL_GENERATED_DOWNLOAD_PREFIX):
            raise RuntimeError(
                f"USAspending File C manifest agency {agency_id} does not point to an official "
                "generated archive"
            )
        if not file_url.endswith("/" + file_name):
            raise RuntimeError(
                f"USAspending File C manifest agency {agency_id} filename/URL mismatch"
            )
        if entry.get("verified_source_grain") != FILE_C_SOURCE_GRAIN:
            raise RuntimeError(
                f"USAspending File C manifest agency {agency_id} has unverified source grain"
            )
        if int(entry.get("total_columns") or 0) != EXPECTED_FILE_C_TOTAL_COLUMNS:
            raise RuntimeError(
                f"USAspending File C manifest agency {agency_id} does not have "
                f"{EXPECTED_FILE_C_TOTAL_COLUMNS} File C columns"
            )
        try:
            total_rows = int(entry["total_rows"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"USAspending File C manifest agency {agency_id} has invalid row count"
            ) from exc
        if total_rows < 0:
            raise RuntimeError(
                f"USAspending File C manifest agency {agency_id} has negative row count"
            )
        if not entry.get("verified_at"):
            raise RuntimeError(
                f"USAspending File C manifest agency {agency_id} has no verification date"
            )
        manifest_by_id[agency_id] = entry

    current_ids = set(current_by_id)
    manifest_ids = set(manifest_by_id)
    if manifest_ids != current_ids:
        missing = sorted(current_ids - manifest_ids)
        extra = sorted(manifest_ids - current_ids)
        raise RuntimeError(
            "Verified USAspending File C manifest does not exactly cover the current "
            f"FY{fiscal_year} P{fiscal_period} reporting universe; "
            f"current={len(current_ids)} manifest={len(manifest_ids)} "
            f"missing={missing[:20]} extra={extra[:20]}"
        )

    declared_count = manifest.get("agency_count")
    if declared_count is not None and int(declared_count) != len(current_ids):
        raise RuntimeError(
            f"USAspending File C manifest declares agency_count={declared_count}, "
            f"but exact coverage contains {len(current_ids)} agencies"
        )

    ordered: list[dict] = []
    for current in reporting_agencies:
        agency_id = int(current["toptier_agency_id"])
        entry = manifest_by_id[agency_id]
        for field in ("toptier_code", "abbreviation"):
            declared = str(entry.get(field) or "").strip()
            current_value = str(current.get(field) or "").strip()
            if declared and declared != current_value:
                raise RuntimeError(
                    f"USAspending File C manifest agency {agency_id} {field} mismatch: "
                    f"{declared!r} != {current_value!r}"
                )
        ordered.append(entry)
    return ordered


def verified_file_c_components(
    payload: dict,
    *,
    reporting_agencies: list[dict],
) -> list[dict] | None:
    filters = payload.get("filters") or {}
    fiscal_year = int(filters["fy"])
    period = filters.get("period")
    if period is None:
        quarter = filters.get("quarter")
        if quarter is None:
            raise ValueError("File C verified manifest requires a fiscal period or quarter")
        fiscal_period = int(quarter) * 3
    else:
        fiscal_period = int(period)

    manifest = load_file_c_manifest(fiscal_year, fiscal_period)
    if manifest is None:
        return None

    entries = validate_file_c_manifest(
        manifest,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        reporting_agencies=reporting_agencies,
    )

    components: list[dict] = []
    for entry in entries:
        shard_payload = deepcopy(payload)
        agency_id = int(entry["toptier_agency_id"])
        shard_payload["filters"]["agency"] = str(agency_id)
        components.append(
            {
                "file_name": entry["file_name"],
                "file_url": entry["file_url"],
                "status": entry["status"],
                "total_rows": int(entry["total_rows"]),
                "total_columns": int(entry["total_columns"]),
                "agency": str(agency_id),
                "transport_fallback": "pinned_verified_release_manifest",
                "verified_source_grain": entry["verified_source_grain"],
                "verified_at": entry["verified_at"],
                "download_request": shard_payload,
            }
        )
    return components
