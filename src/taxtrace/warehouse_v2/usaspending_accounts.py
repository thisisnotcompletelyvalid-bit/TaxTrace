from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from taxtrace.config import get_settings
from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.usaspending_bulk import USASpendingBulkClient, USASpendingDownloadJob
from taxtrace.warehouse_v2.usaspending_lake import materialize_account_archive

ACCOUNT_ACTIVATION_HTTP_TIMEOUT_SECONDS = 90.0


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


def _transport_manifest(response: dict) -> dict[str, object]:
    components = response.get("split_responses") or []
    manifest_components: list[dict[str, object]] = []
    for component in components:
        manifest_components.append(
            {
                key: component.get(key)
                for key in (
                    "file_name",
                    "file_url",
                    "status",
                    "total_rows",
                    "total_columns",
                    "agency",
                    "transport_fallback",
                    "verified_source_grain",
                    "verified_at",
                )
                if component.get(key) is not None
            }
        )
    return {
        "split_strategy": response.get("split_strategy"),
        "agency_count": response.get("agency_count"),
        "components": manifest_components,
    }


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

    if client is None:
        settings = get_settings()
        client = USASpendingBulkClient(
            timeout=max(settings.http_timeout_seconds, ACCOUNT_ACTIVATION_HTTP_TIMEOUT_SECONDS)
        )
    requests = federal_account_download_requests(fiscal_year, period)

    seed_catalog(session)
    downloads: dict[str, dict[str, object]] = {}
    warehouses: dict[str, dict[str, object]] = {}
    submission_files: dict[str, object] = {}

    # Complete the TAS-level A/B release before starting the File C agency fleet.
    # Live FY2025 runs showed that overlapping large account generators can cause
    # submission-time disconnects on Treasury File C, while the same Federal Account
    # request succeeds in isolation. Serializing the two logical source releases avoids
    # upstream generator contention without changing either source grain.
    for key in ("A_B", "C"):
        job = client.submit("accounts", requests[key])
        response = client.wait(job)
        destination = _destination_for_job(job, response, fiscal_year=fiscal_year)
        client.download_completed(response, destination)
        result = materialize_account_archive(
            session,
            destination,
            fiscal_year=fiscal_year,
            request=requests[key],
            transport_metadata=_transport_manifest(response),
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
