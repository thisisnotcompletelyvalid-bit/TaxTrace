from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from taxtrace.enums import CalculationBasis
from taxtrace.tax.models import CalculationStep, FederalTaxInput, FederalTaxResult, TaxBracketStep
from taxtrace.tax.rules import RuleRepository

CENT = Decimal("0.01")
ZERO = Decimal("0")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class FederalTaxEngine:
    """Federal tax engine for the explicitly supported Phase 2 scope.

    This is a liability calculator, not a tax-return preparation system. It supports W-2 wages,
    the standard deduction, ordinary income tax brackets, employee FICA, Additional Medicare Tax,
    CTC/ODC phaseout, and the common ACTC earned-income formula.
    """

    def __init__(self, rules: RuleRepository | None = None):
        self.rules_repo = rules or RuleRepository()

    def calculate(self, inp: FederalTaxInput) -> FederalTaxResult:
        rules = self.rules_repo.load(inp.tax_year)
        wages = inp.total_wages
        standard_deduction = rules.standard_deduction(inp.filing_status)
        taxable_income = max(ZERO, wages - standard_deduction)
        income_tax_before_credits, bracket_steps = self._ordinary_income_tax(
            taxable_income, rules.brackets(inp.filing_status)
        )

        potential_dependent_credit = (
            rules.credit("child_tax_credit_per_child") * inp.qualifying_children_under_17
            + rules.credit("other_dependent_credit_per_dependent") * inp.other_dependents
        )
        phased_credit = self._phase_dependent_credit(
            potential_dependent_credit,
            wages,
            rules.credit_phaseout_threshold(inp.filing_status),
            rules.credit("phaseout_increment"),
            rules.credit("phaseout_reduction_per_increment"),
        )
        nonrefundable_credit = min(income_tax_before_credits, phased_credit)
        income_tax_liability = max(ZERO, income_tax_before_credits - nonrefundable_credit)

        unused_child_credit = max(ZERO, phased_credit - nonrefundable_credit)
        refundable_actc = self._actc(
            unused_credit=unused_child_credit,
            earned_income=wages,
            qualifying_children=inp.qualifying_children_under_17,
            income_floor=rules.credit("additional_child_tax_credit_earned_income_floor"),
            rate=rules.credit("additional_child_tax_credit_rate"),
            per_child_cap=rules.credit("additional_child_tax_credit_max_per_child"),
        )

        ss_rate = rules.fica("social_security_employee_rate")
        ss_base = rules.fica("social_security_wage_base")
        primary_ss = min(inp.wage_income, ss_base) * ss_rate
        spouse_ss = min(inp.spouse_wage_income, ss_base) * ss_rate
        social_security = primary_ss + spouse_ss

        medicare = wages * rules.fica("medicare_employee_rate")
        additional_threshold = rules.additional_medicare_threshold(inp.filing_status)
        additional_medicare = max(ZERO, wages - additional_threshold) * rules.fica(
            "additional_medicare_rate"
        )
        payroll = social_security + medicare + additional_medicare
        personal_liability = income_tax_liability + payroll

        limitations: list[str] = []
        if inp.qualifying_children_under_17 >= 3:
            limitations.append(
                "For three or more qualifying children, Schedule 8812 can provide an alternative ACTC method based on Social Security/Medicare taxes. Phase 2 intentionally uses only the common earned-income formula; review such cases before treating the refundable credit as return-preparation accurate."
            )
        assumptions = [
            "All supplied wage income is W-2 wage income subject to ordinary federal income tax, Social Security tax, and Medicare tax.",
            "The taxpayer takes the standard deduction and has no above-the-line adjustments or itemized deductions.",
            "The qualifying-child and other-dependent counts supplied by the caller already satisfy IRS eligibility rules and identification-number requirements.",
            "Refundable credits are reported separately and do not make 'taxes paid' negative for TaxTrace allocation purposes.",
        ]

        steps = [
            CalculationStep(label="Gross W-2 wages", amount=money(wages)),
            CalculationStep(label="Standard deduction", amount=money(standard_deduction)),
            CalculationStep(label="Taxable income", amount=money(taxable_income)),
            CalculationStep(label="Income tax before credits", amount=money(income_tax_before_credits)),
            CalculationStep(label="Nonrefundable CTC/ODC used", amount=money(nonrefundable_credit)),
            CalculationStep(label="Federal income tax liability", amount=money(income_tax_liability)),
            CalculationStep(label="Employee Social Security tax", amount=money(social_security)),
            CalculationStep(label="Employee Medicare tax", amount=money(medicare)),
            CalculationStep(label="Additional Medicare tax", amount=money(additional_medicare)),
            CalculationStep(label="Refundable ACTC shown separately", amount=money(refundable_actc)),
        ]

        return FederalTaxResult(
            tax_year=inp.tax_year,
            filing_status=inp.filing_status,
            calculation_basis=CalculationBasis.CALCULATED,
            gross_wages=money(wages),
            standard_deduction=money(standard_deduction),
            taxable_income=money(taxable_income),
            income_tax_before_credits=money(income_tax_before_credits),
            nonrefundable_dependent_credit=money(nonrefundable_credit),
            refundable_additional_child_tax_credit=money(refundable_actc),
            federal_income_tax_liability=money(income_tax_liability),
            social_security_tax=money(social_security),
            medicare_tax=money(medicare),
            additional_medicare_tax=money(additional_medicare),
            total_payroll_tax=money(payroll),
            total_personal_tax_liability=money(personal_liability),
            refundable_credits_separately=money(refundable_actc),
            bracket_steps=bracket_steps,
            calculation_steps=steps,
            assumptions=assumptions,
            limitations=limitations,
        )

    @staticmethod
    def _ordinary_income_tax(
        taxable_income: Decimal, brackets: list[tuple[Decimal | None, Decimal]]
    ) -> tuple[Decimal, list[TaxBracketStep]]:
        lower = ZERO
        remaining = taxable_income
        total = ZERO
        steps: list[TaxBracketStep] = []
        for upper, rate in brackets:
            if remaining <= ZERO:
                break
            band_width = remaining if upper is None else min(remaining, upper - lower)
            if band_width < ZERO:
                band_width = ZERO
            tax = band_width * rate
            total += tax
            steps.append(
                TaxBracketStep(
                    lower=money(lower),
                    upper=money(upper) if upper is not None else None,
                    rate=rate,
                    taxable_amount=money(band_width),
                    tax=money(tax),
                )
            )
            remaining -= band_width
            if upper is not None:
                lower = upper
        return money(total), steps

    @staticmethod
    def _phase_dependent_credit(
        credit: Decimal,
        modified_agi: Decimal,
        threshold: Decimal,
        increment: Decimal,
        reduction_per_increment: Decimal,
    ) -> Decimal:
        excess = max(ZERO, modified_agi - threshold)
        if excess == ZERO:
            return credit
        increments = (excess / increment).to_integral_value(rounding=ROUND_CEILING)
        return max(ZERO, credit - increments * reduction_per_increment)

    @staticmethod
    def _actc(
        unused_credit: Decimal,
        earned_income: Decimal,
        qualifying_children: int,
        income_floor: Decimal,
        rate: Decimal,
        per_child_cap: Decimal,
    ) -> Decimal:
        if qualifying_children <= 0 or unused_credit <= ZERO:
            return ZERO
        earned_income_formula = max(ZERO, earned_income - income_floor) * rate
        child_cap = per_child_cap * qualifying_children
        return money(min(unused_credit, earned_income_formula, child_cap))
