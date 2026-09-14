from __future__ import annotations

from dataclasses import dataclass

# OMB budget function codes used by the federal budget classification. This is intentionally
# small, explicit, and versionable rather than inferred from labels at runtime.
BUDGET_FUNCTIONS: dict[str, str] = {
    "050": "National Defense",
    "150": "International Affairs",
    "250": "General Science, Space, and Technology",
    "270": "Energy",
    "300": "Natural Resources and Environment",
    "350": "Agriculture",
    "370": "Commerce and Housing Credit",
    "400": "Transportation",
    "450": "Community and Regional Development",
    "500": "Education, Training, Employment, and Social Services",
    "550": "Health",
    "570": "Medicare",
    "600": "Income Security",
    "650": "Social Security",
    "700": "Veterans Benefits and Services",
    "750": "Administration of Justice",
    "800": "General Government",
    "900": "Net Interest",
    "920": "Allowances",
    "950": "Undistributed Offsetting Receipts",
    "999": "Other / Unclassified",
}


@dataclass(frozen=True)
class BudgetFunctionInfo:
    code: str
    name: str


def function_for_subfunction(code: str | None, title: str | None = None) -> BudgetFunctionInfo:
    """Return the parent OMB budget function for a three-digit subfunction code.

    OMB subfunctions sit under a finite set of function codes. We choose the greatest standard
    function code not exceeding the subfunction, bounded by the next standard function code.
    This handles values such as 051→050, 605→600, 651→650, and 901→900 without treating all
    three-digit prefixes as valid functions.
    """
    if not code:
        return BudgetFunctionInfo("999", "Other / Unclassified")
    text = str(code).strip().zfill(3)
    if text in BUDGET_FUNCTIONS:
        return BudgetFunctionInfo(text, BUDGET_FUNCTIONS[text])
    try:
        n = int(text)
    except ValueError:
        return BudgetFunctionInfo("999", "Other / Unclassified")

    numeric = sorted((int(k), k) for k in BUDGET_FUNCTIONS if k != "999")
    candidates = [(value, key) for value, key in numeric if value <= n]
    if not candidates:
        return BudgetFunctionInfo("999", "Other / Unclassified")
    _, key = max(candidates)
    # Guard against odd synthetic/unknown codes drifting far from a real function.
    next_values = [value for value, _ in numeric if value > int(key)]
    upper = min(next_values) if next_values else 1000
    if n >= upper:
        return BudgetFunctionInfo("999", "Other / Unclassified")
    return BudgetFunctionInfo(key, BUDGET_FUNCTIONS[key])
