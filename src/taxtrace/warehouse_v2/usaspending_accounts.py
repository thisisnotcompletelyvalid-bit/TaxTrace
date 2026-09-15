from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from taxtrace.config import get_settings
from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.usaspending_bulk import USASpendingBulkClient, USASpendingDownloadJob
from taxtrace.warehouse_v2.usaspending_lake import materialize_account_archive


def federal_account_download_requests(
    fiscal_year: int,
    period: int = 12,
) -> dict[str, dict]:
    """Return the exact logical USAspending requests used by the federal product.

    File A/B remain at native Treasury Account Symbol level because their detailed
    account/program/object structure is useful to the receipt. File C is requested at
    Federal Account level because TaxTrace's award projection is controlled at federal
    account grain and USAspending's Federal Account File C performs the TAS rollup
    upstream while retaining award identity and summing the monetary fields.
    """
    common_filters = {
        "agency": "all",
        "fy": str(fiscal_year),
        "period": str(period),
    }
    return {
        "A_B": {
            "account_level": "treasury_account",
            "file_format": "csv",
            "filters": {
                **common_filters,
                "submission_types": [
                    "account_balances",
                    "object_class_program_activity",
                ],
            },
        },
        "C": {
            "account_level": "federal_account",
            "file_format": "csv",
            "filters": {
                **common_filters,
                "submission_types": ["award_financial"],
            },
        },
    }


def _destination_for_job(
    job: USASpendingDownloadJob,
    response: dict,
    *,
    fiscal_year: int,
) -> Path:
    file_name = (
        response.get("file_name")
        or response.get("filename")
        or job.file_name
    )
    if not file_name:
        url = response.get("file_url") or response.get("download_url") or response.get("url")
        if not url:
            raise RuntimeError(f"Completed USAspending account download has no file identity: {response}")
        file_name = Path(str(url).split("?", 1)[0]).name
    return get_settings().raw_data_dir / "usaspending" / str(fiscal_year) / Path(file_name).name


def activate_federal_account_archives(
    session: Session,
    *,
    fiscal_year: int,
    period: int = 12,
    client: USASpendingBulkClient | None = None,
) -> dict[str, object]:
    """Request and materialize the product's exact full-year USAspending account grains."""
    if period < 1 or period > 12:
        raise ValueError("period must be between 1 and 12")

    client = client or USASpendingBulkClient()
    requests = federal_account_download_requests(fiscal_year, period)

    # Submit both logical releases before waiting so A/B generation and the File C
    # agency shards may run concurrently upstream.
    jobs = {
        key: client.submit("accounts", payload)
        for key, payload in requests.items()
    }

    completed = {
        key: client.wait(job)
        for key, job in jobs.items()
    }

    seed_catalog(session)
    downloads: dict[str, dict[str, object]] = {}
    warehouses: dict[str, dict[str, object]] = {}
    submission_files: dict[str, object] = {}

    for key in ("A_B", "C"):
        job = jobs[key]
        response = completed[key]
        destination = _destination_for_job(job, response, fiscal_year=fiscal_year)
        client.download_completed(response, destination)
        result = materialize_account_archive(
            session,
            destination,
            fiscal_year=fiscal_year,
            request=requests[key],
        )
        downloads[key] = {
            "file_name": response.get("file_name") or response.get("filename") or job.file_name,
            "status": response.get("status") or response.get("state"),
            "local_path": str(destination),
        }
        warehouses[key] = result
        for submission_type, file_result in result.get("submission_files", {}).items():
            if submission_type in submission_files:
                raise RuntimeError(
                    f"USAspending activation materialized submission file {submission_type} twice; "
                    "refusing overlapping source grains"
                )
            submission_files[submission_type] = file_result

    expected = {"A", "B", "C"}
    observed = set(submission_files)
    if observed != expected:
        raise RuntimeError(
            "USAspending account activation did not materialize exactly File A/B/C: "
            f"expected {sorted(expected)}, observed {sorted(observed)}"
        )

    return {
        "requests": requests,
        "downloads": downloads,
        "warehouse": {
            "fiscal_year": fiscal_year,
            "submission_files": submission_files,
            "source_archives": warehouses,
        },
    }
