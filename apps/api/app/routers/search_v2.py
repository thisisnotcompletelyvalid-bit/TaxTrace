from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from taxtrace.database import get_db
from taxtrace.warehouse_v2.federal_search import (
    FederalSearchV2Engine,
    FederalSearchV2Request,
    FederalSearchV2Response,
)

router = APIRouter(prefix="/search", tags=["search-v2"])


@router.get("/federal", response_model=FederalSearchV2Response)
def federal_search_v2_get(
    q: str = Query(min_length=1, max_length=300),
    fiscal_year: int = Query(default=2025, ge=1900, le=2200),
    limit: int = Query(default=20, ge=1, le=100),
    entity_type: list[str] | None = Query(default=None),
    session: Session = Depends(get_db),
) -> FederalSearchV2Response:
    try:
        return FederalSearchV2Engine().search(
            session,
            fiscal_year=fiscal_year,
            query=q,
            limit=limit,
            entity_types=entity_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/federal", response_model=FederalSearchV2Response)
def federal_search_v2_post(
    inp: FederalSearchV2Request,
    session: Session = Depends(get_db),
) -> FederalSearchV2Response:
    try:
        return FederalSearchV2Engine().search(
            session,
            fiscal_year=inp.spending_fiscal_year,
            query=inp.q,
            limit=inp.limit,
            entity_types=inp.entity_types,
            receipt_request=inp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
