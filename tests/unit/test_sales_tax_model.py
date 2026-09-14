from decimal import Decimal

from taxtrace.enums import CalculationBasis, ConfidenceGrade
from taxtrace.jurisdictional.sales_tax import FloridaSalesTaxModel9A


def test_phase9a_uses_bls_quintile_and_models_sales_tax():
    result = FloridaSalesTaxModel9A().estimate(Decimal("50000"))
    assert result.calculation_basis == CalculationBasis.MODELED
    assert result.confidence == ConfidenceGrade.C
    assert result.cex_quintile == "second"
    assert result.annual_expenditure_estimate == Decimal("50054.00")
    assert result.florida_state_sales_tax == Decimal("791.35")
    assert result.alachua_county_surtax == Decimal("197.84")
    assert result.combined_sales_tax == Decimal("989.19")


def test_phase9a_local_vehicle_cap_is_visible_and_reduces_local_base():
    result = FloridaSalesTaxModel9A().estimate(Decimal("200000"))
    vehicle = next(row for row in result.categories if row.code == "vehicle_purchases")
    assert vehicle.state_taxable_amount > Decimal("5000")
    assert vehicle.local_taxable_amount == Decimal("5000.00")
    assert result.county_taxable_base < result.state_taxable_base
    assert vehicle.notes


def test_phase9a_does_not_model_property_or_fuel_tax():
    result = FloridaSalesTaxModel9A().estimate(Decimal("50000"))
    gasoline = next(row for row in result.categories if row.code == "gasoline")
    assert gasoline.state_taxable_amount == Decimal("0.00")
    assert any("Property tax" in note or "property taxes" in note for note in result.assumptions)
