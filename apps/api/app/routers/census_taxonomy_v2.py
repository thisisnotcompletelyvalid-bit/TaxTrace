from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from taxtrace.database import get_db
from taxtrace.db_models import Jurisdiction
from taxtrace.warehouse_v2.census_partition import load_government_expenditure_partition
from taxtrace.warehouse_v2.census_taxonomy import (
    CATEGORIES,
    PARENT_KEY,
    PARENT_LABEL,
    SUPPORTED_FISCAL_YEARS,
    TAXONOMY_VERSION,
    formula_for_year,
    taxonomy_audit,
)
from taxtrace.warehouse_v2.db_models import GovernmentFinanceFact

router = APIRouter(prefix="/data", tags=["census-taxonomy-v2"])


@router.get("/census-taxonomy")
def census_taxonomy(fiscal_year: int = 2022) -> dict:
    try:
        formula = formula_for_year(fiscal_year)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit = taxonomy_audit(fiscal_year)
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "formula_key": formula.key,
        "formula_label": formula.label,
        "fiscal_year": fiscal_year,
        "supported_fiscal_years": sorted(SUPPORTED_FISCAL_YEARS),
        "sources": [
            {
                "authority": "U.S. Census Bureau",
                "url": url,
            }
            for url in formula.source_urls
        ],
        "formula_notes": list(formula.notes),
        "parent": {
            "key": PARENT_KEY,
            "label": PARENT_LABEL,
            "native_item_codes": sorted(formula.direct_general_codes),
            "additive": True,
        },
        "categories": [
            {
                "key": category.key,
                "label": category.label,
                "function_codes": sorted(category.function_codes),
                "special_item_codes": sorted(category.special_item_codes),
            }
            for category in CATEGORIES
        ],
        "audit": audit,
        "semantics": {
            "raw_census_rows_additive": False,
            "partition_additive": True,
            "cross_category_addition_allowed": True,
            "year_versioned_formula": True,
            "excluded_from_parent": [
                "intergovernmental expenditure",
                "utility expenditure",
                "liquor store expenditure",
                "insurance trust expenditure",
                "historical/discontinued native codes outside the formula active for the selected year",
            ],
        },
    }


@router.get("/governments/{government_id}/finance-partition")
def government_finance_partition(
    government_id: int,
    fiscal_year: int | None = None,
    dataset_key: str | None = None,
    session: Session = Depends(get_db),
) -> dict:
    jurisdiction = session.get(Jurisdiction, government_id)
    if jurisdiction is None:
        raise HTTPException(404, "Government not found")

    if fiscal_year is None:
        fiscal_year = session.scalar(
            select(func.max(GovernmentFinanceFact.fiscal_year)).where(
                GovernmentFinanceFact.jurisdiction_id == government_id
            )
        )
    if fiscal_year is None:
        raise HTTPException(404, "No Census government-finance facts are available")

    try:
        result = load_government_expenditure_partition(
            session,
            jurisdiction_id=government_id,
            fiscal_year=fiscal_year,
            dataset_key=dataset_key,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "No READY Census finance release is available for this government/year")

    partition = result.partition
    warnings = [
        (
            "This is an additive partition of Census direct general expenditure, not a sum of all "
            "native Census finance rows. Intergovernmental transfers and enterprise/trust-system "
            "expenditure are outside this parent."
        ),
        (
            "TaxTrace presentation categories group the year-specific Census direct-general item-code "
            "formula without changing which native codes enter the parent."
        ),
    ]
    if result.coverage_type != "CENSUS":
        warnings.append(
            f"The selected release has {result.coverage_type} coverage rather than a complete Census universe."
        )
    if result.imputed_codes:
        warnings.append("One or more included/excluded Census rows are marked imputed or non-reported.")

    return {
        "government": {
            "id": jurisdiction.id,
            "code": jurisdiction.code,
            "name": jurisdiction.name,
            "level": jurisdiction.level.value,
        },
        "fiscal_year": result.fiscal_year,
        "dataset_key": result.dataset_key,
        "release": result.release_key,
        "coverage_type": result.coverage_type,
        "taxonomy_version": partition.taxonomy_version,
        "formula_key": partition.formula_key,
        "additive": True,
        "parent": {
            "key": partition.parent_key,
            "label": partition.parent_label,
            "amount": str(partition.parent_amount),
        },
        "nodes": [
            {
                "key": node.key,
                "label": node.label,
                "amount": str(node.amount),
                "item_codes": list(node.item_codes),
                "additive": True,
            }
            for node in partition.nodes
        ],
        "residual": {
            "key": "unmapped_direct_general_expenditure",
            "label": "Unmapped direct general expenditure",
            "amount": str(partition.residual_amount),
            "item_codes": list(partition.residual_codes),
            "additive": True,
        },
        "excluded_native_expenditure_codes": list(partition.excluded_codes),
        "imputed_codes": list(result.imputed_codes),
        "source_row_count": result.source_row_count,
        "conservation_difference": str(partition.conservation_difference),
        "source_urls": list(partition.source_urls),
        "formula_notes": list(partition.formula_notes),
        "warnings": warnings,
    }
