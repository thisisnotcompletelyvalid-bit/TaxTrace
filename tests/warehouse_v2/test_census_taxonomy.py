from decimal import Decimal

from taxtrace.warehouse_v2.census_taxonomy import (
    CENSUS_SUMMARY_METHODOLOGY_URL,
    CensusCodeAmount,
    build_expenditure_partition,
    category_for_item_code,
    taxonomy_audit,
)


def test_official_direct_general_expenditure_codes_have_one_taxtrace_bucket() -> None:
    audit = taxonomy_audit()

    assert audit["valid"] is True
    assert audit["missing_codes"] == ()
    assert audit["duplicate_assignments"] == {}
    assert audit["assigned_code_count"] == audit["official_parent_code_count"]


def test_special_interest_and_assistance_codes_keep_their_semantics() -> None:
    assert category_for_item_code("I89").key == "interest_general_debt"
    assert category_for_item_code("J19").key == "education_libraries"
    assert category_for_item_code("J67").key == "public_welfare_human_services"
    assert category_for_item_code("J68").key == "public_welfare_human_services"
    assert category_for_item_code("J85").key == "public_welfare_human_services"


def test_partition_conserves_direct_general_parent_and_excludes_other_grains() -> None:
    partition = build_expenditure_partition(
        [
            CensusCodeAmount("E62", Decimal("100.00")),
            CensusCodeAmount("F62", Decimal("25.00")),
            CensusCodeAmount("E24", Decimal("50.00")),
            CensusCodeAmount("E44", Decimal("70.00")),
            CensusCodeAmount("J67", Decimal("20.00")),
            CensusCodeAmount("I89", Decimal("5.00")),
            CensusCodeAmount("E03", Decimal("3.00")),
            # These are real Census expenditure-shaped rows but are not part of
            # direct general expenditure and therefore cannot enter this parent.
            CensusCodeAmount("L44", Decimal("999.00")),
            CensusCodeAmount("E91", Decimal("500.00")),
        ]
    )

    assert partition.parent_amount == Decimal("273.00")
    assert partition.conservation_difference == Decimal("0.00")
    assert partition.residual_amount == Decimal("0.00")
    assert partition.residual_codes == ()
    assert partition.excluded_codes == ("E91", "L44")
    assert partition.source_url == CENSUS_SUMMARY_METHODOLOGY_URL

    by_key = {node.key: node for node in partition.nodes}
    assert by_key["police"].amount == Decimal("125.00")
    assert by_key["police"].item_codes == ("E62", "F62")
    assert by_key["fire"].amount == Decimal("50.00")
    assert by_key["transportation"].amount == Decimal("70.00")
    assert by_key["public_welfare_human_services"].amount == Decimal("20.00")
    assert by_key["interest_general_debt"].amount == Decimal("5.00")
    assert by_key["other_unallocable"].amount == Decimal("3.00")
    assert sum((node.amount for node in partition.nodes), Decimal("0")) == partition.parent_amount


def test_duplicate_native_rows_are_combined_at_item_code_before_grouping() -> None:
    partition = build_expenditure_partition(
        [
            CensusCodeAmount("E32", Decimal("10.00")),
            CensusCodeAmount("E32", Decimal("2.50")),
            CensusCodeAmount("F32", Decimal("7.50")),
        ]
    )

    assert partition.parent_amount == Decimal("20.00")
    assert partition.nodes[0].key == "health"
    assert partition.nodes[0].amount == Decimal("20.00")
    assert partition.nodes[0].item_codes == ("E32", "F32")
    assert partition.conservation_difference == Decimal("0.00")
