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
STATE_LOCAL_2022_CONTENT_CHANGES_URL = (
    "https://www2.census.gov/programs-surveys/gov-finances/tables/2022/"
    "Summary%20of%20Content%20Changes%20for%20State%20and%20Local%20Government%20Finance%20Surveys.pdf"
)
STATE_LOCAL_CURRENT_AGGREGATE_DATA_URL = (
    "https://www2.census.gov/programs-surveys/gov-finances/data/GS00LOCALFIN.zip"
)
STATE_LOCAL_2022_INDIVIDUAL_UNIT_URL = (
    "https://www2.census.gov/programs-surveys/gov-finances/tables/2022/"
    "2022_Individual_Unit_File.zip"
)


@dataclass(frozen=True)
class CensusFormula:
    key: str
    label: str
    supported_years: frozenset[int]
    direct_general_codes: frozenset[str]
    source_urls: tuple[str, ...]
    notes: tuple[str, ...]


# The combined State and Local Government Finances summary-tabulation manual
# defines Direct General Expenditure from E/F/G functional expenditure rows,
# I89 interest on general debt, and J assistance rows. The 2022 content changes
# alter the native code system: F becomes the consolidated capital family, G/K
# capital families are discontinued, welfare detail 74/75 and J67/J68/J85 is
# consolidated into E79, and environmental-health code 27 is recoded into the
# major functions it serves. Fire protection (24) remains a general-expenditure
# function. Utilities 91-94 and liquor stores 90 remain separate sectors.
#
# This is therefore an explicit post-2022 adaptation of the *combined state and
# local* formula. Do not substitute the similarly named State Government
# Finances SF0176 workbook: it is a different program/table family and omits
# local-government function 24 while including state-only function 54.
POST_2022_DIRECT_GENERAL_FUNCTION_CODES = frozenset(
    {
        "01",
        "03",
        "04",
        "05",
        "12",
        "16",
        "18",
        "21",
        "22",
        "23",
        "24",
        "25",
        "26",
        "29",
        "31",
        "32",
        "36",
        "44",
        "45",
        "50",
        "52",
        "55",
        "56",
        "59",
        "60",
        "61",
        "62",
        "66",
        "77",
        "79",
        "80",
        "81",
        "85",
        "87",
        "89",
    }
)
POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES = frozenset(
    {
        *(f"E{function_code}" for function_code in POST_2022_DIRECT_GENERAL_FUNCTION_CODES),
        *(f"F{function_code}" for function_code in POST_2022_DIRECT_GENERAL_FUNCTION_CODES),
        "I89",
        "J19",
    }
)

POST_2022_FORMULA = CensusFormula(
    key="census-state-local-direct-general-2022-2024",
    label="Census state and local direct general expenditure, post-2022 code system",
    supported_years=frozenset({2022, 2024}),
    direct_general_codes=POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES,
    source_urls=(
        STATE_LOCAL_SUMMARY_METHODOLOGY_URL,
        STATE_LOCAL_2022_CONTENT_CHANGES_URL,
        STATE_LOCAL_CURRENT_AGGREGATE_DATA_URL,
        STATE_LOCAL_2022_INDIVIDUAL_UNIT_URL,
    ),
    notes=(
        "Parent membership adapts the Census State and Local Government Finances Direct General Expenditure summary formula to the post-2022 native code system.",
        "F is the consolidated capital-expenditure family effective 2022; G/K capital rows are not additive beside F.",
        "E74/E75 and J67/J68/J85 are discontinued from the post-2022 formula after welfare recoding into E79.",
        "Environmental-health code 27 is not a standalone member after Census recoded it into major functions.",
        "Fire-protection codes E24/F24 remain members of combined state-and-local Direct General Expenditure.",
        "State-only function 54 is not part of the combined state-and-local Direct General Expenditure function set.",
        "Utility codes 91-94, liquor-store code 90, and their related interest/capital codes are outside this direct-general parent.",
        "Published aggregate controls may contain Census aggregate-stage adjustments that are not present as additive dollars on any individual government row; TaxTrace does not redistribute those adjustments across governments.",
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
    CensusReceiptCategory("fire_protection", "Fire protection", frozenset({"24"})),
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
        frozenset({"55", "56", "59"}),
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
