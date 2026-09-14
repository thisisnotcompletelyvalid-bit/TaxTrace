from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import duckdb

from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.lake import LakeStore
from taxtrace.warehouse_v2.usaspending_lake import (
    classify_account_columns,
    inspect_account_archive,
    materialize_account_archive,
)


def _csv(header: list[str], row: list[str]) -> str:
    return ",".join(header) + "\n" + ",".join(row) + "\n"


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
