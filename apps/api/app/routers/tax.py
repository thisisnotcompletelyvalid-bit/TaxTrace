from fastapi import APIRouter

from taxtrace.tax.engine import FederalTaxEngine
from taxtrace.tax.models import FederalTaxInput, FederalTaxResult

router = APIRouter(prefix="/tax", tags=["tax"])


@router.post("/federal", response_model=FederalTaxResult)
def federal_tax(inp: FederalTaxInput) -> FederalTaxResult:
    return FederalTaxEngine().calculate(inp)
