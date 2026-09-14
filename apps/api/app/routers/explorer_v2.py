from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from taxtrace.allocation.models import FederalReceiptRequest
from taxtrace.database import get_db
from taxtrace.warehouse_v2.federal_awards import (
    FederalAwardProjectionEngine,
    FederalAwardProjectionResult,
)

router = APIRouter(prefix="/explorer", tags=["explorer-v2"])


@router.post("/federal/awards", response_model=FederalAwardProjectionResult)
def federal_awards_v2(
    inp: FederalReceiptRequest,
    session: Session = Depends(get_db),
) -> FederalAwardProjectionResult:
    try:
        return FederalAwardProjectionEngine().calculate(session, inp)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
