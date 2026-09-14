from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from taxtrace.allocation.models import FederalReceiptRequest
from taxtrace.database import get_db
from taxtrace.warehouse_v2.federal_receipt import FederalReceiptV2Engine, FederalReceiptV2Result

router = APIRouter(prefix="/receipt", tags=["receipt-v2"])


@router.post("/federal", response_model=FederalReceiptV2Result)
def federal_receipt_v2(
    inp: FederalReceiptRequest,
    session: Session = Depends(get_db),
) -> FederalReceiptV2Result:
    try:
        return FederalReceiptV2Engine().calculate(session, inp)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
