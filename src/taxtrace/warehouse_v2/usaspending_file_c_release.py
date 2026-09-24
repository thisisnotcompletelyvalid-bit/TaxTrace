from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

FILE_C_PRODUCT_COLUMNS: tuple[str, ...] = (
    "federal_account_symbol",
    "gross_outlay_amount_FYB_to_period_end",
    "award_unique_key",
    "award_id_piid",
    "award_id_fain",
    "award_id_uri",
    "recipient_name",
    "recipient_name_raw",
    "recipient_uei",
    "prime_award_base_transaction_description",
    "awarding_agency_name",
    "funding_agency_name",
    "award_type",
    "usaspending_permalink",
)

OFFICIAL_GENERATED_DOWNLOAD_PREFIX = "https://files.usaspending.gov/generated_downloads/"
FILE_C_SOURCE_GRAIN = "federal_account_award"
FILE_C_ACCOUNT_LEVEL = "federal_account"
FILE_C_SUBMISSION_TYPE = "award_financial"
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_MANIFEST_PATH = _DATA_DIR / "usaspending_file_c_product_release_manifest.json"


def load_file_c_product_release_manifest() -> dict:
    payload = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("USAspending File C product release manifest is not a JSON object")
    releases = payload.get("releases")
    if not isinstance(releases, list):
        raise RuntimeError("USAspending File C product release manifest releases must be a list")
    return payload


def _validate_release(entry: dict) -> None:
    if entry.get("account_level") != FILE_C_ACCOUNT_LEVEL:
        raise RuntimeError("Verified File C product release has the wrong account level")
    if entry.get("source_grain") != FILE_C_SOURCE_GRAIN:
        raise RuntimeError("Verified File C product release has the wrong source grain")
    if entry.get("submission_type") != FILE_C_SUBMISSION_TYPE:
        raise RuntimeError("Verified File C product release has the wrong submission type")
    if entry.get("file_format") != "csv":
        raise RuntimeError("Verified File C product release is not CSV")
    if tuple(entry.get("columns") or ()) != FILE_C_PRODUCT_COLUMNS:
        raise RuntimeError("Verified File C product release does not match the product column contract")
    if str(entry.get("status") or "").lower() != "finished":
        raise RuntimeError("Verified File C product release is not terminal-success")

    file_name = str(entry.get("file_name") or "")
    file_url = str(entry.get("file_url") or "")
    if not file_name or not file_url.startswith(OFFICIAL_GENERATED_DOWNLOAD_PREFIX):
        raise RuntimeError("Verified File C product release is not an official generated archive")
    if not file_url.endswith("/" + file_name):
        raise RuntimeError("Verified File C product release filename/URL mismatch")

    if int(entry.get("total_rows") or 0) <= 0:
        raise RuntimeError("Verified File C product release has no rows")
    if int(entry.get("total_columns") or 0) <= 0:
        raise RuntimeError("Verified File C product release has no reported columns")
    if int(entry.get("member_count") or 0) <= 0:
        raise RuntimeError("Verified File C product release has no archive members")
    if int(entry.get("columns_per_member") or 0) != len(FILE_C_PRODUCT_COLUMNS):
        raise RuntimeError("Verified File C product release member schema is incomplete")
    if int(entry.get("coverage_agency_count") or 0) <= 0:
        raise RuntimeError("Verified File C product release has no reporting-universe coverage count")
    if not entry.get("verified_at") or not entry.get("verification_run_id"):
        raise RuntimeError("Verified File C product release is missing verification provenance")


def verified_product_file_c_release(payload: dict) -> dict | None:
    filters = payload.get("filters") or {}
    if payload.get("account_level") != FILE_C_ACCOUNT_LEVEL:
        return None
    if payload.get("file_format") != "csv":
        return None
    if str(filters.get("agency") or "").lower() != "all":
        return None
    if filters.get("submission_types") != [FILE_C_SUBMISSION_TYPE]:
        return None
    if tuple(payload.get("columns") or ()) != FILE_C_PRODUCT_COLUMNS:
        return None

    try:
        fiscal_year = int(filters["fy"])
        fiscal_period = int(filters["period"])
    except (KeyError, TypeError, ValueError):
        return None

    manifest = load_file_c_product_release_manifest()
    for entry in manifest["releases"]:
        if (
            int(entry.get("fiscal_year") or 0) != fiscal_year
            or int(entry.get("fiscal_period") or 0) != fiscal_period
        ):
            continue
        _validate_release(entry)
        return {
            "status": "finished",
            "file_name": entry["file_name"],
            "file_url": entry["file_url"],
            "total_rows": int(entry["total_rows"]),
            "total_columns": int(entry["total_columns"]),
            "total_size": entry.get("reported_total_size"),
            "member_count": int(entry["member_count"]),
            "columns_per_member": int(entry["columns_per_member"]),
            "coverage_agency_count": int(entry["coverage_agency_count"]),
            "transport_source": "pinned_verified_official_generated_archive",
            "transport_strategy": "all_agency_product_column_projection",
            "verified_source_grain": entry["source_grain"],
            "verified_at": entry["verified_at"],
            "verification_run_id": int(entry["verification_run_id"]),
            "download_request": deepcopy(payload),
        }
    return None
