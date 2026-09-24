from __future__ import annotations

from copy import deepcopy

import pytest

from taxtrace.warehouse_v2 import usaspending_bulk as bulk_module
from taxtrace.warehouse_v2.usaspending_bulk import USASpendingBulkClient
from taxtrace.warehouse_v2.usaspending_file_c_release import (
    FILE_C_PRODUCT_COLUMNS,
    load_file_c_product_release_manifest,
    verified_product_file_c_release,
)


def _payload() -> dict:
    return {
        "account_level": "federal_account",
        "file_format": "csv",
        "columns": list(FILE_C_PRODUCT_COLUMNS),
        "filters": {
            "agency": "all",
            "fy": "2025",
            "period": "12",
            "submission_types": ["award_financial"],
        },
    }


def test_manifest_pins_verified_full_year_all_agency_product_archive() -> None:
    manifest = load_file_c_product_release_manifest()
    releases = manifest["releases"]
    assert len(releases) == 1
    release = releases[0]

    assert release["fiscal_year"] == 2025
    assert release["fiscal_period"] == 12
    assert release["account_level"] == "federal_account"
    assert release["source_grain"] == "federal_account_award"
    assert release["status"] == "finished"
    assert release["total_rows"] == 39777645
    assert release["total_columns"] == 42
    assert release["member_count"] == 42
    assert release["columns_per_member"] == len(FILE_C_PRODUCT_COLUMNS)
    assert release["coverage_agency_count"] == 103
    assert release["verification_run_id"] == 35897125858
    assert release["file_url"].endswith("/" + release["file_name"])


def test_verified_release_requires_exact_logical_request() -> None:
    payload = _payload()
    response = verified_product_file_c_release(payload)
    assert response is not None
    assert response["status"] == "finished"
    assert response["total_rows"] == 39777645
    assert response["transport_source"] == "pinned_verified_official_generated_archive"
    assert response["transport_strategy"] == "all_agency_product_column_projection"
    assert response["verified_source_grain"] == "federal_account_award"
    assert response["download_request"] == payload

    wrong_columns = deepcopy(payload)
    wrong_columns["columns"] = wrong_columns["columns"][:-1]
    assert verified_product_file_c_release(wrong_columns) is None

    wrong_period = deepcopy(payload)
    wrong_period["filters"]["period"] = "11"
    assert verified_product_file_c_release(wrong_period) is None


def test_bulk_client_prefers_verified_product_release_without_agency_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = USASpendingBulkClient(timeout=1)
    monkeypatch.setattr(
        client,
        "_submit_file_c_agency_shards",
        lambda _payload: (_ for _ in ()).throw(AssertionError("agency generation must not run")),
    )

    job = client.submit("accounts", _payload())
    completed = client.wait(job)

    assert completed["status"] == "finished"
    assert completed["total_rows"] == 39777645
    assert completed["coverage_agency_count"] == 103
    assert completed["transport_source"] == "pinned_verified_official_generated_archive"


def test_nonproduct_file_c_request_retains_fail_closed_agency_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = USASpendingBulkClient(timeout=1)
    payload = _payload()
    payload.pop("columns")

    sentinel = bulk_module.USASpendingDownloadJob(
        kind="accounts",
        request=payload,
        response={"status": "finished", "file_name": "sharded.zip"},
    )
    monkeypatch.setattr(client, "_submit_file_c_agency_shards", lambda _payload: sentinel)

    assert client.submit("accounts", payload) is sentinel
