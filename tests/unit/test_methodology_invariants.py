from decimal import Decimal

import pytest
from sqlalchemy import select

from taxtrace.db_models import RevenuePoolMapping, RevenueType
from taxtrace.finance.seed import seed_federal_methodology_entities
from taxtrace.methodology.invariants import assert_conservation, validate_revenue_pool_shares


def test_seeded_revenue_pool_shares_sum_to_one(db_session):
    seed_federal_methodology_entities(db_session)
    assert validate_revenue_pool_shares(db_session, 2026) == []


def test_broken_pool_share_is_detected(db_session):
    seed_federal_methodology_entities(db_session)
    social_security = db_session.scalar(select(RevenueType).where(RevenueType.code == "SS_EMPLOYEE"))
    mapping = db_session.scalar(
        select(RevenuePoolMapping).where(RevenuePoolMapping.revenue_type_id == social_security.id)
    )
    mapping.share = Decimal("0.5")
    db_session.commit()
    errors = validate_revenue_pool_shares(db_session, 2026)
    assert any("SS_EMPLOYEE" in error for error in errors)


def test_conservation_assertion():
    assert_conservation(Decimal("100"), [Decimal("33.33"), Decimal("66.67")])
    with pytest.raises(AssertionError):
        assert_conservation(Decimal("100"), [Decimal("40"), Decimal("50")])
