from __future__ import annotations

from pathlib import Path

import pytest

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
