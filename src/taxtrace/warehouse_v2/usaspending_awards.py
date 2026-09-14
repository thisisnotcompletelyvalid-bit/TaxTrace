from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from taxtrace.config import get_settings
from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.usaspending_award_lake import materialize_award_archive
from taxtrace.warehouse_v2.usaspending_bulk import USASpendingBulkClient

# Current values accepted by USAspending's Custom Award Data Download validator.
# Keep the native codes rather than collapsing contract, assistance, and IDV types.
PRIME_AWARD_TYPES = [
    "A",
    "B",
    "C",
    "D",
    "IDV_A",
    "IDV_B",
    "IDV_B_A",
    "IDV_B_B",
    "IDV_B_C",
    "IDV_C",
    "IDV_D",
    "IDV_E",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
    "08",
    "09",
    "10",
    "11",
    "-1",
    "F001",
    "F002",
    "F003",
    "F004",
    "F005",
    "F006",
    "F007",
    "F008",
    "F009",
    "F010",
]
SUBAWARD_TYPES = ["grant", "procurement"]


def fiscal_year_date_range(fiscal_year: int) -> tuple[date, date]:
    if fiscal_year < 1900 or fiscal_year > 9999:
        raise ValueError("fiscal_year must be between 1900 and 9999")
    return date(fiscal_year - 1, 10, 1), date(fiscal_year, 9, 30)


def build_award_bulk_payload(
    fiscal_year: int,
    *,
    agency: int | str = "all",
    include_prime_awards: bool = True,
    include_subawards: bool = True,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """Build an exact Custom Award Data Download payload.

    USAspending's year-limited bulk endpoint accepts at most one year per
    request. The default therefore maps one federal fiscal year to Oct 1 through
    Sep 30. Narrower dates are useful for live smoke tests.
    """
    if not include_prime_awards and not include_subawards:
        raise ValueError("At least one of prime awards or subawards must be requested")

    fy_start, fy_end = fiscal_year_date_range(fiscal_year)
    start = start_date or fy_start
    end = end_date or fy_end
    if start > end:
        raise ValueError("start_date must not be after end_date")
    if start < fy_start or end > fy_end:
        raise ValueError("award download dates must stay within the selected fiscal year")
    if (end - start).days > 366:
        raise ValueError("USAspending award bulk downloads are limited to one year")

    filters: dict[str, object] = {
        "agency": agency,
        "date_type": "action_date",
        "date_range": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
    }
    if include_prime_awards:
        filters["prime_award_types"] = PRIME_AWARD_TYPES
    if include_subawards:
        filters["sub_award_types"] = SUBAWARD_TYPES

    return {"filters": filters, "file_format": "csv"}


def request_award_archive(
    fiscal_year: int,
    *,
    agency: int | str = "all",
    include_prime_awards: bool = True,
    include_subawards: bool = True,
    start_date: date | None = None,
    end_date: date | None = None,
    wait: bool = True,
    client: USASpendingBulkClient | None = None,
) -> dict[str, object]:
    """Submit a Custom Award Data Download and optionally wait/download it."""
    payload = build_award_bulk_payload(
        fiscal_year,
        agency=agency,
        include_prime_awards=include_prime_awards,
        include_subawards=include_subawards,
        start_date=start_date,
        end_date=end_date,
    )
    client = client or USASpendingBulkClient()
    job = client.submit("bulk_awards", payload)
    response = client.wait(job) if wait else job.response
    result: dict[str, object] = {"request": payload, "response": response}

    if not wait:
        return result

    url = response.get("file_url") or response.get("download_url") or response.get("url")
    if not url:
        raise RuntimeError(f"Completed USAspending award response has no file URL: {response}")
    destination = (
        get_settings().raw_data_dir
        / "usaspending"
        / "awards"
        / f"FY{fiscal_year}"
        / Path(str(url).split("?", 1)[0]).name
    )
    client.download_completed(response, destination)
    result["response"] = {**response, "taxtrace_local_path": str(destination)}
    return result


def materialize_requested_awards(
    session: Session,
    result: dict[str, object],
    *,
    fiscal_year: int,
) -> dict[str, object]:
    """Materialize a completed ``request_award_archive`` result into the lake."""
    response = result.get("response")
    if not isinstance(response, dict):
        raise ValueError("award result response is missing")
    local_path = response.get("taxtrace_local_path")
    if not local_path:
        raise ValueError("award result has not been downloaded locally")
    request = result.get("request")
    if not isinstance(request, dict):
        raise ValueError("award result request is missing")

    seed_catalog(session)
    return materialize_award_archive(
        session,
        Path(str(local_path)),
        fiscal_year=fiscal_year,
        request=request,
    )
