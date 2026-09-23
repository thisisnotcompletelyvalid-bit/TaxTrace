from __future__ import annotations

from copy import deepcopy

import pytest

from taxtrace.warehouse_v2 import usaspending_file_c_manifest as manifest_module
from taxtrace.warehouse_v2.usaspending_file_c_manifest import (
    validate_file_c_manifest,
    verified_file_c_components,
)


def _reporting_agencies() -> list[dict]:
    return [
        {
            "toptier_code": "001",
            "abbreviation": "ONE",
            "name": "Agency One",
            "toptier_agency_id": 101,
        },
        {
            "toptier_code": "002",
            "abbreviation": "TWO",
            "name": "Agency Two",
            "toptier_agency_id": 202,
        },
    ]


def _entry(agency: dict, *, rows: int = 1) -> dict:
    agency_id = agency["toptier_agency_id"]
    file_name = f"FY2025P01-P12_{agency_id}_FA_AccountBreakdownByAward_verified.zip"
    return {
        **agency,
        "file_name": file_name,
        "file_url": (
            "https://files.usaspending.gov/generated_downloads/" + file_name
        ),
        "status": "finished",
        "total_rows": rows,
        "total_columns": 240,
        "verified_source_grain": "federal_account_award",
        "verified_at": "2026-09-23",
    }


def _manifest() -> dict:
    agencies = _reporting_agencies()
    return {
        "schema_version": "1.0",
        "fiscal_year": 2025,
        "fiscal_period": 12,
        "account_level": "federal_account",
        "source_grain": "federal_account_award",
        "submission_type": "award_financial",
        "agency_count": len(agencies),
        "agencies": [_entry(agency) for agency in agencies],
    }


def _payload() -> dict:
    return {
        "account_level": "federal_account",
        "file_format": "csv",
        "filters": {
            "agency": "all",
            "fy": "2025",
            "period": "12",
            "submission_types": ["award_financial"],
        },
    }


def test_manifest_requires_exact_current_reporting_universe() -> None:
    manifest = _manifest()
    manifest["agencies"] = manifest["agencies"][:1]

    with pytest.raises(RuntimeError, match="does not exactly cover"):
        validate_file_c_manifest(
            manifest,
            fiscal_year=2025,
            fiscal_period=12,
            reporting_agencies=_reporting_agencies(),
        )


def test_manifest_rejects_nonofficial_or_wrong_grain_archives() -> None:
    manifest = _manifest()
    manifest["agencies"][0]["file_url"] = "https://example.com/not-official.zip"
    with pytest.raises(RuntimeError, match="official generated archive"):
        validate_file_c_manifest(
            manifest,
            fiscal_year=2025,
            fiscal_period=12,
            reporting_agencies=_reporting_agencies(),
        )

    manifest = _manifest()
    manifest["agencies"][0]["verified_source_grain"] = "treasury_account_award"
    with pytest.raises(RuntimeError, match="unverified source grain"):
        validate_file_c_manifest(
            manifest,
            fiscal_year=2025,
            fiscal_period=12,
            reporting_agencies=_reporting_agencies(),
        )


def test_verified_components_preserve_logical_request_and_transport_truth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    monkeypatch.setattr(
        manifest_module,
        "load_file_c_manifest",
        lambda _year, _period: deepcopy(manifest),
    )

    payload = _payload()
    components = verified_file_c_components(
        payload,
        reporting_agencies=_reporting_agencies(),
    )

    assert components is not None
    assert len(components) == 2
    assert [component["agency"] for component in components] == ["101", "202"]
    assert all(
        component["transport_fallback"] == "pinned_verified_release_manifest"
        for component in components
    )
    assert all(
        component["verified_source_grain"] == "federal_account_award"
        for component in components
    )
    assert [component["download_request"]["filters"]["agency"] for component in components] == [
        "101",
        "202",
    ]
    assert payload["filters"]["agency"] == "all"


def test_zero_row_reporting_agency_archive_is_not_fabricated_away() -> None:
    agencies = _reporting_agencies()
    manifest = _manifest()
    manifest["agencies"][1] = _entry(agencies[1], rows=0)

    validated = validate_file_c_manifest(
        manifest,
        fiscal_year=2025,
        fiscal_period=12,
        reporting_agencies=agencies,
    )

    assert validated[1]["total_rows"] == 0
