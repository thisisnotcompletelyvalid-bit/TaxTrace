from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from taxtrace.allocation.models import FederalReceiptRequest, FederalReceiptResult, SourceReference
from taxtrace.enums import CalculationBasis, ConfidenceGrade
from taxtrace.methodology.version import METHODOLOGY_VERSION


class FloridaGainesvilleReceiptRequest(FederalReceiptRequest):
    household_size: int = Field(default=1, ge=1, le=20)


class ModeledCategoryTax(BaseModel):
    code: str
    label: str
    baseline_amount: Decimal
    scaled_amount: Decimal
    taxability_share: Decimal
    state_taxable_amount: Decimal
    local_taxable_amount: Decimal
    notes: list[str] = Field(default_factory=list)


class ModeledSalesTaxEstimate(BaseModel):
    model_version: str = "sales-tax-9a-v1"
    calculation_basis: CalculationBasis = CalculationBasis.MODELED
    confidence: ConfidenceGrade = ConfidenceGrade.C
    reference_year: int = 2024
    income_proxy: Decimal
    cex_quintile: str
    annual_expenditure_estimate: Decimal
    state_taxable_base: Decimal
    county_taxable_base: Decimal
    florida_state_rate: Decimal
    alachua_surtax_rate: Decimal
    florida_state_sales_tax: Decimal
    alachua_county_surtax: Decimal
    combined_sales_tax: Decimal
    categories: list[ModeledCategoryTax]
    assumptions: list[str]
    sources: list[SourceReference]


class JurisdictionReceiptNode(BaseModel):
    key: str
    label: str
    allocated_amount: Decimal
    government_spending_amount: Decimal | None = None
    relation: str
    confidence: ConfidenceGrade
    calculation_basis: CalculationBasis = CalculationBasis.MODELED
    additive: bool = True
    notes: list[str] = Field(default_factory=list)
    children: list["JurisdictionReceiptNode"] = Field(default_factory=list)


class JurisdictionReceipt(BaseModel):
    jurisdiction_code: str
    jurisdiction_name: str
    fiscal_year: int
    tax_amount: Decimal
    nodes: list[JurisdictionReceiptNode]
    conservation_difference: Decimal
    warnings: list[str] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)


class SpendingReferenceNode(BaseModel):
    key: str
    label: str
    actual_expenditure: Decimal


class SpendingReference(BaseModel):
    jurisdiction_code: str
    jurisdiction_name: str
    fiscal_year: int
    metric: str = "EXPENDITURE"
    status: str = "ACTUAL"
    total_actual_expenditure: Decimal
    nodes: list[SpendingReferenceNode]
    attributable_tax_amount: Decimal | None = None
    explanation: str
    sources: list[SourceReference] = Field(default_factory=list)


class FloridaGainesvilleReceiptResult(BaseModel):
    methodology_version: str = METHODOLOGY_VERSION
    federal: FederalReceiptResult
    state_individual_income_tax: Decimal = Decimal("0.00")
    sales_tax_model: ModeledSalesTaxEstimate
    florida_state: JurisdictionReceipt
    alachua_local: JurisdictionReceipt
    gainesville_spending_reference: SpendingReference
    total_supported_calculated_and_modeled_tax: Decimal
    warnings: list[str] = Field(default_factory=list)
