import pytest

from taxtrace.warehouse_v2.usaspending_award_crosswalk import (
    CANONICAL_AWARD_KEY,
    award_crosswalks,
    canonical_column_for_data_class,
    validate_award_member_crosswalk_keys,
    validate_file_c_crosswalk_columns,
)
from taxtrace.warehouse_v2.usaspending_award_lake import USAspendingAwardArchiveMember


def _member(data_class: str, family: str, columns: tuple[str, ...]) -> USAspendingAwardArchiveMember:
    return USAspendingAwardArchiveMember(
        member_name=f"{data_class}-{family}.csv",
        data_class=data_class,
        dataset_key=(
            "usaspending-file-f" if data_class == "F" else "usaspending-file-d1-d2"
        ),
        award_family=family,
        columns=columns,
    )


def test_award_crosswalks_use_one_canonical_non_additive_key() -> None:
    specs = award_crosswalks()
    assert {spec.name for spec in specs} == {
        "file_c_to_d1_contract",
        "file_c_to_d2_assistance",
        "d1_contract_to_file_f",
        "d2_assistance_to_file_f",
    }
    assert all(spec.canonical_key == CANONICAL_AWARD_KEY for spec in specs)
    assert all(spec.additive is False for spec in specs)
    assert all(spec.requires_identity_collapse is True for spec in specs)
    assert {spec.cardinality for spec in specs} == {
        "many_file_c_rows_to_many_prime_transactions_via_award_identity",
        "many_prime_transactions_to_many_subawards_via_award_identity",
    }

    contract = award_crosswalks(award_family="contract")
    assistance = award_crosswalks(award_family="assistance")
    assert {spec.name for spec in contract} == {
        "file_c_to_d1_contract",
        "d1_contract_to_file_f",
    }
    assert {spec.name for spec in assistance} == {
        "file_c_to_d2_assistance",
        "d2_assistance_to_file_f",
    }


def test_canonical_crosswalk_columns_match_usaspending_download_aliases() -> None:
    assert canonical_column_for_data_class("C") == "award_unique_key"
    assert canonical_column_for_data_class("d1") == "contract_award_unique_key"
    assert canonical_column_for_data_class("D2") == "assistance_award_unique_key"
    assert canonical_column_for_data_class("f") == "prime_award_unique_key"

    with pytest.raises(ValueError, match="Unsupported"):
        canonical_column_for_data_class("B")


def test_validate_realistic_award_member_crosswalk_schemas() -> None:
    members = [
        _member(
            "D1",
            "contract",
            ("contract_award_unique_key", "award_id_piid", "recipient_name"),
        ),
        _member(
            "D2",
            "assistance",
            ("assistance_award_unique_key", "award_id_fain", "recipient_name"),
        ),
        _member(
            "F",
            "contract",
            ("prime_award_unique_key", "prime_award_piid", "subaward_number"),
        ),
        _member(
            "F",
            "assistance",
            ("prime_award_unique_key", "prime_award_fain", "subaward_number"),
        ),
    ]

    assert validate_award_member_crosswalk_keys(members) == {
        "D1:contract": "contract_award_unique_key",
        "D2:assistance": "assistance_award_unique_key",
        "F:contract": "prime_award_unique_key",
        "F:assistance": "prime_award_unique_key",
    }


def test_validate_file_c_crosswalk_schema() -> None:
    assert (
        validate_file_c_crosswalk_columns(
            ["treasury_account_symbol", "award_unique_key", "gross_outlay_amount_by_award_cpe"]
        )
        == "award_unique_key"
    )

    with pytest.raises(ValueError, match="award_unique_key"):
        validate_file_c_crosswalk_columns(["treasury_account_symbol", "recipient_name"])


def test_award_member_without_canonical_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="prime_award_unique_key"):
        validate_award_member_crosswalk_keys(
            [_member("F", "contract", ("prime_award_piid", "subaward_number"))]
        )
