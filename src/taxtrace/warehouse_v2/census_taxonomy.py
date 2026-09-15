from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

TAXONOMY_VERSION = "1.2.0"
PARENT_KEY = "direct_general_expenditure"
PARENT_LABEL = "Direct general expenditure"

STATE_LOCAL_SUMMARY_METHODOLOGY_URL = (
    "https://www2.census.gov/programs-surveys/gov-finances/technical-documentation/"
    "classification-manual/methodology_for_summary_tabulations.pdf"
)
STATE_2022_SUMMARY_METHODOLOGY_URL = (
    "https://www2.census.gov/programs-surveys/state/technical-documentation/"
    "methodology/methodology_summary_tabulations.xlsx"
)
STATE_2022_TECHNICAL_DOCUMENTATION_URL = (
    "https://www2.census.gov/programs-surveys/state/technical-documentation/"
    "complete-technical-documentation/statetechdoc2022.pdf"
)
STATE_LOCAL_2022_CONTENT_CHANGES_URL = (
    "https://www2.census.gov/programs-surveys/gov-finances/tables/2022/"
    "Summary%20of%20Content%20Changes%20for%20State%20and%20Local%20Government%20Finance%20Surveys.pdf"
)


@dataclass(frozen=True)
class CensusFormula:
    key: str
    label: str
    supported_years: frozenset[int]
    direct_general_codes: frozenset[str]
    source_urls: tuple[str, ...]
    notes: tuple[str, ...]


# Census's Summary Tabulations workbook defines SF0176, "Expenditure - Direct
# Expenditure - Total General Expenditure", with an explicit native-code list.
# For 2022, and again for 2023-2024, the list is the same 72 codes below.
#
# Keep this list literal. In particular, do not infer parent membership from a
# function suffix or an E/F prefix. The raw finance files contain expenditure-
# shaped codes such as E24/F24 (fire protection), utility codes 91-94, and
# liquor-store code 90 that are not members of the published SF0176 formula.
POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES = frozenset(
    {
        "E01",
        "E03",
        "E04",
        "E05",
        "E12",
        "E16",
        "E18",
        "E21",
        "E22",
        "E23",
        "E25",
        "E26",
        "E29",
        "E31",
        "E32",
        "E36",
        "E44",
        "E45",
        "E50",
        "E52",
        "E54",
        "E55",
        "E56",
        "E59",
        "E60",
        "E61",
        "E62",
        "E66",
        "E77",
        "E79",
        "E80",
        "E81",
        "E85",
        "E87",
        "E89",
        "F01",
        "F03",
        "F04",
        "F05",
        "F12",
        "F16",
        "F18",
        "F21",
        "F22",
        "F23",
        "F25",
        "F26",
        "F29",
        "F31",
        "F32",
        "F36",
        "F44",
        "F45",
        "F50",
        "F52",
        "F54",
        "F55",
        "F56",
        "F59",
        "F60",
        "F61",
        "F62",
        "F66",
        "F77",
        "F79",
        "F80",
        "F81",
        "F85",
        "F87",
        "F89",
        "I89",
        "J19",
    }
)

POST_2022_FORMULA = CensusFormula(
    key="census-sf0176-direct-general-2022-2024",
    label="Census SF0176 direct general expenditure, 2022-2024 code system",
    supported_years=frozenset({2022, 2024}),
    direct_general_codes=POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES,
    source_urls=(
        STATE_2022_SUMMARY_METHODOLOGY_URL,
        STATE_LOCAL_2022_CONTENT_CHANGES_URL,
        STATE_2022_TECHNICAL_DOCUMENTATION_URL,
        STATE_LOCAL_SUMMARY_METHODOLOGY_URL,
    ),
    notes=(
        "Parent membership is the literal SF0176 ITEM_CODES_2022 / ITEM_CODES_2023_2024 list from Census's Summary Tabulations workbook.",
        "F is the consolidated capital-expenditure family effective 2022; G/K capital rows are not additive beside F.",
        "E74/E75 and J67/J68 are discontinued from this 2022 formula; J85 is not a member either.",
        "Environmental-health code 27 is not a member of SF0176.",
        "Fire-protection codes E24/F24 are reported in raw Census finance data but are not members of the published SF0176 direct-general formula.",
        "Utility codes 91-94, liquor-store code 90, and their related interest/capital codes are outside this direct-general parent.",
        "The current revised 2022 published national SF0176 control does not equal the sum of the current public-use native codes in the static methodology formula; TaxTrace records that as a source-level aggregate reconciliation issue rather than altering unit-level formula membership.",
    ),
)

FORMULAS = (POST_2022_FORMULA,)
SUPPORTED_FISCAL_YEARS = frozenset(
    year for formula in FORMULAS for year in formula.supported_years
)


@dataclass(frozen=True)
class CensusReceiptCategory:
    key: str
    label: str
    function_codes: frozenset[str]
    special_item_codes: frozenset[str] = frozenset()


# TaxTrace presentation groups do not determine membership in the additive
# parent. The year-specific Census formula does that first; these groups then
# assign every included native code to exactly one public category.
CATEGORIES = (
    CensusReceiptCategory(
        "general_government",
        "General government and administration",
        frozenset({"23", "26", "29", "31"}),
    ),
    CensusReceiptCategory(
        "education_libraries",
        "Education and libraries",
        frozenset({"12", "16", "18", "21", "52"}),
        frozenset({"J19"}),
    ),
    CensusReceiptCategory(
        "public_welfare_human_services",
        "Public welfare and human services",
        frozenset({"22", "77", "79", "85"}),
    ),
    CensusReceiptCategory("health", "Health", frozenset({"32"})),
    CensusReceiptCategory("hospitals", "Hospitals", frozenset({"36"})),
    CensusReceiptCategory("police", "Police protection", frozenset({"62"})),
    CensusReceiptCategory("corrections", "Corrections", frozenset({"04", "05"})),
    CensusReceiptCategory("judicial_legal", "Judicial and legal", frozenset({"25"})),
    CensusReceiptCategory(
        "protective_regulation",
        "Protective inspection and regulation",
        frozenset({"66"}),
    ),
    CensusReceiptCategory(
        "transportation",
        "Transportation",
        frozenset({"01", "44", "45", "60", "87"}),
    ),
    CensusReceiptCategory(
        "natural_resources_environment",
        "Natural resources and environment",
        frozenset({"54", "55", "56", "59"}),
    ),
    CensusReceiptCategory("parks_recreation", "Parks and recreation", frozenset({"61"})),
    CensusReceiptCategory(
        "housing_community_development",
        "Housing and community development",
        frozenset({"50"}),
    ),
    CensusReceiptCategory(
        "sewerage_solid_waste",
        "Sewerage and solid waste management",
        frozenset({"80", "81"}),
    ),
    CensusReceiptCategory(
        "interest_general_debt",
        "Interest on general debt",
        frozenset(),
        frozenset({"I89"}),
    ),
    CensusReceiptCategory(
        "other_unallocable",
        "Other and unallocable general expenditure",
        frozenset({"03", "89"}),
    ),
)

CATEGORY_BY_KEY = {category.key: category for category in CATEGORIES}


@dataclass(frozen=True)
class CensusCodeAmount:
    item_code: str
    amount: Decimal


@dataclass(frozen=True)
class CensusPartitionNode:
    key: str
    label: str
    amount: Decimal
    item_codes: tuple[str, ...]


@dataclass(frozen=True)
class CensusExpenditurePartition:
    taxonomy_version: str
    formula_key: str
    fiscal_year: int
    parent_key: str
    parent_label: str
    parent_amount: Decimal
    nodes: tuple[CensusPartitionNode, ...]
    residual_amount: Decimal
    residual_codes: tuple[str, ...]
    excluded_codes: tuple[str, ...]
    conservation_difference: Decimal
    source_urls: tuple[str, ...]
    formula_notes: tuple[str, ...]


def formula_for_year(fiscal_year: int) -> CensusFormula:
    matches = [formula for formula in FORMULAS if fiscal_year in formula.supported_years]
    if len(matches) != 1:
        raise ValueError(
            f"No unique Census additive expenditure formula is implemented for fiscal year {fiscal_year}"
        )
    return matches[0]


def category_for_item_code(
    item_code: str,
    *,
    fiscal_year: int,
) -> CensusReceiptCategory | None:
    code = item_code.strip().upper()
    formula = formula_for_year(fiscal_year)
    if code not in formula.direct_general_codes:
        return None

    # Special I/J items have object semantics that override their numeric suffix.
    for category in CATEGORIES:
        if code in category.special_item_codes:
            return category

    if code[:1] in {"E", "F"} and len(code) == 3:
        for category in CATEGORIES:
            if code[1:] in category.function_codes:
                return category
    return None


def taxonomy_audit(fiscal_year: int) -> dict[str, object]:
    formula = formula_for_year(fiscal_year)
    assignments: dict[str, list[str]] = {}
    for code in sorted(formula.direct_general_codes):
        category = category_for_item_code(code, fiscal_year=fiscal_year)
        if category is not None:
            assignments.setdefault(code, []).append(category.key)
    missing = tuple(sorted(formula.direct_general_codes - assignments.keys()))
    duplicates = {
        code: tuple(keys)
        for code, keys in assignments.items()
        if len(keys) != 1
    }
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "formula_key": formula.key,
        "fiscal_year": fiscal_year,
        "official_parent_code_count": len(formula.direct_general_codes),
        "assigned_code_count": len(assignments),
        "missing_codes": missing,
        "duplicate_assignments": duplicates,
        "valid": not missing and not duplicates,
    }


def build_expenditure_partition(
    rows: Iterable[CensusCodeAmount],
    *,
    fiscal_year: int,
) -> CensusExpenditurePartition:
    formula = formula_for_year(fiscal_year)
    by_code: dict[str, Decimal] = {}
    excluded: set[str] = set()
    for row in rows:
        code = row.item_code.strip().upper()
        amount = Decimal(row.amount)
        if code in formula.direct_general_codes:
            by_code[code] = by_code.get(code, Decimal("0.00")) + amount
        else:
            excluded.add(code)

    category_codes: dict[str, list[str]] = {category.key: [] for category in CATEGORIES}
    category_amounts: dict[str, Decimal] = {
        category.key: Decimal("0.00") for category in CATEGORIES
    }
    residual_codes: list[str] = []
    residual_amount = Decimal("0.00")

    for code, amount in sorted(by_code.items()):
        category = category_for_item_code(code, fiscal_year=fiscal_year)
        if category is None:
            residual_codes.append(code)
            residual_amount += amount
            continue
        category_codes[category.key].append(code)
        category_amounts[category.key] += amount

    nodes = tuple(
        CensusPartitionNode(
            key=category.key,
            label=category.label,
            amount=category_amounts[category.key],
            item_codes=tuple(category_codes[category.key]),
        )
        for category in CATEGORIES
        if category_amounts[category.key] != 0
    )
    parent_amount = sum(by_code.values(), Decimal("0.00"))
    child_total = sum((node.amount for node in nodes), Decimal("0.00")) + residual_amount
    return CensusExpenditurePartition(
        taxonomy_version=TAXONOMY_VERSION,
        formula_key=formula.key,
        fiscal_year=fiscal_year,
        parent_key=PARENT_KEY,
        parent_label=PARENT_LABEL,
        parent_amount=parent_amount,
        nodes=nodes,
        residual_amount=residual_amount,
        residual_codes=tuple(residual_codes),
        excluded_codes=tuple(sorted(excluded)),
        conservation_difference=parent_amount - child_total,
        source_urls=formula.source_urls,
        formula_notes=formula.notes,
    )
