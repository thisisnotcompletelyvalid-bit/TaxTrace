from decimal import Decimal

import pytest

from taxtrace.enums import FilingStatus
from taxtrace.tax import FederalTaxEngine, FederalTaxInput


@pytest.fixture
def engine():
    return FederalTaxEngine()


def test_single_50000_wages(engine):
    r = engine.calculate(FederalTaxInput(filing_status=FilingStatus.SINGLE, wage_income=50000))
    assert r.standard_deduction == Decimal("16100.00")
    assert r.taxable_income == Decimal("33900.00")
    assert r.income_tax_before_credits == Decimal("3820.00")
    assert r.social_security_tax == Decimal("3100.00")
    assert r.medicare_tax == Decimal("725.00")
    assert r.total_personal_tax_liability == Decimal("7645.00")


def test_joint_social_security_wage_base_is_per_spouse(engine):
    r = engine.calculate(
        FederalTaxInput(
            filing_status=FilingStatus.MARRIED_FILING_JOINTLY,
            wage_income=150000,
            spouse_wage_income=150000,
        )
    )
    assert r.social_security_tax == Decimal("18600.00")
    assert r.additional_medicare_tax == Decimal("450.00")


def test_single_social_security_cap(engine):
    r = engine.calculate(FederalTaxInput(filing_status=FilingStatus.SINGLE, wage_income=300000))
    assert r.social_security_tax == Decimal("11439.00")  # 184,500 * 6.2%
    assert r.additional_medicare_tax == Decimal("900.00")


def test_child_credit_and_refundable_component(engine):
    r = engine.calculate(
        FederalTaxInput(
            filing_status=FilingStatus.SINGLE,
            wage_income=25000,
            qualifying_children_under_17=1,
        )
    )
    # Taxable income 8,900 -> $890 tax, with remaining credit potentially refundable.
    assert r.income_tax_before_credits == Decimal("890.00")
    assert r.nonrefundable_dependent_credit == Decimal("890.00")
    assert r.federal_income_tax_liability == Decimal("0.00")
    assert r.refundable_additional_child_tax_credit == Decimal("1310.00")


def test_ctc_phaseout_rounds_excess_up_to_next_thousand(engine):
    r = engine.calculate(
        FederalTaxInput(
            filing_status=FilingStatus.SINGLE,
            wage_income=200001,
            qualifying_children_under_17=1,
        )
    )
    assert r.nonrefundable_dependent_credit == Decimal("2150.00")


def test_other_dependent_credit(engine):
    r = engine.calculate(
        FederalTaxInput(
            filing_status=FilingStatus.SINGLE,
            wage_income=80000,
            other_dependents=1,
        )
    )
    assert r.nonrefundable_dependent_credit == Decimal("500.00")


def test_unsupported_tax_year(engine):
    with pytest.raises(ValueError):
        engine.calculate(FederalTaxInput(tax_year=2024, filing_status=FilingStatus.SINGLE, wage_income=50000))


def test_spouse_wages_rejected_for_non_joint():
    with pytest.raises(ValueError):
        FederalTaxInput(
            filing_status=FilingStatus.SINGLE,
            wage_income=50000,
            spouse_wage_income=10000,
        )
