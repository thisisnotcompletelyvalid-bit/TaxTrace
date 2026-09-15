from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from taxtrace.warehouse_v2.census_taxonomy import (
    CensusCodeAmount,
    CensusExpenditurePartition,
    build_expenditure_partition,
)
from taxtrace.warehouse_v2.db_models import (
    DatasetDefinition,
    DatasetRelease,
    FinanceClassification,
    GovernmentFinanceFact,
)

# Census total-expenditure families. Only the exact direct-general code formula
# is additive in the published TaxTrace partition; the rest are retained as
# explicit excluded native expenditure codes for auditability.
EXPENDITURE_PREFIXES = frozenset({"E", "F", "G", "I", "J", "K", "L", "M", "Q", "S", "X", "Y"})


@dataclass(frozen=True)
class CensusGovernmentExpenditureResult:
    dataset_key: str
    release_key: str
    coverage_type: str
    fiscal_year: int
    source_row_count: int
    imputed_codes: tuple[str, ...]
    partition: CensusExpenditurePartition


def load_government_expenditure_partition(
    session: Session,
    *,
    jurisdiction_id: int,
    fiscal_year: int,
    dataset_key: str | None = None,
) -> CensusGovernmentExpenditureResult | None:
    """Build one government's official-code direct-general expenditure partition.

    This reads the normalized Census individual-unit facts but never sums the
    complete native result set. Only codes in the official Census direct-general
    expenditure formula enter the additive parent.
    """
    resolved_dataset_key = dataset_key or f"census-gov-finance-{fiscal_year}"
    dataset = session.scalar(
        select(DatasetDefinition).where(DatasetDefinition.key == resolved_dataset_key)
    )
    if dataset is None:
        return None

    release = session.scalar(
        select(DatasetRelease)
        .where(
            DatasetRelease.dataset_id == dataset.id,
            DatasetRelease.reference_year == fiscal_year,
            DatasetRelease.status == "READY",
        )
        .order_by(DatasetRelease.id.desc())
    )
    if release is None:
        return None

    rows = session.execute(
        select(GovernmentFinanceFact, FinanceClassification)
        .join(
            FinanceClassification,
            GovernmentFinanceFact.classification_id == FinanceClassification.id,
        )
        .where(
            GovernmentFinanceFact.jurisdiction_id == jurisdiction_id,
            GovernmentFinanceFact.dataset_release_id == release.id,
            GovernmentFinanceFact.fiscal_year == fiscal_year,
        )
        .order_by(FinanceClassification.code)
    ).all()

    expenditure_rows: list[CensusCodeAmount] = []
    imputed_codes: set[str] = set()
    for fact, classification in rows:
        code = classification.code.strip().upper()
        if code[:1] not in EXPENDITURE_PREFIXES:
            continue
        expenditure_rows.append(CensusCodeAmount(code, fact.amount))
        if fact.is_imputed:
            imputed_codes.add(code)

    partition = build_expenditure_partition(expenditure_rows)
    return CensusGovernmentExpenditureResult(
        dataset_key=dataset.key,
        release_key=release.release_key,
        coverage_type=release.coverage_type,
        fiscal_year=fiscal_year,
        source_row_count=len(expenditure_rows),
        imputed_codes=tuple(sorted(imputed_codes)),
        partition=partition,
    )
