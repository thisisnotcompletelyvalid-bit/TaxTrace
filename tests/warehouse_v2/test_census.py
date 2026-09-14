from decimal import Decimal
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
from sqlalchemy import select

from taxtrace.db_models import Jurisdiction
from taxtrace.warehouse_v2.census import (
    ingest_finance_zip,
    ingest_government_units_zip,
    iter_government_units,
    parse_finance_line,
    parse_government_unit_line,
)
from taxtrace.warehouse_v2.db_models import FinanceClassification, GovernmentFinanceFact


def finance_line(gid: str, item: str, amount_thousands: int) -> str:
    return f"{gid:<14}{item:<3}{amount_thousands:>12}22R R "


def government_line(gid: str, name: str) -> str:
    return f"{gid:<14}{name:<64}" + " " * (206 - 78)


def test_fixed_width_parsers():
    record = parse_finance_line(finance_line("10200123400000", "E62", 1234))
    assert record is not None
    assert record.item_code == "E62"
    assert record.amount_dollars == Decimal("1234000")
    unit = parse_government_unit_line(government_line("10200123400000", "Gainesville test city"))
    assert unit is not None
    assert unit.name == "Gainesville test city"


def test_official_2022_government_workbook_headers(tmp_path):
    """Regression test for the headers used by the published 2022 Government Units workbook."""
    workbook = BytesIO()
    frame = pd.DataFrame(
        [
            {
                "CENSUS_ID_PID6": "100001",
                "CENSUS_ID_GIDID": "01100100100000",
                "UNIT_NAME": "COUNTY OF AUTAUGA",
                "UNIT_TYPE": "1 - COUNTY",
                "STATE": "AL",
                "FIPS_STATE": "01",
                "FIPS_COUNTY": "001",
                "IS_ACTIVE": "Y",
            },
            {
                "CENSUS_ID_PID6": "177885",
                "CENSUS_ID_GIDID": "01500100100000",
                "UNIT_NAME": "AUTAUGA COUNTY SCHOOL DISTRICT",
                "STATE": "AL",
                "FIPS_STATE": "01",
                "FIPS_COUNTY": "001",
                "IS_ACTIVE": "Y",
            },
        ]
    )
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="General Purpose", index=False)

    units_zip = tmp_path / "govt_units_2022.ZIP"
    with ZipFile(units_zip, "w", ZIP_DEFLATED) as archive:
        archive.writestr("Government_Units_List_Documentation_2022.pdf", b"%PDF-test")
        archive.writestr("Govt_Units_2022_Final.xlsx", workbook.getvalue())

    units = list(iter_government_units(units_zip))
    assert [(unit.government_id, unit.name) for unit in units] == [
        ("01100100100000", "COUNTY OF AUTAUGA"),
        ("01500100100000", "AUTAUGA COUNTY SCHOOL DISTRICT"),
    ]


def test_census_registry_and_finance_ingest(db_session, tmp_path):
    units_zip = tmp_path / "govt_units_2022.ZIP"
    with ZipFile(units_zip, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "22cogid.dat",
            "\n".join(
                [
                    government_line("10000000000000", "Florida"),
                    government_line("10200123400000", "Gainesville test city"),
                ]
            ),
        )
    unit_result = ingest_government_units_zip(db_session, units_zip)
    assert unit_result["governments"] == 2

    finance_zip = tmp_path / "2022_Individual_Unit_File.zip"
    with ZipFile(finance_zip, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "22fin.dat",
            "\n".join(
                [
                    finance_line("10200123400000", "E62", 1234),
                    finance_line("10200123400000", "F62", 200),
                    finance_line("10200123400000", "E24", 500),
                    finance_line("10200123400000", "E44", 700),
                ]
            ),
        )
    result = ingest_finance_zip(
        db_session,
        finance_zip,
        year=2022,
        coverage_type="CENSUS",
        dataset_key="census-gov-finance-2022",
    )
    assert result["rows"] == 4
    city = db_session.scalar(select(Jurisdiction).where(Jurisdiction.name == "Gainesville test city"))
    assert city is not None
    police = db_session.scalar(
        select(GovernmentFinanceFact)
        .join(FinanceClassification, GovernmentFinanceFact.classification_id == FinanceClassification.id)
        .where(
            GovernmentFinanceFact.jurisdiction_id == city.id,
            FinanceClassification.code == "E62",
        )
    )
    assert police is not None
    assert police.amount == Decimal("1234000.00")
    classification = db_session.scalar(
        select(FinanceClassification).where(FinanceClassification.code == "E62")
    )
    assert classification.function_name == "Police protection"
    assert classification.object_type == "Current operations"
    assert classification.additive_partition is None
