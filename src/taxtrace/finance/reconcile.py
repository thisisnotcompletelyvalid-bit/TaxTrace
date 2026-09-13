from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from taxtrace.db_models import ReconciliationResult, SpendFact, TreasuryAggregate
from taxtrace.enums import FinancialMetric


@dataclass(frozen=True)
class ReconciliationPolicy:
    pass_threshold: Decimal = Decimal("0.001")  # 0.1%
    review_threshold: Decimal = Decimal("0.01")  # 1%

    def status(self, relative_difference: Decimal | None) -> str:
        if relative_difference is None:
            return "REVIEW"
        value = abs(relative_difference)
        if value <= self.pass_threshold:
            return "PASS"
        if value <= self.review_threshold:
            return "REVIEW"
        return "FAIL"


def compare_values(
    *,
    left: Decimal,
    right: Decimal,
    policy: ReconciliationPolicy | None = None,
) -> tuple[Decimal, Decimal | None, str]:
    policy = policy or ReconciliationPolicy()
    difference = left - right
    relative = None if right == 0 else difference / abs(right)
    return difference, relative, policy.status(relative)


def reconcile_omb_outlays_to_treasury(
    session: Session,
    fiscal_year: int,
    *,
    policy: ReconciliationPolicy | None = None,
) -> ReconciliationResult:
    """Compare OMB account-level outlays with Treasury's explicitly named total outlays row.

    The function intentionally does not sum every Treasury row: Treasury summary workbooks can
    contain subtotals and totals. It locates a row whose normalized name is exactly 'total outlays'
    or 'total', and fails if no unambiguous aggregate exists.
    """
    policy = policy or ReconciliationPolicy()
    omb_total = session.scalar(
        select(func.coalesce(func.sum(SpendFact.amount), 0)).where(
            SpendFact.fiscal_year == fiscal_year,
            SpendFact.record_scope == "omb_account_outlay",
            SpendFact.metric == FinancialMetric.OUTLAY,
        )
    )
    treasury_rows = session.scalars(
        select(TreasuryAggregate).where(
            TreasuryAggregate.fiscal_year == fiscal_year,
            TreasuryAggregate.aggregate_type == "outlays",
        )
    ).all()
    matches = [
        row
        for row in treasury_rows
        if " ".join(row.category_name.lower().split()) in {"total outlays", "total"}
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one Treasury total outlays row for FY{fiscal_year}; found {len(matches)}"
        )
    treasury_total = Decimal(matches[0].amount)
    omb_total = Decimal(omb_total)
    diff, rel, status = compare_values(left=omb_total, right=treasury_total, policy=policy)
    session.execute(
        delete(ReconciliationResult).where(
            ReconciliationResult.fiscal_year == fiscal_year,
            ReconciliationResult.comparison_name == "OMB account outlays vs Treasury total outlays",
        )
    )
    result = ReconciliationResult(
        fiscal_year=fiscal_year,
        comparison_name="OMB account outlays vs Treasury total outlays",
        left_value=omb_total,
        right_value=treasury_total,
        absolute_difference=abs(diff),
        relative_difference=rel,
        status=status,
        metadata_json={
            "left": "OMB Public Budget Database account outlays",
            "right": "Treasury Combined Statement total outlays",
            "pass_threshold": str(policy.pass_threshold),
            "review_threshold": str(policy.review_threshold),
        },
    )
    session.add(result)
    session.commit()
    session.refresh(result)
    return result
