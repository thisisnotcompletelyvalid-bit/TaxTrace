from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

import taxtrace.warehouse_v2.usaspending_bulk as bulk_module
from taxtrace.warehouse_v2.usaspending_bulk import (
    USASpendingBulkClient,
    USASpendingDownloadJob,
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


def test_account_submit_splits_multiple_submission_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = USASpendingBulkClient(timeout=1)
    submitted: list[dict] = []

    def fake_submit_one(kind: str, payload: dict) -> USASpendingDownloadJob:
        submitted.append(payload)
        submission_type = payload["filters"]["submission_types"][0]
        return USASpendingDownloadJob(
            kind=kind,
            request=payload,
            response={
                "file_name": f"{submission_type}.zip",
                "file_url": f"https://files.usaspending.gov/{submission_type}.zip",
            },
        )

    monkeypatch.setattr(client, "_submit_one", fake_submit_one)

    job = client.submit("accounts", _multi_type_payload())

    assert job.file_name == "FY2025P12_TaxTrace_Split_AccountData.zip"
    assert job.direct_url == "taxtrace-split://FY2025P12_TaxTrace_Split_AccountData.zip"
    assert [
        payload["filters"]["submission_types"] for payload in submitted
    ] == [
        ["account_balances"],
        ["object_class_program_activity"],
        ["award_financial"],
    ]
    assert len(job.response["split_jobs"]) == 3


def test_wait_completes_all_split_account_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    client = USASpendingBulkClient(timeout=1)

    def fake_submit_one(kind: str, payload: dict) -> USASpendingDownloadJob:
        submission_type = payload["filters"]["submission_types"][0]
        return USASpendingDownloadJob(
            kind=kind,
            request=payload,
            response={
                "file_name": f"{submission_type}.zip",
                "file_url": f"https://files.usaspending.gov/{submission_type}.zip",
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

    result = client.wait(
        client.submit("accounts", _multi_type_payload()),
        poll_seconds=0,
        max_polls=1,
    )

    assert result["status"] == "finished"
    assert len(result["split_responses"]) == 3
    assert all(item["status"] == "finished" for item in result["split_responses"])


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
