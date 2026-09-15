from fastapi import HTTPException

from apps.api.app.routers.search_v2 import federal_search_v2_get
from taxtrace.warehouse_v2.catalog import seed_catalog


def test_v2_federal_search_api_degrades_without_award_lake(db_session) -> None:
    seed_catalog(db_session)
    result = federal_search_v2_get(
        q="Acme",
        fiscal_year=2025,
        limit=20,
        entity_type=None,
        session=db_session,
    )

    assert result.results == []
    assert result.receipt_context is False
    assert result.personalization_status == "NOT_REQUESTED"
    assert result.prime_coverage.status == "NO_FULL_YEAR_RELEASE"
    assert result.subaward_coverage.status == "NO_FULL_YEAR_RELEASE"
    assert all("non-additive" in warning or "incomplete" in warning for warning in result.warnings)


def test_v2_federal_search_api_rejects_unknown_type(db_session) -> None:
    seed_catalog(db_session)
    try:
        federal_search_v2_get(
            q="Acme",
            fiscal_year=2025,
            limit=20,
            entity_type=["obligation"],
            session=db_session,
        )
    except HTTPException as exc:
        assert exc.status_code == 422
        assert "unsupported Warehouse V2 federal search types" in str(exc.detail)
    else:
        raise AssertionError("V2 search should reject an unsupported entity type")
