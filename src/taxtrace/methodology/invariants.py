from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from taxtrace.db_models import RevenuePoolMapping, RevenueType

TOLERANCE = Decimal("0.000000001")


def validate_revenue_pool_shares(session: Session, year: int) -> list[str]:
    errors: list[str] = []
    revenues = session.scalars(select(RevenueType)).all()
    for revenue in revenues:
        shares = session.scalars(
            select(RevenuePoolMapping.share).where(
                RevenuePoolMapping.revenue_type_id == revenue.id,
                RevenuePoolMapping.effective_start_year <= year,
                (RevenuePoolMapping.effective_end_year.is_(None) | (RevenuePoolMapping.effective_end_year >= year)),
            )
        ).all()
        if not shares:
            errors.append(f"{revenue.code}: no active pool mapping for {year}")
            continue
        total = sum((Decimal(s) for s in shares), Decimal("0"))
        if abs(total - Decimal("1")) > TOLERANCE:
            errors.append(f"{revenue.code}: pool shares sum to {total}, expected 1")
    return errors


def assert_conservation(input_amount: Decimal, allocated_amounts: list[Decimal], tolerance: Decimal = Decimal("0.01")) -> None:
    output = sum(allocated_amounts, Decimal("0"))
    if abs(input_amount - output) > tolerance:
        raise AssertionError(f"Conservation failure: input={input_amount}, output={output}")
