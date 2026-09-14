from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

FILE_C_DATASET = "usaspending-file-c"
PRIME_DATASET = "usaspending-file-d1-d2"
SUBAWARD_DATASET = "usaspending-file-f"
CANONICAL_AWARD_KEY = "generated_unique_award_id"


class AwardMemberLike(Protocol):
    data_class: str
    award_family: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class AwardCrosswalk:
    """A non-additive identity relationship between USAspending grains.

    The participating download columns are aliases of USAspending's canonical
    generated_unique_award_id / Broker unique_award_key.  D1/D2 are transaction
    grains and File C can also contain repeated award identities, so these keys
    must not be used as an unconstrained row-to-row join: doing so can create a
    many-to-many fan-out.  Collapse or otherwise constrain each side to the
    intended award-identity grain before enrichment.

    These relationships are for enrichment and drill-down only; they never
    create another pool of federal spending to add to File C, D1/D2, or File F.
    """

    name: str
    source_dataset: str
    source_data_class: str
    source_key: str
    target_dataset: str
    target_data_class: str
    target_key: str
    award_family: str
    cardinality: str
    requires_identity_collapse: bool = True
    additive: bool = False
    canonical_key: str = CANONICAL_AWARD_KEY


AWARD_CROSSWALKS: tuple[AwardCrosswalk, ...] = (
    AwardCrosswalk(
        name="file_c_to_d1_contract",
        source_dataset=FILE_C_DATASET,
        source_data_class="C",
        source_key="award_unique_key",
        target_dataset=PRIME_DATASET,
        target_data_class="D1",
        target_key="contract_award_unique_key",
        award_family="contract",
        cardinality="many_file_c_rows_to_many_prime_transactions_via_award_identity",
    ),
    AwardCrosswalk(
        name="file_c_to_d2_assistance",
        source_dataset=FILE_C_DATASET,
        source_data_class="C",
        source_key="award_unique_key",
        target_dataset=PRIME_DATASET,
        target_data_class="D2",
        target_key="assistance_award_unique_key",
        award_family="assistance",
        cardinality="many_file_c_rows_to_many_prime_transactions_via_award_identity",
    ),
    AwardCrosswalk(
        name="d1_contract_to_file_f",
        source_dataset=PRIME_DATASET,
        source_data_class="D1",
        source_key="contract_award_unique_key",
        target_dataset=SUBAWARD_DATASET,
        target_data_class="F",
        target_key="prime_award_unique_key",
        award_family="contract",
        cardinality="many_prime_transactions_to_many_subawards_via_award_identity",
    ),
    AwardCrosswalk(
        name="d2_assistance_to_file_f",
        source_dataset=PRIME_DATASET,
        source_data_class="D2",
        source_key="assistance_award_unique_key",
        target_dataset=SUBAWARD_DATASET,
        target_data_class="F",
        target_key="prime_award_unique_key",
        award_family="assistance",
        cardinality="many_prime_transactions_to_many_subawards_via_award_identity",
    ),
)


def award_crosswalks(*, award_family: str | None = None) -> tuple[AwardCrosswalk, ...]:
    if award_family is None:
        return AWARD_CROSSWALKS
    normalized = award_family.strip().lower()
    return tuple(spec for spec in AWARD_CROSSWALKS if spec.award_family == normalized)


def canonical_column_for_data_class(data_class: str) -> str:
    normalized = data_class.strip().upper()
    mapping = {
        "C": "award_unique_key",
        "D1": "contract_award_unique_key",
        "D2": "assistance_award_unique_key",
        "F": "prime_award_unique_key",
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported USAspending award data class: {data_class!r}") from exc


def validate_award_member_crosswalk_keys(members: Iterable[AwardMemberLike]) -> dict[str, str]:
    """Require every D1/D2/File F member to expose the canonical join alias.

    This validates schema compatibility only.  It deliberately does not assert
    that every prime award has a File C financial row or every prime award has a
    subaward, because those are coverage facts rather than parser invariants.
    """
    validated: dict[str, str] = {}
    for member in members:
        data_class = member.data_class.strip().upper()
        expected = canonical_column_for_data_class(data_class)
        columns = {str(column).strip().lower() for column in member.columns}
        if expected not in columns:
            raise ValueError(
                f"USAspending {data_class} {member.award_family} member is missing "
                f"canonical crosswalk column {expected!r}"
            )
        validated[f"{data_class}:{member.award_family}"] = expected
    return validated


def validate_file_c_crosswalk_columns(columns: Iterable[str]) -> str:
    expected = canonical_column_for_data_class("C")
    normalized = {str(column).strip().lower() for column in columns}
    if expected not in normalized:
        raise ValueError(f"USAspending File C is missing canonical crosswalk column {expected!r}")
    return expected
