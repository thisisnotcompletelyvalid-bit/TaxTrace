from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import duckdb

from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.census import ingest_finance_zip
from taxtrace.warehouse_v2.census_lake import materialize_finance_parquet
from taxtrace.warehouse_v2.lake import LakeStore


def finance_line(gid: str, item: str, amount_thousands: int) -> str:
    return f"{gid:<14}{item:<3}{amount_thousands:>12}22R R "


def test_materialize_census_finance_parquet(db_session, tmp_path):
    seed_catalog(db_session)
    finance_zip = tmp_path / "2022_Individual_Unit_File.zip"
    with ZipFile(finance_zip, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "22fin.dat",
            "\n".join(
                [
                    finance_line("01100100100000", "E62", 1234),
                    finance_line("01100100100000", "F62", 200),
                    finance_line("01500100100000", "E12", 999),
                ]
            ),
        )

    ingest_finance_zip(
        db_session,
        finance_zip,
        year=2022,
        coverage_type="CENSUS",
        dataset_key="census-gov-finance-2022",
    )
    lake = LakeStore(root=tmp_path / "lake")
    result = materialize_finance_parquet(
        db_session,
        finance_zip,
        dataset_key="census-gov-finance-2022",
        year=2022,
        lake=lake,
    )

    parquet = Path(str(result["path"]))
    assert parquet.exists()
    assert result["rows"] == 3
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            "SELECT government_id, item_code, amount_dollars FROM read_parquet(?) ORDER BY item_code",
            [str(parquet)],
        ).fetchall()
    finally:
        connection.close()
    assert rows == [
        ("01500100100000", "E12", "999000"),
        ("01100100100000", "E62", "1234000"),
        ("01100100100000", "F62", "200000"),
    ]
