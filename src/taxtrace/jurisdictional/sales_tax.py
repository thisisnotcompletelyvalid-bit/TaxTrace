from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from importlib.resources import files

from taxtrace.allocation.models import SourceReference
from taxtrace.jurisdictional.models import ModeledCategoryTax, ModeledSalesTaxEstimate

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


class FloridaSalesTaxModel9A:
    """Quick-mode statistical estimator for Florida + Alachua general sales taxes.

    This is intentionally not a tax-return calculator. It chooses a 2024 BLS Consumer Expenditure
    income quintile from wage income, scales a transparent national expenditure profile, then applies
    explicit Florida taxability assumptions. Results are always MODELED.
    """

    def __init__(self):
        path = files("taxtrace").joinpath("data/statistical/sales_tax_9a.json")
        self.rules = json.loads(path.read_text())

    def estimate(self, wage_income: Decimal, spouse_wage_income: Decimal = Decimal("0")) -> ModeledSalesTaxEstimate:
        income = Decimal(wage_income) + Decimal(spouse_wage_income)
        quintile = self._quintile(income)
        annual_total = Decimal(str(quintile["annual_expenditures"]))
        scale = annual_total / Decimal(str(self.rules["all_consumer_units_total"]))
        state_rate = Decimal(str(self.rules["florida_state_rate"]))
        local_rate = Decimal(str(self.rules["alachua_surtax_rate"]))
        local_cap = Decimal(str(self.rules["local_tangible_property_cap"]))

        categories: list[ModeledCategoryTax] = []
        state_base = Decimal("0")
        local_base = Decimal("0")
        for row in self.rules["categories"]:
            baseline = Decimal(str(row["baseline"]))
            scaled = baseline * scale
            share = Decimal(str(row["taxability"]))
            state_taxable = scaled * share
            local_taxable = state_taxable
            notes: list[str] = []
            if row.get("local_cap_approximation") and local_taxable > local_cap:
                local_taxable = local_cap
                notes.append(
                    "Alachua's statutory $5,000 per-item surtax cap is approximated here by capping "
                    "the annual modeled vehicle-purchase component; actual transaction-level tax may differ."
                )
            categories.append(
                ModeledCategoryTax(
                    code=row["code"],
                    label=row["label"],
                    baseline_amount=money(baseline),
                    scaled_amount=money(scaled),
                    taxability_share=share,
                    state_taxable_amount=money(state_taxable),
                    local_taxable_amount=money(local_taxable),
                    notes=notes,
                )
            )
            state_base += state_taxable
            local_base += local_taxable

        state_base = money(state_base)
        local_base = money(local_base)
        state_tax = money(state_base * state_rate)
        local_tax = money(local_base * local_rate)
        source = SourceReference(
            id=0,
            name="U.S. Bureau of Labor Statistics — Consumer Expenditures, 2024",
            url=self.rules["source_url"],
            reference_period="Calendar year 2024",
            parser_version=self.rules["model_version"],
        )
        assumptions = list(self.rules["notes"])
        assumptions.append(
            f"Income proxy ${money(income)} selects the {quintile['name']} 2024 BLS income quintile, "
            f"whose average annual expenditures were ${money(annual_total)}."
        )
        return ModeledSalesTaxEstimate(
            income_proxy=money(income),
            cex_quintile=quintile["name"],
            annual_expenditure_estimate=money(annual_total),
            state_taxable_base=state_base,
            county_taxable_base=local_base,
            florida_state_rate=state_rate,
            alachua_surtax_rate=local_rate,
            florida_state_sales_tax=state_tax,
            alachua_county_surtax=local_tax,
            combined_sales_tax=money(state_tax + local_tax),
            categories=categories,
            assumptions=assumptions,
            sources=[source],
        )

    def _quintile(self, income: Decimal) -> dict:
        for row in self.rules["quintiles"]:
            lower = Decimal(str(row["lower_bound"]))
            upper = row["upper_bound"]
            if income >= lower and (upper is None or income < Decimal(str(upper))):
                return row
        return self.rules["quintiles"][-1]
