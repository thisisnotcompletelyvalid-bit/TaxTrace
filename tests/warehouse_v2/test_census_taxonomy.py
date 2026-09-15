from decimal import Decimal

import pytest

from taxtrace.warehouse_v2.census_taxonomy import (
    POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES,
    STATE_LOCAL_SUMMARY_METHODOLOGY_URL,
    TAXONOMY_VERSION,
    CensusCodeAmount,
    build_expenditure_partition,
    category_for_item_code,
    formula_for_year,
    taxonomy_audit,
)


def test_post_2022_direct_general_codes_have_one_taxtrace_bucket() -> None:
    for fiscal_year in (2022, 2024):
        audit = taxonomy_audit(fiscal_year)

        assert audit["valid"] is True
        assert audit["missing_codes"] == ()
        assert audit["duplicate_assignments"] == {}
        assert audit["assigned_code_count"] == audit["official_parent_code_count"] == 72
        assert audit["formula_key"] == "census-state-local-direct-general-2022-2024"
        assert audit["taxonomy_version"] == TAXONOMY_VERSION == "1.2.0"


def test_post_2022_formula_matches_combined_state_local_membership() -> None:
    assert len(POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES) == 72
    for code in ("E24", "F24", "E62", "F62", "I89", "J19"):
        assert code in POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES

    # These expenditure-shaped native rows are outside the post-2022 combined
    # state/local Direct General Expenditure parent.
    for code in (
        "E27",
        "F27",
        "E54",
        "F54",
        "E90",
        "F90",
        "E91",
        "F91",
        "I91",
        "E92",
        "F92",
        "I92",
        "E93",
        "F93",
        "I93",
        "E94",
        "F94",
        "I94",
        "G24",
        "G62",
        "K62",
        "E74",
        "E75",
        "J67",
        "J68",
        "J85",
    ):
        assert code not in POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES


def test_post_2022_formula_applies_2022_function_recodes() -> None:
    assert category_for_item_code("E27", fiscal_year=2022) is None
    assert category_for_item_code("F27", fiscal_year=2022) is None
    assert category_for_item_code("E54", fiscal_year=2022) is None
    assert category_for_item_code("F54", fiscal_year=2022) is None
    assert category_for_item_code("E55", fiscal_year=2022).key == "natural_resources_environment"
    assert category_for_item_code("F55", fiscal_year=2022).key == "natural_resources_environment"


def test_fire_remains_in_combined_state_local_additive_parent() -> None:
    assert category_for_item_code("E24", fiscal_year=2022).key == "fire_protection"
    assert category_for_item_code("F24", fiscal_year=2022).key == "fire_protection"


def test_special_interest_and_education_subsidy_codes_keep_semantics() -> None:
    assert category_for_item_code("I89", fiscal_year=2022).key == "interest_general_debt"
    assert category_for_item_code("J19", fiscal_year=2022).key == "education_libraries"


def test_formula_fails_closed_for_unimplemented_year() -> None:
    with pytest.raises(ValueError, match="No unique Census additive expenditure formula"):
        formula_for_year(2021)


def test_partition_conserves_direct_general_parent_and_excludes_other_grains() -> None:
    partition = build_expenditure_partition(
        [
            CensusCodeAmount("E62", Decimal("100.00")),
            CensusCodeAmount("F62", Decimal("25.00")),
            CensusCodeAmount("E24", Decimal("50.00")),
            CensusCodeAmount("E44", Decimal("70.00")),
            CensusCodeAmount("E79", Decimal("20.00")),
            CensusCodeAmount("I89", Decimal("5.00")),
            CensusCodeAmount("E03", Decimal("3.00")),
            # Transfer, utility, obsolete capital/welfare, and recoded rows.
            CensusCodeAmount("L44", Decimal("999.00")),
            CensusCodeAmount("E91", Decimal("500.00")),
            CensusCodeAmount("G44", Decimal("400.00")),
            CensusCodeAmount("J67", Decimal("200.00")),
            CensusCodeAmount("E27", Decimal("100.00")),
        ],
        fiscal_year=2022,
    )

    assert partition.parent_amount == Decimal("273.00")
    assert partition.conservation_difference == Decimal("0.00")
    assert partition.residual_amount == Decimal("0.00")
    assert partition.residual_codes == ()
    assert partition.excluded_codes == ("E27", "E91", "G44", "J67", "L44")
    assert STATE_LOCAL_SUMMARY_METHODOLOGY_URL in partition.source_urls
    assert partition.formula_key == "census-state-local-direct-general-2022-2024"
    assert partition.fiscal_year == 2022

    by_key = {node.key: node for node in partition.nodes}
    assert by_key["police"].amount == Decimal("125.00")
    assert by_key["police"].item_codes == ("E62", "F62")
    assert by_key["fire_protection"].amount == Decimal("50.00")
    assert by_key["transportation"].amount == Decimal("70.00")
    assert by_key["public_welfare_human_services"].amount == Decimal("20.00")
    assert by_key["interest_general_debt"].amount == Decimal("5.00")
    assert by_key["other_unallocable"].amount == Decimal("3.00")
    assert sum((node.amount for node in partition.nodes), Decimal("0.00")) == partition.parent_amount


def test_duplicate_native_rows_are_combined_at_item_code_before_grouping() -> None:
    partition = build_expenditure_partition(
        [
            CensusCodeAmount("E32", Decimal("10.00")),
            CensusCodeAmount("E32", Decimal("2.50")),
            CensusCodeAmount("F32", Decimal("7.50")),
        ],
        fiscal_year=2022,
    )

    assert partition.parent_amount == Decimal("20.00")
    assert partition.nodes[0].key == "health"
    assert partition.nodes[0].amount == Decimal("20.00")
    assert partition.nodes[0].item_codes == ("E32", "F32")
    assert partition.conservation_difference == Decimal("0.00")
