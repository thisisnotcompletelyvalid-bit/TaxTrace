from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from taxtrace.warehouse_v2 import usaspending_accounts as accounts_module
from taxtrace.warehouse_v2.catalog import get_source
from taxtrace.warehouse_v2.usaspending_accounts import (
    activate_federal_account_archives,
    federal_account_download_requests,
)
from taxtrace.warehouse_v2.usaspending_bulk import USASpendingDownloadJob


def test_federal_account_download_requests_use_distinct_truthful_grains() -> None:
    requests = federal_account_download_requests(2025, 12)

    assert set(requests) == {"A_B", "C"}
    assert requests["A_B"]["account_level"] == "treasury_account"
    assert requests["A_B"]["filters"]["submission_types"] == [
        "account_balances",
        "object_class_program_activity",
    ]
    assert requests["C"]["account_level"] == "federal_account"
    assert requests["C"]["filters"]["submission_types"] == ["award_financial"]
    for payload in requests.values():
        assert payload["filters"]["agency"] == "all"
        assert payload["filters"]["fy"] == "2025"
        assert payload["filters"]["period"] == "12"


def test_catalog_declares_file_c_federal_account_award_grain() -> None:
    source = get_source("usaspending-file-c")

    assert source.grain == "federal_account_award"
    assert source.metadata["submission_file"] == "C"
    assert source.metadata["account_level"] == "federal_account"
    assert source.metadata["upstream_rollup"] == "treasury_account_to_federal_account"


class _FakeClient:
    def __init__(self) -> None:
        self.submitted: list[dict] = []
        self.waited: list[dict] = []
        self.downloaded: list[Path] = []

    def submit(self, kind: str, payload: dict) -> USASpendingDownloadJob:
        assert kind == "accounts"
        self.submitted.append(payload)
        label = "ab" if payload["account_level"] == "treasury_account" else "c"
        return USASpendingDownloadJob(
            kind="accounts",
            request=payload,
            response={
                "file_name": f"{label}.zip",
                "file_url": f"https://files.example/{label}.zip",
            },
        )

    def wait(self, job: USASpendingDownloadJob) -> dict:
        self.waited.append(job.request)
        return {**job.response, "status": "finished"}

    def download_completed(self, response: dict, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fake")
        self.downloaded.append(destination)
        return destination


def test_activation_materializes_ab_and_c_with_their_exact_requests(
    db_session, tmp_path, monkeypatch
) -> None:
    fake = _FakeClient()
    seen_requests: list[dict] = []

    monkeypatch.setattr(
        accounts_module,
        "get_settings",
        lambda: SimpleNamespace(raw_data_dir=tmp_path / "raw"),
    )

    def fake_materialize(session, zip_path, *, fiscal_year, request, lake=None):
        assert session is db_session
        assert fiscal_year == 2025
        assert zip_path.exists()
        seen_requests.append(request)
        if request["account_level"] == "treasury_account":
            files = {
                "A": {"rows": 2, "parquet_objects": ["a.parquet"]},
                "B": {"rows": 3, "parquet_objects": ["b.parquet"]},
            }
        else:
            files = {"C": {"rows": 4, "parquet_objects": ["c.parquet"]}}
        return {
            "archive": str(zip_path),
            "fiscal_year": fiscal_year,
            "submission_files": files,
        }

    monkeypatch.setattr(accounts_module, "materialize_account_archive", fake_materialize)

    result = activate_federal_account_archives(
        db_session,
        fiscal_year=2025,
        period=12,
        client=fake,
    )

    expected = federal_account_download_requests(2025, 12)
    assert fake.submitted == [expected["A_B"], expected["C"]]
    assert fake.waited == [expected["A_B"], expected["C"]]
    assert seen_requests == [expected["A_B"], expected["C"]]
    assert set(result["warehouse"]["submission_files"]) == {"A", "B", "C"}
    assert result["requests"]["A_B"]["account_level"] == "treasury_account"
    assert result["requests"]["C"]["account_level"] == "federal_account"
    assert len(fake.downloaded) == 2
