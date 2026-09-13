from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from taxtrace.enums import CalculationBasis, FilingStatus


class FederalTaxInput(BaseModel):
    tax_year: int = 2026
    filing_status: FilingStatus
    wage_income: Decimal = Field(default=Decimal("0"), ge=0)
    spouse_wage_income: Decimal = Field(default=Decimal("0"), ge=0)
    qualifying_children_under_17: int = Field(default=0, ge=0)
    other_dependents: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_spouse_wages(self):
        if self.filing_status != FilingStatus.MARRIED_FILING_JOINTLY and self.spouse_wage_income != 0:
            raise ValueError("spouse_wage_income is only supported for married_filing_jointly")
        return self

    @property
    def total_wages(self) -> Decimal:
        return self.wage_income + self.spouse_wage_income


class TaxBracketStep(BaseModel):
    lower: Decimal
    upper: Decimal | None
    rate: Decimal
    taxable_amount: Decimal
    tax: Decimal


class CalculationStep(BaseModel):
    label: str
    amount: Decimal
    note: str | None = None


class FederalTaxResult(BaseModel):
    tax_year: int
    filing_status: FilingStatus
    calculation_basis: CalculationBasis = CalculationBasis.CALCULATED
    gross_wages: Decimal
    standard_deduction: Decimal
    taxable_income: Decimal
    income_tax_before_credits: Decimal
    nonrefundable_dependent_credit: Decimal
    refundable_additional_child_tax_credit: Decimal
    federal_income_tax_liability: Decimal
    social_security_tax: Decimal
    medicare_tax: Decimal
    additional_medicare_tax: Decimal
    total_payroll_tax: Decimal
    total_personal_tax_liability: Decimal
    refundable_credits_separately: Decimal
    bracket_steps: list[TaxBracketStep]
    calculation_steps: list[CalculationStep]
    assumptions: list[str]
    limitations: list[str]
