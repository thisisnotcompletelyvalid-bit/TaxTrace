from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from taxtrace.allocation.models import FederalReceiptRequest
from taxtrace.database import get_db
from taxtrace.warehouse_v2.federal_award_detail import (
    FederalAwardDetailEngine,
    FederalAwardDetailResult,
)
from taxtrace.warehouse_v2.federal_awards import (
    FederalAwardProjectionEngine,
    FederalAwardProjectionResult,
)

router = APIRouter(prefix="/explorer", tags=["explorer-v2"])


class FederalAwardDetailRequest(BaseModel):
    fiscal_year: int
    award_identity: str


@router.post("/federal/awards", response_model=FederalAwardProjectionResult)
def federal_awards_v2(
    inp: FederalReceiptRequest,
    session: Session = Depends(get_db),
) -> FederalAwardProjectionResult:
    try:
        return FederalAwardProjectionEngine().calculate(session, inp)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/federal/award-detail", response_model=FederalAwardDetailResult)
def federal_award_detail_v2(
    inp: FederalAwardDetailRequest,
    session: Session = Depends(get_db),
) -> FederalAwardDetailResult:
    try:
        return FederalAwardDetailEngine().get(
            session,
            fiscal_year=inp.fiscal_year,
            award_identity=inp.award_identity,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
