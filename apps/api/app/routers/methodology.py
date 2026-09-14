from fastapi import APIRouter

router = APIRouter(prefix="/methodology", tags=["methodology"])


@router.get("")
def methodology() -> dict:
    return {
        "version": "1.2.0",
        "headline_definition": (
            "A user's estimated contribution is personal tax liability attributed to government "
            "activities. Dedicated revenues are restricted to their financing pools; fungible "
            "revenues are proportionally allocated across eligible actual expenditures."
        ),
        "relations": ["DIRECT", "ALLOCATED", "TRACED"],
        "calculation_bases": ["CALCULATED", "MODELED"],
        "data_statuses": ["ACTUAL", "ENACTED", "PROPOSED"],
        "primary_metric": "OUTLAY/EXPENDITURE when available",
        "statistical_scope": (
            "Phase 9A models Florida and Alachua general sales taxes from 2024 BLS Consumer "
            "Expenditure income-quintile data and explicit TaxTrace taxability assumptions."
        ),
        "docs": ["docs/METHODOLOGY.md", "docs/PHASE_7_8_9A.md"],
    }
