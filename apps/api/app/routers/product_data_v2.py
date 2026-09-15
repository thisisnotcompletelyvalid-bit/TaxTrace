from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from taxtrace.database import get_db
from taxtrace.warehouse_v2.product_activation import product_data_readiness

router = APIRouter(prefix="/data", tags=["product-data-v2"])


@router.get("/product-readiness")
def product_readiness(
    federal_fiscal_year: int = 2025,
    session: Session = Depends(get_db),
) -> dict:
    """Report whether the running deployment is using substantive public data or fixture-scale data."""
    result = product_data_readiness(
        session,
        federal_fiscal_year=federal_fiscal_year,
    )
    return result.to_dict()
