from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from taxtrace.database import SessionLocal
from taxtrace.search import (
    FederalSearchRequest,
    SearchResponse,
    rebuild_search_index,
    search,
    search_with_receipt,
)

router = APIRouter(prefix="/search", tags=["search"])


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.get("", response_model=SearchResponse)
def search_get(
    q: str = Query(min_length=1, max_length=300),
    limit: int = Query(default=20, ge=1, le=100),
    entity_type: list[str] | None = Query(default=None),
    session: Session = Depends(get_db),
) -> SearchResponse:
    return search(session, q, limit=limit, entity_types=entity_type)


@router.post("/rebuild")
def rebuild(session: Session = Depends(get_db)) -> dict:
    return {"documents": rebuild_search_index(session)}


@router.post("/federal", response_model=SearchResponse)
def search_federal(
    inp: FederalSearchRequest, session: Session = Depends(get_db)
) -> SearchResponse:
    return search_with_receipt(session, inp)
