from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import httpx
import pytest

import taxtrace.warehouse_v2.usaspending_bulk as bulk_module
from taxtrace.warehouse_v2.usaspending_bulk import (
    USASpendingBulkClient,
    USASpendingDownloadJob,
    _account_agency_ids_from_response,
    _reporting_agencies_from_response,
)


def _job() -> USASpendingDownloadJob:
    return USASpendingDownloadJob(
        kind="accounts",
        request={"filters": {"fy": "2022"}},
        response={
            "file_name": "accounts.zip",
            "file_url": "https://files.usaspending.gov/generated_downloads/accounts.zip",
        },
    )


def _multi_type_payload() -> dict:
    return {
        "account_level": "treasury_account",
        "file_format": "csv",
        "filters": {
            "agency": "all",
            "fy": "2025",
            "period": "12",
            "submission_types": [
                "account_balances",
                "object_class_program_activity",
                "award_financial",
            ],
        },
    }


def _reporting_agencies() -> list[dict]:
    return [
        {"abbreviation": "ONE", "toptier_code": "001", "name": "Agency One"},
        {"abbreviation": "TWO", "toptier_code": "002", "name": "Agency Two"},
    ]


def _agencies() -> list[dict]:
    return [
        {
            "abbreviation": "ONE",
            "toptier_code": "001",
            "name": "Agency One",
            "toptier_agency_id": 101,
        },
        {
            "abbreviation": "TWO",
            "toptier_code": "002",
            "name": "Agency Two",
            "toptier_agency_id": 202,
        },
    ]


def test_wait_treats_ready_as_intermediate(monkeypatch: pytest.MonkeyPatch) -> None:
    client = USASpendingBulkClient(timeout=1)
    responses = iter(
        [
            {"status": "ready", "file_name": "accounts.zip"},
            {"status": "finished", "file_name": "accounts.zip", "total_rows": 24},
        ]
    )
    monkeypatch.setattr(client, "status", lambda _file_name: next(responses))

    result = client.wait(_job(), poll_seconds=0, max_polls=2)

    assert result["status"] == "finished"
    assert result["total_rows"] == 24


def test_wait_raises_for_terminal_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = USASpendingBulkClient(timeout=1)
    monkeypatch.setattr(
        client,
        "status",
        lambda _file_name: {"status": "failed", "message": "upstream failure"},
    )

    with pytest.raises(RuntimeError, match="USAspending download failed"):
        client.wait(_job(), poll_seconds=0, max_polls=1)


def test_download_completed_rejects_ready_state(tmp_path: Path) -> None:
    client = USASpendingBulkClient(timeout=1)

    with pytest.raises(RuntimeError, match="refusing an early download attempt"):
        client.download_completed(
            {
                "status": "ready",
                "file_url": "https://files.usaspending.gov/generated_downloads/accounts.zip",
            },
            tmp_path / "accounts.zip",
        )


def test_reporting_agency_response_filters_stale_rows_and_sorts() -> None:
    result = _reporting_agencies_from_response(
        {
            "results": [
                {
                    "toptier_code": "002",
                    "abbreviation": "two",
                    "agency_name": "Agency Two",
                    "recent_publication_date": "2025-10-15T00:00:00Z",
                },
                {
                    "toptier_code": "999",
                    "abbreviation": "OLD",
                    "agency_name": "Stale Agency",
                    "recent_publication_date": None,
                },
                {
                    "toptier_code": "001",
                    "abbreviation": "ONE",
                    "agency_name": "Agency One",
                    "recent_publication_date": "2025-10-14T00:00:00Z",
                },
                {
                    "toptier_code": "002",
                    "abbreviation": "TWO",
                    "agency_name": "Agency Two",
                    "recent_publication_date": "2025-10-15T00:00:00Z",
                },
            ]
        }
    )

    assert result == _reporting_agencies()


def test_reporting_agency_response_refuses_missing_abbreviation() -> None:
    with pytest.raises(RuntimeError, match="without an abbreviation"):
        _reporting_agencies_from_response(
            {
                "results": [
                    {
                        "toptier_code": "001",
                        "agency_name": "Agency One",
                        "recent_publication_date": "2025-10-14T00:00:00Z",
                    }
                ]
            }
        )


def test_account_agency_reference_parses_flat_and_grouped_shapes() -> None:
    flat = _account_agency_ids_from_response(
        {
            "agencies": [
                {"toptier_code": "001", "toptier_agency_id": 101, "name": "Agency One"},
                {"toptier_code": "002", "toptier_agency_id": "202", "name": "Agency Two"},
            ]
        }
    )
    grouped = _account_agency_ids_from_response(
        {
            "agencies": {
                "cfo_agencies": [
                    {"toptier_code": "001", "toptier_agency_id": 101, "name": "Agency One"}
                ],
                "other_agencies": [
                    {"toptier_code": "002", "toptier_agency_id": 202, "name": "Agency Two"}
                ],
            }
        }
    )

    assert flat == {"001": 101, "002": 202}
    assert grouped == flat


def test_account_agency_reference_refuses_conflicting_ids() -> None:
    with pytest.raises(RuntimeError, match="conflicting toptier agency IDs"):
        _account_agency_ids_from_response(
            {
                "agencies": [
                    {"toptier_code": "001", "toptier_agency_id": 101},
                    {"toptier_code": "001", "toptier_agency_id": 999},
                ]
            }
        )


def test_current_reporting_account_agencies_strictly_joins_internal_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = USASpendingBulkClient(timeout=1)
    monkeypatch.setattr(client, "reporting_agencies", lambda _year, _period: _reporting_agencies())
    monkeypatch.setattr(client, "account_agency_ids", lambda: {"001": 101, "002": 202})

    assert client.current_reporting_account_agencies(2025, 12) == _agencies()


def test_current_reporting_account_agencies_fails_closed_on_missing_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = USASpendingBulkClient(timeout=1)
    monkeypatch.setattr(client, "reporting_agencies", lambda _year, _period: _reporting_agencies())
    monkeypatch.setattr(client, "account_agency_ids", lambda: {"001": 101})

    with pytest.raises(RuntimeError, match="002:TWO"):
        client.current_reporting_account_agencies(2025, 12)


def test_submit_retries_transient_server_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://api.usaspending.gov/api/v2/download/accounts/")
    responses = iter(
        [
            httpx.Response(500, request=request),
            httpx.Response(503, request=request),
            httpx.Response(
                200,
                request=request,
                json={"file_name": "accounts.zip", "file_url": "https://files/accounts.zip"},
            ),
        ]
    )
    calls = 0

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url: str, json: dict):
            nonlocal calls
            calls += 1
            assert json["filters"]["fy"] == "2025"
            return next(responses)

    monkeypatch.setattr(bulk_module.httpx, "Client", lambda **_kwargs: FakeClient())
    monkeypatch.setattr(bulk_module.time, "sleep", lambda _seconds: None)

    client = USASpendingBulkClient(timeout=1)
    job = client._submit_one(
        "accounts",
        {"filters": {"fy": "2025", "submission_types": ["account_balances"]}},
    )

    assert calls == 3
    assert job.file_name == "accounts.zip"


def test_submit_retries_transient_transport_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://api.usaspending.gov/api/v2/download/accounts/")
    outcomes: list[object] = [
        httpx.RemoteProtocolError("Server disconnected without sending a response", request=request),
        httpx.ConnectError("temporary connect failure", request=request),
        httpx.Response(
            200,
            request=request,
            json={"file_name": "accounts.zip", "file_url": "https://files/accounts.zip"},
        ),
    ]
    calls = 0

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url: str, json: dict):
            nonlocal calls
            calls += 1
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(bulk_module.httpx, "Client", lambda **_kwargs: FakeClient())
    monkeypatch.setattr(bulk_module.time, "sleep", lambda _seconds: None)

    client = USASpendingBulkClient(timeout=1)
    job = client._submit_one(
        "accounts",
        {"filters": {"fy": "2025", "submission_types": ["award_financial"]}},
    )

    assert calls == 3
    assert job.file_name == "accounts.zip"


def test_submit_does_not_retry_nontransient_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://api.usaspending.gov/api/v2/download/accounts/")
    calls = 0

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url: str, json: dict):
            nonlocal calls
            calls += 1
            return httpx.Response(400, request=request, json={"detail": "bad request"})

    monkeypatch.setattr(bulk_module.httpx, "Client", lambda **_kwargs: FakeClient())

    client = USASpendingBulkClient(timeout=1)
    with pytest.raises(httpx.HTTPStatusError):
        client._submit_one(
            "accounts",
            {"filters": {"fy": "2025", "submission_types": ["account_balances"]}},
        )
    assert calls == 1


def test_status_retries_transient_transport_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("GET", bulk_module.STATUS_ENDPOINT)
    outcomes = [
        httpx.RemoteProtocolError("server disconnected", request=request),
        httpx.ConnectError("temporary connect failure", request=request),
        httpx.Response(200, request=request, json={"status": "finished", "file_name": "x.zip"}),
    ]
    calls = 0
    sleeps: list[float] = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, _url: str, params: dict):
            nonlocal calls
            assert params == {"file_name": "x.zip"}
            calls += 1
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(bulk_module.httpx, "Client", lambda **_kwargs: FakeClient())
    monkeypatch.setattr(bulk_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    client = USASpendingBulkClient(timeout=1)
    result = client.status("x.zip")

    assert result["status"] == "finished"
    assert calls == 3
    assert sleeps == [1, 2]


def test_status_does_not_retry_nontransient_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("GET", bulk_module.STATUS_ENDPOINT)
    calls = 0

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, _url: str, params: dict):
            nonlocal calls
            calls += 1
            return httpx.Response(404, request=request, json={"detail": "missing"})

    monkeypatch.setattr(bulk_module.httpx, "Client", lambda **_kwargs: FakeClient())

    client = USASpendingBulkClient(timeout=1)
    with pytest.raises(httpx.HTTPStatusError):
        client.status("x.zip")
    assert calls == 1


def test_file_c_cache_bust_schema_is_complete_and_stable() -> None:
    columns = bulk_module.FEDERAL_ACCOUNT_FILE_C_COLUMNS
    assert len(columns) == 80
    assert len(set(columns)) == 80
    assert "federal_account_symbol" in columns
    assert "award_unique_key" in columns
    assert "gross_outlay_amount_FYB_to_period_end" in columns
    assert "recipient_uei" in columns
    assert columns[-1] == "last_modified_date_NAMING_CONFLICT_SUFFIX"

    payload = {
        "account_level": "federal_account",
        "file_format": "csv",
        "filters": {
            "agency": "14",
            "fy": "2025",
            "period": "12",
            "submission_types": ["award_financial"],
        },
    }
    first = USASpendingBulkClient._file_c_cache_bust_payload(payload, 0)
    second = USASpendingBulkClient._file_c_cache_bust_payload(payload, 1)

    assert "columns" not in payload
    assert set(first["columns"]) == set(columns)
    assert set(second["columns"]) == set(columns)
    assert first["columns"] != second["columns"]
    assert first["filters"] == payload["filters"]
    assert second["filters"] == payload["filters"]


def test_file_c_stale_cached_job_is_resubmitted_with_complete_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = USASpendingBulkClient(timeout=1)
    payload = {
        "account_level": "federal_account",
        "file_format": "csv",
        "filters": {
            "agency": "14",
            "fy": "2025",
            "period": "12",
            "submission_types": ["award_financial"],
        },
    }
    submitted: list[dict] = []

    def fake_submit_one(kind: str, candidate: dict) -> USASpendingDownloadJob:
        submitted.append(candidate)
        file_name = "stale.zip" if len(submitted) == 1 else "fresh.zip"
        return USASpendingDownloadJob(
            kind=kind,
            request=candidate,
            response={
                "status_url": f"https://api.usaspending.gov/status?file_name={file_name}",
                "file_name": file_name,
                "file_url": f"https://files.usaspending.gov/generated_downloads/{file_name}",
                "download_request": candidate,
            },
        )

    def fake_status(file_name: str) -> dict:
        if file_name == "stale.zip":
            return {
                "status": "running",
                "file_name": file_name,
                "file_url": f"https://files.usaspending.gov/generated_downloads/{file_name}",
                "seconds_elapsed": "35856.956909",
            }
        return {
            "status": "finished",
            "file_name": file_name,
            "file_url": f"https://files.usaspending.gov/generated_downloads/{file_name}",
            "total_rows": 321,
            "total_columns": 240,
            "seconds_elapsed": "1.25",
        }

    monkeypatch.setattr(client, "_submit_one", fake_submit_one)
    monkeypatch.setattr(client, "status", fake_status)

    result = client._submit_file_c_shard(payload)

    assert len(submitted) == 2
    assert "columns" not in submitted[0]
    assert submitted[1]["columns"] == list(bulk_module.FEDERAL_ACCOUNT_FILE_C_COLUMNS)
    assert result["status"] == "finished"
    assert result["total_rows"] == 321
    assert result["total_columns"] == 240
    assert result["transport_cache_recovery"] == "complete_file_c_columns"
    assert result["cache_recovery_variant"] == 0
    assert result["stale_cached_jobs"][0]["file_name"] == "stale.zip"
    assert result["stale_cached_jobs"][0]["seconds_elapsed"] == "35856.956909"
    assert result["download_request"]["filters"] == payload["filters"]


def test_file_c_fresh_completed_job_does_not_cache_bust(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = USASpendingBulkClient(timeout=1)
    payload = {
        "account_level": "federal_account",
        "file_format": "csv",
        "filters": {
            "agency": "14",
            "fy": "2025",
            "period": "12",
            "submission_types": ["award_financial"],
        },
    }
    submitted: list[dict] = []

    def fake_submit_one(kind: str, candidate: dict) -> USASpendingDownloadJob:
        submitted.append(candidate)
        return USASpendingDownloadJob(
            kind=kind,
            request=candidate,
            response={
                "status_url": "https://api.usaspending.gov/status?file_name=fresh.zip",
                "file_name": "fresh.zip",
                "file_url": "https://files.usaspending.gov/generated_downloads/fresh.zip",
                "download_request": candidate,
            },
        )

    monkeypatch.setattr(client, "_submit_one", fake_submit_one)
    monkeypatch.setattr(
        client,
        "status",
        lambda _file_name: {
            "status": "finished",
            "file_name": "fresh.zip",
            "file_url": "https://files.usaspending.gov/generated_downloads/fresh.zip",
            "total_rows": 12,
            "total_columns": 240,
            "seconds_elapsed": "5.0",
        },
    )

    result = client._submit_file_c_shard(payload)

    assert submitted == [payload]
    assert result["status"] == "finished"
    assert "transport_cache_recovery" not in result


def test_verified_file_c_fallback_manifest_is_narrow() -> None:
    assert set(bulk_module.VERIFIED_FILE_C_ARCHIVE_FALLBACKS) == {
        (2025, 12, 22),
        (2025, 12, 24),
        (2025, 12, 25),
    }
    assert bulk_module.VERIFIED_FILE_C_ARCHIVE_FALLBACKS[(2025, 12, 22)]["total_rows"] == 104154
    assert bulk_module.VERIFIED_FILE_C_ARCHIVE_FALLBACKS[(2025, 12, 24)]["total_rows"] == 5602
    ncua = bulk_module.VERIFIED_FILE_C_ARCHIVE_FALLBACKS[(2025, 12, 25)]
    assert ncua["total_rows"] == 949
    assert ncua["total_columns"] == 240
    assert ncua["verified_source_grain"] == "federal_account_award"
    assert ncua["verified_at"] == "2026-09-21"


def test_file_c_uses_only_exact_verified_treasury_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = USASpendingBulkClient(timeout=1)
    monkeypatch.setattr(
        client,
        "current_reporting_account_agencies",
        lambda _year, _period: [
            {
                "toptier_code": "020",
                "abbreviation": "TREAS",
                "name": "Department of the Treasury",
                "toptier_agency_id": 22,
            }
        ],
    )
    monkeypatch.setattr(
        client,
        "_submit_one",
        lambda _kind, _payload: (_ for _ in ()).throw(RuntimeError("generator unavailable")),
    )

    payload = _multi_type_payload()
    payload["account_level"] = "federal_account"
    payload["filters"]["submission_types"] = ["award_financial"]

    job = client.submit("accounts", payload)

    assert job.response["status"] == "finished"
    assert job.response["agency_count"] == 1
    shard = job.response["split_responses"][0]
    assert shard["transport_fallback"] == "verified_official_generated_archive"
    assert shard["agency"] == "22"
    assert shard["total_rows"] == 104154
    assert shard["verified_source_grain"] == "federal_account_award"
    assert shard["download_request"]["account_level"] == "federal_account"
    assert shard["download_request"]["filters"]["period"] == "12"


def test_file_c_unverified_agency_failure_still_aborts_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = USASpendingBulkClient(timeout=1)
    monkeypatch.setattr(
        client,
        "current_reporting_account_agencies",
        lambda _year, _period: [
            {
                "toptier_code": "999",
                "abbreviation": "OTHER",
                "name": "Other Agency",
                "toptier_agency_id": 999,
            }
        ],
    )
    monkeypatch.setattr(
        client,
        "_submit_one",
        lambda _kind, _payload: (_ for _ in ()).throw(RuntimeError("generator unavailable")),
    )

    payload = _multi_type_payload()
    payload["account_level"] = "federal_account"
    payload["filters"]["submission_types"] = ["award_financial"]

    with pytest.raises(RuntimeError, match="refusing incomplete federal coverage"):
        client.submit("accounts", payload)


def test_file_c_all_agency_request_generates_current_reporting_agencies_sequentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = USASpendingBulkClient(timeout=1)
    events: list[str] = []
    seen_period: list[tuple[int, int]] = []

    def fake_current_agencies(fiscal_year: int, fiscal_period: int) -> list[dict]:
        seen_period.append((fiscal_year, fiscal_period))
        return _agencies()

    monkeypatch.setattr(client, "current_reporting_account_agencies", fake_current_agencies)

    def fake_submit_one(kind: str, payload: dict) -> USASpendingDownloadJob:
        agency = payload["filters"]["agency"]
        events.append(f"submit:{agency}")
        return USASpendingDownloadJob(
            kind=kind,
            request=payload,
            response={
                "file_name": f"file_c_{agency}.zip",
                "file_url": f"https://files.usaspending.gov/file_c_{agency}.zip",
            },
        )

    def fake_wait(job: USASpendingDownloadJob, **_kwargs) -> dict:
        agency = job.request["filters"]["agency"]
        events.append(f"wait:{agency}")
        return {**job.response, "status": "finished", "total_rows": 1}

    monkeypatch.setattr(client, "_submit_one", fake_submit_one)
    monkeypatch.setattr(client, "wait", fake_wait)
    monkeypatch.setattr(bulk_module.time, "sleep", lambda _seconds: events.append("sleep"))

    payload = _multi_type_payload()
    payload["account_level"] = "federal_account"
    payload["filters"]["submission_types"] = ["award_financial"]

    job = client.submit("accounts", payload)

    assert seen_period == [(2025, 12)]
    assert job.file_name == "FY2025P12_TaxTrace_AgencySharded_FileC.zip"
    assert job.response["split_strategy"] == "file_c_sequential_current_reporting_toptier_agency_id"
    assert job.response["agency_count"] == 2
    assert job.response["status"] == "finished"
    assert len(job.response["split_responses"]) == 2
    assert events == ["submit:101", "wait:101", "sleep", "submit:202", "wait:202"]
    assert payload["filters"]["agency"] == "all"


def test_account_submit_splits_a_b_and_preserves_completed_file_c_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = USASpendingBulkClient(timeout=1)
    submitted: list[dict] = []
    monkeypatch.setattr(
        client,
        "current_reporting_account_agencies",
        lambda _year, _period: _agencies(),
    )

    def fake_submit_one(kind: str, payload: dict) -> USASpendingDownloadJob:
        submitted.append(payload)
        submission_type = payload["filters"]["submission_types"][0]
        agency = payload["filters"].get("agency", "all")
        return USASpendingDownloadJob(
            kind=kind,
            request=payload,
            response={
                "file_name": f"{submission_type}_{agency}.zip",
                "file_url": f"https://files.usaspending.gov/{submission_type}_{agency}.zip",
            },
        )

    monkeypatch.setattr(client, "_submit_one", fake_submit_one)

    original_wait = client.wait
    def fake_wait(job: USASpendingDownloadJob, **kwargs):
        if job.request["filters"]["submission_types"] == ["award_financial"]:
            return {**job.response, "status": "finished"}
        return original_wait(job, **kwargs)

    monkeypatch.setattr(client, "wait", fake_wait)
    monkeypatch.setattr(bulk_module.time, "sleep", lambda _seconds: None)
    original_payload = _multi_type_payload()

    job = client.submit("accounts", original_payload)

    assert job.file_name == "FY2025P12_TaxTrace_Split_AccountData.zip"
    assert job.direct_url == "taxtrace-split://FY2025P12_TaxTrace_Split_AccountData.zip"
    assert (
        job.response["split_strategy"]
        == "submission_type_with_file_c_current_reporting_toptier_agency_id_shards"
    )
    assert job.response["file_c_agency_count"] == 0
    assert len(job.response["split_jobs"]) == 3
    assert [
        (
            payload["filters"]["submission_types"][0],
            payload["filters"].get("agency", "all"),
        )
        for payload in submitted
    ] == [
        ("account_balances", "all"),
        ("object_class_program_activity", "all"),
        ("award_financial", "101"),
        ("award_financial", "202"),
    ]
    assert original_payload["filters"]["agency"] == "all"
    assert original_payload["filters"]["submission_types"] == [
        "account_balances",
        "object_class_program_activity",
        "award_financial",
    ]


def test_wait_completes_all_split_account_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    client = USASpendingBulkClient(timeout=1)
    monkeypatch.setattr(
        client,
        "current_reporting_account_agencies",
        lambda _year, _period: _agencies(),
    )

    def fake_submit_one(kind: str, payload: dict) -> USASpendingDownloadJob:
        submission_type = payload["filters"]["submission_types"][0]
        agency = payload["filters"].get("agency", "all")
        return USASpendingDownloadJob(
            kind=kind,
            request=payload,
            response={
                "file_name": f"{submission_type}_{agency}.zip",
                "file_url": f"https://files.usaspending.gov/{submission_type}_{agency}.zip",
            },
        )

    monkeypatch.setattr(client, "_submit_one", fake_submit_one)
    monkeypatch.setattr(
        client,
        "status",
        lambda file_name: {
            "status": "finished",
            "file_name": file_name,
            "file_url": f"https://files.usaspending.gov/{file_name}",
            "total_rows": 1,
        },
    )

    monkeypatch.setattr(bulk_module.time, "sleep", lambda _seconds: None)

    result = client.wait(
        client.submit("accounts", _multi_type_payload()),
        poll_seconds=0,
        max_polls=1,
    )

    assert result["status"] == "finished"
    assert len(result["split_responses"]) == 3
    assert all(item["status"] == "finished" for item in result["split_responses"])
    file_c = result["split_responses"][2]
    assert file_c["split_strategy"] == "file_c_sequential_current_reporting_toptier_agency_id"
    assert len(file_c["split_responses"]) == 2
    assert all(item["status"] == "finished" for item in file_c["split_responses"])


def test_download_completed_streams_split_archives_into_one_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_a = tmp_path / "source_a.zip"
    source_b = tmp_path / "source_b.zip"
    with ZipFile(source_a, "w") as archive:
        archive.writestr("file_a.csv", "treasury_account_symbol,gross_outlay_amount\n001-0001,10\n")
    with ZipFile(source_b, "w") as archive:
        archive.writestr(
            "file_b.csv",
            "program_activity_name,object_class_name,gross_outlay_amount\nProgram,Object,10\n",
        )

    sources = {
        "https://files.usaspending.gov/a.zip": source_a,
        "https://files.usaspending.gov/b.zip": source_b,
    }

    def fake_stream_download(url: str, destination: Path):
        shutil.copyfile(sources[url], destination)
        return SimpleNamespace(path=destination)

    monkeypatch.setattr(bulk_module, "stream_download", fake_stream_download)
    client = USASpendingBulkClient(timeout=1)
    destination = tmp_path / "combined.zip"

    result = client.download_completed(
        {
            "status": "finished",
            "split_responses": [
                {
                    "status": "finished",
                    "file_name": "a.zip",
                    "file_url": "https://files.usaspending.gov/a.zip",
                },
                {
                    "status": "finished",
                    "file_name": "b.zip",
                    "file_url": "https://files.usaspending.gov/b.zip",
                },
            ],
        },
        destination,
    )

    assert result == destination
    with ZipFile(destination) as archive:
        names = archive.namelist()
        assert len(names) == 2
        assert any(name.endswith("file_a.csv") for name in names)
        assert any(name.endswith("file_b.csv") for name in names)
