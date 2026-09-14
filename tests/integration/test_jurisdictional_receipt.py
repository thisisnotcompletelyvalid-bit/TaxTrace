from decimal import Decimal

from taxtrace.config import PROJECT_ROOT
from taxtrace.finance.fixtures import ingest_all_fixtures
from taxtrace.finance.seed import seed_federal_methodology_entities
from taxtrace.jurisdictional.engine import FloridaGainesvilleEngine
from taxtrace.jurisdictional.fixtures import ingest_jurisdiction_fixtures
from taxtrace.jurisdictional.models import FloridaGainesvilleReceiptRequest


def test_florida_gainesville_receipt_conserves_state_and_local_tax(db_session):
    seed_federal_methodology_entities(db_session)
    ingest_all_fixtures(db_session, root=PROJECT_ROOT / "data" / "fixtures")
    ingest_jurisdiction_fixtures(db_session, root=PROJECT_ROOT / "data" / "fixtures")

    request = FloridaGainesvilleReceiptRequest(
        tax_year=2026,
        spending_fiscal_year=2025,
        filing_status="single",
        wage_income=Decimal("50000"),
    )
    result = FloridaGainesvilleEngine().calculate(db_session, request)

    assert result.federal.total_allocable_taxes == Decimal("7645.00")
    assert result.sales_tax_model.florida_state_sales_tax == Decimal("791.35")
    assert result.sales_tax_model.alachua_county_surtax == Decimal("197.84")
    assert result.florida_state.conservation_difference == Decimal("0.00")
    assert result.alachua_local.conservation_difference == Decimal("0.00")
    assert sum(node.allocated_amount for node in result.florida_state.nodes) == Decimal("791.35")
    assert sum(node.allocated_amount for node in result.alachua_local.nodes) == Decimal("197.84")
    assert result.gainesville_spending_reference.total_actual_expenditure == Decimal("185815738.00")
    assert result.gainesville_spending_reference.attributable_tax_amount is None
    assert result.total_supported_calculated_and_modeled_tax == Decimal("8634.19")

    wspp = next(node for node in result.alachua_local.nodes if node.key.endswith(":wspp"))
    assert sum(child.allocated_amount for child in wspp.children) == wspp.allocated_amount
    gainesville = next(child for child in wspp.children if child.key.endswith(":gainesville"))
    assert gainesville.allocated_amount > Decimal("0")
