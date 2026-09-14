from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from taxtrace.database import SessionLocal
from taxtrace.explorer import FederalExplorer, FederalExplorerRequest, ExplorerResult

router = APIRouter(prefix="/explorer", tags=["explorer"])


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.post("/federal", response_model=ExplorerResult)
def federal_explorer(inp: FederalExplorerRequest, session: Session = Depends(get_db)) -> ExplorerResult:
    try:
        return FederalExplorer().explore(session, inp)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
