from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from taxtrace.database import SessionLocal
from taxtrace.db_models import Agency, Award, ReconciliationResult, SearchDocument, SourceSnapshot, SpendFact, TreasuryAggregate
from taxtrace.jurisdictional.db_models import JurisdictionSpendFact

router = APIRouter(prefix="/warehouse", tags=["warehouse"])


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.get("/status")
def status(session: Session = Depends(get_db)) -> dict:
    return {
        "source_snapshots": session.scalar(select(func.count(SourceSnapshot.id))) or 0,
        "spend_facts": session.scalar(select(func.count(SpendFact.id))) or 0,
        "jurisdiction_spend_facts": session.scalar(select(func.count(JurisdictionSpendFact.id))) or 0,
        "agencies": session.scalar(select(func.count(Agency.id))) or 0,
        "treasury_aggregate_rows": session.scalar(select(func.count(TreasuryAggregate.id))) or 0,
        "awards": session.scalar(select(func.count(Award.id))) or 0,
        "search_documents": session.scalar(select(func.count(SearchDocument.id))) or 0,
    }


@router.get("/reconciliation/{fiscal_year}")
def reconciliation(fiscal_year: int, session: Session = Depends(get_db)) -> list[dict]:
    rows = session.scalars(
        select(ReconciliationResult).where(ReconciliationResult.fiscal_year == fiscal_year)
    ).all()
    return [
        {
            "comparison": r.comparison_name,
            "left": str(r.left_value),
            "right": str(r.right_value),
            "absolute_difference": str(r.absolute_difference),
            "relative_difference": str(r.relative_difference) if r.relative_difference is not None else None,
            "status": r.status,
        }
        for r in rows
    ]


@router.get("/treasury/{fiscal_year}/{aggregate_type}")
def treasury_aggregate(
    fiscal_year: int, aggregate_type: str, session: Session = Depends(get_db)
) -> list[dict]:
    if aggregate_type not in {"receipts", "outlays"}:
        raise HTTPException(400, "aggregate_type must be receipts or outlays")
    rows = session.scalars(
        select(TreasuryAggregate)
        .where(
            TreasuryAggregate.fiscal_year == fiscal_year,
            TreasuryAggregate.aggregate_type == aggregate_type,
        )
        .order_by(TreasuryAggregate.id)
    ).all()
    return [{"name": r.category_name, "amount": str(r.amount)} for r in rows]
