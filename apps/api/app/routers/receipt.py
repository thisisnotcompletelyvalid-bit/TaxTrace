from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from taxtrace.allocation.engine import FederalAllocationEngine
from taxtrace.allocation.models import FederalReceiptRequest, FederalReceiptResult
from taxtrace.database import SessionLocal

router = APIRouter(prefix="/receipt", tags=["receipt"])


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.post("/federal", response_model=FederalReceiptResult)
def federal_receipt(inp: FederalReceiptRequest, session: Session = Depends(get_db)) -> FederalReceiptResult:
    try:
        return FederalAllocationEngine().calculate(session, inp)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
