from datetime import date
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import duckdb
import pytest

from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.lake import LakeStore
from taxtrace.warehouse_v2.usaspending_award_lake import (
    PRIME_DATASET,
    SUBAWARD_DATASET,
    award_release_identity,
    classify_award_columns,
    inspect_award_archive,
    materialize_award_archive,
)
from taxtrace.warehouse_v2.usaspending_awards import build_award_bulk_payload


def _csv(header: list[str], row: list[str]) -> str:
    return ",".join(header) + "\n" + ",".join(row) + "\n"


def test_classify_prime_and_subaward_grains() -> None:
    assert classify_award_columns(
        ["contract_award_unique_key", "award_id_piid", "recipient_name"]
    ) == ("D1", "contract")
    assert classify_award_columns(
        ["assistance_award_unique_key", "award_id_fain", "recipient_name"]
    ) == ("D2", "assistance")
    assert classify_award_columns(
        ["prime_award_unique_key", "prime_award_piid", "subaward_number", "subaward_amount"]
    ) == ("F", "contract")
    assert classify_award_columns(
        ["prime_award_unique_key", "prime_award_fain", "subaward_number", "subaward_amount"]
    ) == ("F", "assistance")


def test_file_f_requires_family_marker() -> None:
    with pytest.raises(ValueError, match="do not identify contract vs assistance"):
        classify_award_columns(["prime_award_unique_key", "subaward_number", "subaward_amount"])


def test_award_release_identity_distinguishes_full_year_slice_and_scope() -> None:
    full = award_release_identity(2022, build_award_bulk_payload(2022))
    assert full.release_key == "FY2022"
    assert full.reference_period == "FY2022"
    assert full.coverage_type == "FEDERAL_AWARD"
    assert full.scope_complete is True

    sliced = award_release_identity(
        2022,
        build_award_bulk_payload(
            2022,
            start_date=date(2022, 3, 1),
            end_date=date(2022, 3, 7),
        ),
    )
    assert sliced.release_key == "FY2022_2022-03-01_2022-03-07"
    assert sliced.reference_period == "2022-03-01/2022-03-07"
    assert sliced.coverage_type == "FEDERAL_AWARD_SLICE"
    assert sliced.scope_complete is True

    normalized_request = build_award_bulk_payload(2022)
    filters = normalized_request["filters"]
    filters.pop("date_range")
    filters["time_period"] = [{"start_date": "2022-04-01", "end_date": "2022-04-02"}]
    normalized = award_release_identity(2022, normalized_request)
    assert normalized.release_key == "FY2022_2022-04-01_2022-04-02"
    assert normalized.scope_complete is True

    agency_scoped = award_release_identity(
        2022,
        build_award_bulk_payload(2022, agency=12),
    )
    assert agency_scoped.release_key.startswith("FY2022_SCOPE_")
    assert agency_scoped.release_key != "FY2022"
    assert agency_scoped.coverage_type == "FEDERAL_AWARD_SCOPED"
    assert agency_scoped.scope_complete is False

    type_scoped_request = build_award_bulk_payload(2022)
    type_scoped_request["filters"]["prime_award_types"] = ["A"]
    type_scoped = award_release_identity(2022, type_scoped_request)
    assert type_scoped.release_key.startswith("FY2022_SCOPE_")
    assert type_scoped.coverage_type == "FEDERAL_AWARD_SCOPED"
    assert type_scoped.scope_complete is False


def test_materialize_usaspending_award_archive(db_session, tmp_path: Path) -> None:
    seed_catalog(db_session)
    archive_path = tmp_path / "FY2022_awards.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "contracts.csv",
            _csv(
                ["contract_award_unique_key", "award_id_piid", "recipient_name", "total_obligated_amount"],
                ["CONT_AWD_1", "PIID-1", "Contract Recipient", "100.00"],
            ),
        )
        archive.writestr(
            "assistance.csv",
            _csv(
                ["assistance_award_unique_key", "award_id_fain", "recipient_name", "total_obligated_amount"],
                ["ASST_NON_1", "FAIN-1", "Assistance Recipient", "200.00"],
            ),
        )
        archive.writestr(
            "contract_subawards.csv",
            _csv(
                ["prime_award_unique_key", "prime_award_piid", "subaward_number", "subaward_amount", "subawardee_name"],
                ["CONT_AWD_1", "PIID-1", "SUB-C-1", "25.00", "Contract Subrecipient"],
            ),
        )
        archive.writestr(
            "assistance_subawards.csv",
            _csv(
                ["prime_award_unique_key", "prime_award_fain", "subaward_number", "subaward_amount", "subawardee_name"],
                ["ASST_NON_1", "FAIN-1", "SUB-A-1", "50.00", "Assistance Subrecipient"],
            ),
        )
        archive.writestr("readme.txt", "not a data member")

    inspected = inspect_award_archive(archive_path)
    assert [(member.data_class, member.award_family) for member in inspected] == [
        ("D1", "contract"),
        ("D2", "assistance"),
        ("F", "contract"),
        ("F", "assistance"),
    ]

    lake = LakeStore(root=tmp_path / "lake")
    result = materialize_award_archive(
        db_session,
        archive_path,
        fiscal_year=2022,
        request=build_award_bulk_payload(2022),
        lake=lake,
    )

    assert result["release_key"] == "FY2022"
    assert result["coverage_type"] == "FEDERAL_AWARD"
    assert result["scope_complete"] is True
    assert result["datasets"][PRIME_DATASET]["release_key"] == "FY2022"
    assert result["datasets"][PRIME_DATASET]["scope_complete"] is True
    assert result["datasets"][PRIME_DATASET]["rows"] == 2
    assert result["datasets"][PRIME_DATASET]["members"] == 2
    assert result["datasets"][SUBAWARD_DATASET]["rows"] == 2
    assert result["datasets"][SUBAWARD_DATASET]["members"] == 2

    prime_parts = result["datasets"][PRIME_DATASET]["parts"]
    subaward_parts = result["datasets"][SUBAWARD_DATASET]["parts"]
    assert {(part["data_class"], part["award_family"]) for part in prime_parts} == {
        ("D1", "contract"),
        ("D2", "assistance"),
    }
    assert {(part["data_class"], part["award_family"]) for part in subaward_parts} == {
        ("F", "contract"),
        ("F", "assistance"),
    }

    for dataset_key in (PRIME_DATASET, SUBAWARD_DATASET):
        for object_key in result["datasets"][dataset_key]["parquet_objects"]:
            parquet = tmp_path / "lake" / object_key
            assert parquet.exists()
            connection = duckdb.connect()
            try:
                assert connection.execute(
                    "SELECT count(*) FROM read_parquet(?)", [str(parquet)]
                ).fetchone()[0] == 1
            finally:
                connection.close()


def test_materialize_scoped_full_year_cannot_claim_plain_fy_release(
    db_session, tmp_path: Path
) -> None:
    seed_catalog(db_session)
    archive_path = tmp_path / "scoped.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "contracts.csv",
            _csv(
                ["contract_award_unique_key", "award_id_piid", "recipient_name"],
                ["CONT_AWD_1", "PIID-1", "Contract Recipient"],
            ),
        )

    result = materialize_award_archive(
        db_session,
        archive_path,
        fiscal_year=2022,
        request=build_award_bulk_payload(
            2022,
            agency=12,
            include_subawards=False,
        ),
        lake=LakeStore(root=tmp_path / "scoped-lake"),
    )

    assert result["release_key"].startswith("FY2022_SCOPE_")
    assert result["release_key"] != "FY2022"
    assert result["coverage_type"] == "FEDERAL_AWARD_SCOPED"
    assert result["scope_complete"] is False
