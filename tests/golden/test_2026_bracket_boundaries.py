from decimal import Decimal

import pytest

from taxtrace.enums import FilingStatus
from taxtrace.tax.engine import FederalTaxEngine
from taxtrace.tax.models import FederalTaxInput


@pytest.mark.parametrize(
    "taxable_income,expected_tax",
    [
        (Decimal("0"), Decimal("0")),
        (Decimal("12400"), Decimal("1240.00")),
        (Decimal("12401"), Decimal("1240.12")),
        (Decimal("50400"), Decimal("5800.00")),
        (Decimal("50401"), Decimal("5800.22")),
    ],
)
def test_single_2026_progressive_boundaries(taxable_income, expected_tax):
    # Construct wages by adding the 2026 single standard deduction.
    wages = taxable_income + Decimal("16100")
    result = FederalTaxEngine().calculate(
        FederalTaxInput(tax_year=2026, filing_status=FilingStatus.SINGLE, wage_income=wages)
    )
    assert result.income_tax_before_credits == expected_tax
