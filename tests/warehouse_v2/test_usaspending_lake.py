import csv
import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import duckdb
import pytest

from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.lake import LakeStore
from taxtrace.warehouse_v2.usaspending_lake import (
    classify_account_columns,
    inspect_account_archive,
    materialize_account_archive,
)


def _csv(header: list[str], row: list[str]) -> str:
    return ",".join(header) + "\n" + ",".join(row) + "\n"


def _csv_records(header: list[str], rows: list[list[str]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue()


def test_classify_usaspending_account_grains():
    assert classify_account_columns(
        ["treasury_account_symbol", "gross_outlay_amount", "appropriation_account_balances_id"]
    ) == "A"
    assert classify_account_columns(
        [
            "treasury_account_symbol",
            "program_activity_name",
            "object_class_name",
            "gross_outlay_amount_FYB_to_period_end",
        ]
    ) == "B"
    assert classify_account_columns(
        ["treasury_account_symbol", "program_activity_name", "object_class_name", "award_unique_key"]
    ) == "C"


def test_materialize_usaspending_account_archive(db_session, tmp_path):
    seed_catalog(db_session)
    archive_path = tmp_path / "FY2025_All_TAS_AccountData.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "AccountBalances_1.csv",
            _csv(
                [
                    "treasury_account_symbol",
                    "treasury_account_name",
                    "gross_outlay_amount",
                    "appropriation_account_balances_id",
                ],
                ["012-2025/2025-1234-000", "Test account", "125.50", "1"],
            ),
        )
        archive.writestr(
            "ObjectClassProgramActivity_1.csv",
            _csv(
                [
                    "treasury_account_symbol",
                    "program_activity_name",
                    "object_class_name",
                    "gross_outlay_amount_FYB_to_period_end",
                    "financial_accounts_by_program_activity_object_class_id",
                ],
                ["012-2025/2025-1234-000", "Nutrition Assistance", "Grants", "120.00", "2"],
            ),
        )
        archive.writestr(
            "AwardFinancial_1.csv",
            _csv(
                [
                    "treasury_account_symbol",
                    "program_activity_name",
                    "object_class_name",
                    "award_unique_key",
                    "recipient_name",
                    "financial_accounts_by_awards_id",
                ],
                ["012-2025/2025-1234-000", "Nutrition Assistance", "Grants", "AWARD-1", "Recipient", "3"],
            ),
        )

    inspected = inspect_account_archive(archive_path)
    assert [member.submission_type for member in inspected] == ["A", "B", "C"]

    lake = LakeStore(root=tmp_path / "lake")
    result = materialize_account_archive(
        db_session,
        archive_path,
        fiscal_year=2025,
        request={"account_level": "treasury_account"},
        lake=lake,
    )
    assert result["submission_files"]["A"]["rows"] == 1
    assert result["submission_files"]["B"]["rows"] == 1
    assert result["submission_files"]["C"]["rows"] == 1

    for submission_type in ("A", "B", "C"):
        object_key = result["submission_files"][submission_type]["parquet_objects"][0]
        parquet = Path(tmp_path / "lake" / object_key)
        assert parquet.exists()
        connection = duckdb.connect()
        try:
            assert connection.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(parquet)]
            ).fetchone()[0] == 1
        finally:
            connection.close()



def _verified_file_c_transport(total_rows: int) -> dict:
    return {
        "transport_strategy": "all_agency_product_column_projection",
        "components": [
            {
                "status": "finished",
                "total_rows": total_rows,
                "total_columns": 42,
                "transport_source": "pinned_verified_official_generated_archive",
                "verified_source_grain": "federal_account_award",
            }
        ],
    }


def test_verified_product_file_c_python_csv_canonicalization_preserves_multiline_records(
    db_session, tmp_path
) -> None:
    seed_catalog(db_session)
    archive_path = tmp_path / "FY2025_All_FA_Product_FileC.zip"
    header = [
        "federal_account_symbol",
        "gross_outlay_amount_FYB_to_period_end",
        "award_unique_key",
        "award_id_piid",
        "award_id_fain",
        "award_id_uri",
        "recipient_name",
        "recipient_name_raw",
        "recipient_uei",
        "prime_award_base_transaction_description",
        "awarding_agency_name",
        "funding_agency_name",
        "award_type",
        "usaspending_permalink",
    ]
    rows = [
        [
            "012-3456",
            "10.00",
            "AWARD-1",
            "PIID-1",
            "",
            "",
            "Recipient One",
            "Recipient One",
            "UEI-1",
            "First line\nSecond line, with a comma",
            "Agency",
            "Agency",
            "Contract",
            "https://example.test/award-1",
        ],
        [
            "097-0400",
            "20.00",
            "AWARD-2",
            "PIID-2",
            "FAIN-2",
            "URI-2",
            "Recipient Two",
            "Recipient Two",
            "UEI-2",
            "Description",
            "Awarding",
            "Funding",
            "Contract",
            "https://example.test/award-2",
        ],
    ]
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("AwardFinancial_1.csv", _csv_records(header, rows))

    lake = LakeStore(root=tmp_path / "lake")
    result = materialize_account_archive(
        db_session,
        archive_path,
        fiscal_year=2025,
        request={
            "account_level": "federal_account",
            "file_format": "csv",
            "filters": {
                "agency": "all",
                "fy": "2025",
                "period": "12",
                "submission_types": ["award_financial"],
            },
        },
        transport_metadata=_verified_file_c_transport(2),
        lake=lake,
    )

    assert result["submission_files"]["C"]["rows"] == 2
    object_key = result["submission_files"]["C"]["parquet_objects"][0]
    parquet = tmp_path / "lake" / object_key
    connection = duckdb.connect()
    try:
        observed = connection.execute(
            """
            SELECT award_unique_key, prime_award_base_transaction_description, usaspending_permalink
            FROM read_parquet(?)
            ORDER BY award_unique_key
            """,
            [str(parquet)],
        ).fetchall()
    finally:
        connection.close()
    assert observed == [
        (
            "AWARD-1",
            "First line\nSecond line, with a comma",
            "https://example.test/award-1",
        ),
        ("AWARD-2", "Description", "https://example.test/award-2"),
    ]

def test_verified_product_file_c_canonical_csv_fails_closed_on_row_count_mismatch(
    db_session, tmp_path
) -> None:
    seed_catalog(db_session)
    archive_path = tmp_path / "FY2025_All_FA_Product_FileC_bad_count.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "AwardFinancial_1.csv",
            "federal_account_symbol,gross_outlay_amount_FYB_to_period_end,award_unique_key\n"
            "012-3456,10.00,AWARD-1\n",
        )

    with pytest.raises(RuntimeError, match="parsed row count does not match"):
        materialize_account_archive(
            db_session,
            archive_path,
            fiscal_year=2025,
            request={
                "account_level": "federal_account",
                "file_format": "csv",
                "filters": {"agency": "all", "fy": "2025", "period": "12", "submission_types": ["award_financial"]},
            },
            transport_metadata=_verified_file_c_transport(2),
            lake=LakeStore(root=tmp_path / "lake"),
        )



def test_verified_product_file_c_canonical_csv_fails_closed_on_structural_fragment(
    db_session, tmp_path
) -> None:
    seed_catalog(db_session)
    archive_path = tmp_path / "FY2025_All_FA_Product_FileC_fragments.zip"
    header = [
        "federal_account_symbol",
        "gross_outlay_amount_FYB_to_period_end",
        "award_unique_key",
        "award_id_piid",
        "award_id_fain",
        "award_id_uri",
        "recipient_name",
        "recipient_name_raw",
        "recipient_uei",
        "prime_award_base_transaction_description",
        "awarding_agency_name",
        "funding_agency_name",
        "award_type",
        "usaspending_permalink",
    ]
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "AwardFinancial_1.csv",
            ",".join(header)
            + "\n"
            + "012-3456,10.00,AWARD-1,PIID-1,,,,,,,,,,\n"
            + "continued description fragment,with,only,four columns\n"
            + "097-0400,20.00,AWARD-2,PIID-2,,,,,,,,,,\n",
        )

    with pytest.raises(RuntimeError, match="columns; expected"):
        materialize_account_archive(
            db_session,
            archive_path,
            fiscal_year=2025,
            request={
                "account_level": "federal_account",
                "file_format": "csv",
                "filters": {
                    "agency": "all",
                    "fy": "2025",
                    "period": "12",
                    "submission_types": ["award_financial"],
                },
            },
            transport_metadata=_verified_file_c_transport(2),
            lake=LakeStore(root=tmp_path / "lake"),
        )
