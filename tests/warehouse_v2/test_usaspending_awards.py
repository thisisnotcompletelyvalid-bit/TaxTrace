from datetime import date

import pytest

from taxtrace.warehouse_v2.usaspending_awards import (
    PRIME_AWARD_TYPES,
    SUBAWARD_TYPES,
    build_award_bulk_payload,
    fiscal_year_date_range,
)


def test_federal_fiscal_year_date_range() -> None:
    assert fiscal_year_date_range(2025) == (date(2024, 10, 1), date(2025, 9, 30))


def test_build_full_fiscal_year_award_payload() -> None:
    payload = build_award_bulk_payload(2025)

    assert payload["file_format"] == "csv"
    filters = payload["filters"]
    assert filters["agency"] == "all"
    assert filters["date_type"] == "action_date"
    assert filters["date_range"] == {
        "start_date": "2024-10-01",
        "end_date": "2025-09-30",
    }
    assert filters["prime_award_types"] == PRIME_AWARD_TYPES
    assert filters["sub_award_types"] == SUBAWARD_TYPES


def test_build_narrow_agency_award_payload() -> None:
    payload = build_award_bulk_payload(
        2022,
        agency=80,
        start_date=date(2022, 1, 1),
        end_date=date(2022, 1, 31),
    )
    filters = payload["filters"]
    assert filters["agency"] == 80
    assert filters["date_range"] == {
        "start_date": "2022-01-01",
        "end_date": "2022-01-31",
    }


def test_payload_can_request_only_one_award_level() -> None:
    prime_only = build_award_bulk_payload(2025, include_subawards=False)
    assert "prime_award_types" in prime_only["filters"]
    assert "sub_award_types" not in prime_only["filters"]

    sub_only = build_award_bulk_payload(2025, include_prime_awards=False)
    assert "prime_award_types" not in sub_only["filters"]
    assert "sub_award_types" in sub_only["filters"]


def test_payload_rejects_invalid_windows() -> None:
    with pytest.raises(ValueError, match="At least one"):
        build_award_bulk_payload(
            2025,
            include_prime_awards=False,
            include_subawards=False,
        )
    with pytest.raises(ValueError, match="within the selected fiscal year"):
        build_award_bulk_payload(
            2025,
            start_date=date(2024, 9, 30),
            end_date=date(2025, 1, 1),
        )
    with pytest.raises(ValueError, match="after end_date"):
        build_award_bulk_payload(
            2025,
            start_date=date(2025, 2, 1),
            end_date=date(2025, 1, 1),
        )
