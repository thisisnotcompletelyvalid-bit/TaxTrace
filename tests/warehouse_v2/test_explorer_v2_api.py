from fastapi import HTTPException

from apps.api.app.routers.explorer_v2 import (
    FederalAwardDetailRequest,
    federal_award_detail_v2,
)


def test_award_detail_api_degrades_without_full_year_lake_release(db_session) -> None:
    result = federal_award_detail_v2(
        FederalAwardDetailRequest(fiscal_year=2025, award_identity="AWARD-NOT-LOCAL"),
        session=db_session,
    )

    assert result.award_identity == "AWARD-NOT-LOCAL"
    assert result.prime_coverage.status == "NO_FULL_YEAR_RELEASE"
    assert result.subaward_coverage.status == "NO_FULL_YEAR_RELEASE"
    assert result.prime is None
    assert result.subawards == []


def test_award_detail_api_rejects_blank_identity(db_session) -> None:
    try:
        federal_award_detail_v2(
            FederalAwardDetailRequest(fiscal_year=2025, award_identity="   "),
            session=db_session,
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "award_identity must not be blank" in str(exc.detail)
    else:
        raise AssertionError("blank award identity should be rejected")
