from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

# U.S. Census Bureau, State and Local Government Finances:
# Methodology for Summary Tabulations. The methodology publishes the detailed
# item-code formulas used to construct direct general expenditure and its
# function-level subtotals.
CENSUS_SUMMARY_METHODOLOGY_URL = (
    "https://www2.census.gov/programs-surveys/gov-finances/technical-documentation/"
    "classification-manual/methodology_for_summary_tabulations.pdf"
)
TAXONOMY_VERSION = "1.0.0"
PARENT_KEY = "direct_general_expenditure"
PARENT_LABEL = "Direct general expenditure"

# Exact Census formula for direct general expenditure. Do not infer this set
# from prefixes: the source formula intentionally contains only selected
# expenditure codes and includes special I/J items.
DIRECT_GENERAL_EXPENDITURE_CODES = frozenset(
    {
        # Current operations.
        "E01", "E03", "E04", "E05", "E12", "E16", "E18", "E21", "E22",
        "E23", "E24", "E25", "E26", "E29", "E31", "E32", "E36", "E44",
        "E45", "E50", "E52", "E55", "E56", "E59", "E60", "E61", "E62",
        "E66", "E74", "E75", "E77", "E79", "E80", "E81", "E85", "E87",
        "E89",
        # Construction.
        "F01", "F03", "F04", "F05", "F12", "F16", "F18", "F21", "F22",
        "F23", "F24", "F25", "F26", "F29", "F31", "F32", "F36", "F44",
        "F45", "F50", "F52", "F55", "F56", "F59", "F60", "F61", "F62",
        "F66", "F77", "F79", "F80", "F81", "F85", "F87", "F89",
        # Other capital outlay.
        "G01", "G03", "G04", "G05", "G12", "G16", "G18", "G21", "G22",
        "G23", "G24", "G25", "G26", "G29", "G31", "G32", "G36", "G44",
        "G45", "G50", "G52", "G55", "G56", "G59", "G60", "G61", "G62",
        "G66", "G77", "G79", "G80", "G81", "G85", "G87", "G89",
        # Interest on general debt and assistance/subsidies included by Census.
        "I89", "J19", "J67", "J68", "J85",
    }
)


@dataclass(frozen=True)
class CensusReceiptCategory:
    key: str
    label: str
    function_codes: frozenset[str]
    special_item_codes: frozenset[str] = frozenset()


# These are TaxTrace presentation groups over the official Census direct-general
# expenditure formula. The grouping never changes which native item codes enter
# the additive parent; it only gives each included code exactly one public bucket.
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
        frozenset({"22", "74", "75", "77", "79", "85"}),
        frozenset({"J67", "J68", "J85"}),
    ),
    CensusReceiptCategory("health", "Health", frozenset({"32"})),
    CensusReceiptCategory("hospitals", "Hospitals", frozenset({"36"})),
    CensusReceiptCategory("police", "Police protection", frozenset({"62"})),
    CensusReceiptCategory("fire", "Fire protection", frozenset({"24"})),
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
    parent_key: str
    parent_label: str
    parent_amount: Decimal
    nodes: tuple[CensusPartitionNode, ...]
    residual_amount: Decimal
    residual_codes: tuple[str, ...]
    excluded_codes: tuple[str, ...]
    conservation_difference: Decimal
    source_url: str


def category_for_item_code(item_code: str) -> CensusReceiptCategory | None:
    code = item_code.strip().upper()
    if code not in DIRECT_GENERAL_EXPENDITURE_CODES:
        return None

    # Special I/J items have object semantics that override their numeric suffix.
    for category in CATEGORIES:
        if code in category.special_item_codes:
            return category

    # The regular function grouping applies only to Census E/F/G direct-general
    # expenditure rows. Applying it to I89 would incorrectly treat general-debt
    # interest as function 89 "other and unallocable."
    if code[:1] in {"E", "F", "G"} and len(code) == 3:
        for category in CATEGORIES:
            if code[1:] in category.function_codes:
                return category
    return None


def taxonomy_audit() -> dict[str, object]:
    assignments: dict[str, list[str]] = {}
    for code in sorted(DIRECT_GENERAL_EXPENDITURE_CODES):
        category = category_for_item_code(code)
        if category is not None:
            assignments.setdefault(code, []).append(category.key)
    missing = tuple(sorted(DIRECT_GENERAL_EXPENDITURE_CODES - assignments.keys()))
    duplicates = {
        code: tuple(keys)
        for code, keys in assignments.items()
        if len(keys) != 1
    }
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "official_parent_code_count": len(DIRECT_GENERAL_EXPENDITURE_CODES),
        "assigned_code_count": len(assignments),
        "missing_codes": missing,
        "duplicate_assignments": duplicates,
        "valid": not missing and not duplicates,
    }


def build_expenditure_partition(
    rows: Iterable[CensusCodeAmount],
) -> CensusExpenditurePartition:
    by_code: dict[str, Decimal] = {}
    excluded: set[str] = set()
    for row in rows:
        code = row.item_code.strip().upper()
        amount = Decimal(row.amount)
        if code in DIRECT_GENERAL_EXPENDITURE_CODES:
            by_code[code] = by_code.get(code, Decimal("0")) + amount
        else:
            excluded.add(code)

    category_codes: dict[str, list[str]] = {category.key: [] for category in CATEGORIES}
    category_amounts: dict[str, Decimal] = {
        category.key: Decimal("0") for category in CATEGORIES
    }
    residual_codes: list[str] = []
    residual_amount = Decimal("0")

    for code, amount in sorted(by_code.items()):
        category = category_for_item_code(code)
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
    parent_amount = sum(by_code.values(), Decimal("0"))
    child_total = sum((node.amount for node in nodes), Decimal("0")) + residual_amount
    return CensusExpenditurePartition(
        taxonomy_version=TAXONOMY_VERSION,
        parent_key=PARENT_KEY,
        parent_label=PARENT_LABEL,
        parent_amount=parent_amount,
        nodes=nodes,
        residual_amount=residual_amount,
        residual_codes=tuple(residual_codes),
        excluded_codes=tuple(sorted(excluded)),
        conservation_difference=parent_amount - child_total,
        source_url=CENSUS_SUMMARY_METHODOLOGY_URL,
    )
