from decimal import Decimal

import pytest

from taxtrace.warehouse_v2.census_taxonomy import (
    POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES,
    STATE_2022_SUMMARY_METHODOLOGY_URL,
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
        assert audit["assigned_code_count"] == audit["official_parent_code_count"]
        assert audit["formula_key"] == "census-direct-general-post-2022"


def test_post_2022_formula_reflects_capital_and_welfare_code_changes() -> None:
    assert "F62" in POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES
    assert "G62" not in POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES
    assert "K62" not in POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES
    assert "E79" in POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES
    assert "E74" not in POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES
    assert "E75" not in POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES
    assert "J67" not in POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES
    assert "J68" not in POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES
    assert "J85" not in POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES
    assert "J19" in POST_2022_DIRECT_GENERAL_EXPENDITURE_CODES


def test_post_2022_formula_excludes_environmental_health_exhibit_but_adds_natural_resource_detail() -> None:
    assert category_for_item_code("E27", fiscal_year=2022) is None
    assert category_for_item_code("F27", fiscal_year=2022) is None
    assert category_for_item_code("E54", fiscal_year=2022).key == "natural_resources_environment"
    assert category_for_item_code("F54", fiscal_year=2022).key == "natural_resources_environment"


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
            # These expenditure-shaped rows are not in the post-2022 direct-
            # general parent: transfer, utility, obsolete capital/welfare, and
            # environmental-health exhibit/recode rows.
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
    assert STATE_2022_SUMMARY_METHODOLOGY_URL in partition.source_urls
    assert partition.formula_key == "census-direct-general-post-2022"
    assert partition.fiscal_year == 2022

    by_key = {node.key: node for node in partition.nodes}
    assert by_key["police"].amount == Decimal("125.00")
    assert by_key["police"].item_codes == ("E62", "F62")
    assert by_key["fire"].amount == Decimal("50.00")
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
