from decimal import Decimal

import pandas as pd
import pytest

from taxtrace.finance.sources.treasury import (
    parse_mts_table_9,
    parse_treasury_summary_xlsx,
)


def test_treasury_parser_detects_millions_and_year(tmp_path):
    path = tmp_path / "outlay.xlsx"
    frame = pd.DataFrame(
        [
            ["Combined Statement", None],
            ["Amounts in millions of dollars", None],
            ["Function", "2025"],
            ["National Defense", 916649],
            ["Total Outlays", 7009992],
        ]
    )
    frame.to_excel(path, index=False, header=False)
    rows = parse_treasury_summary_xlsx(path, 2025, "outlays")
    assert rows[0]["category_name"] == "National Defense"
    assert rows[0]["amount"] == Decimal("916649000000")
    assert rows[1]["amount"] == Decimal("7009992000000")


def test_treasury_parser_refuses_unknown_units(tmp_path):
    path = tmp_path / "bad.xlsx"
    pd.DataFrame([["Function", "2025"], ["Total Outlays", 1]]).to_excel(
        path, index=False, header=False
    )
    with pytest.raises(ValueError, match="monetary units"):
        parse_treasury_summary_xlsx(path, 2025, "outlays")


def _mts_payload(*, outlay_total: str = "60.00") -> dict:
    return {
        "data": [
            {
                "record_date": "2025-09-30",
                "record_fiscal_year": "2025",
                "record_calendar_month": "09",
                "record_type_cd": "SL",
                "data_type_cd": "S",
                "line_code_nbr": "10",
                "sequence_level_nbr": "1",
                "sequence_number_cd": "1",
                "classification_desc": "Receipts",
                "current_fytd_rcpt_outly_amt": "null",
            },
            {
                "record_date": "2025-09-30",
                "record_fiscal_year": "2025",
                "record_calendar_month": "09",
                "record_type_cd": "RSG",
                "data_type_cd": "D",
                "line_code_nbr": "20",
                "sequence_level_nbr": "2",
                "sequence_number_cd": "1.1",
                "classification_id": "R1",
                "classification_desc": "Individual Income Taxes",
                "current_fytd_rcpt_outly_amt": "100.25",
            },
            {
                "record_date": "2025-09-30",
                "record_fiscal_year": "2025",
                "record_calendar_month": "09",
                "record_type_cd": "RSG",
                "data_type_cd": "S",
                "line_code_nbr": "40",
                "sequence_level_nbr": "2",
                "sequence_number_cd": "1.2",
                "classification_desc": "Social Insurance and Retirement Receipts:",
                "current_fytd_rcpt_outly_amt": "null",
            },
            {
                "record_date": "2025-09-30",
                "record_fiscal_year": "2025",
                "record_calendar_month": "09",
                "record_type_cd": "RSG",
                "data_type_cd": "D",
                "line_code_nbr": "50",
                "sequence_level_nbr": "3",
                "sequence_number_cd": "1.2.1",
                "classification_id": "R2",
                "classification_desc": "Employment and General Retirement",
                "current_fytd_rcpt_outly_amt": "49.75",
            },
            {
                "record_date": "2025-09-30",
                "record_fiscal_year": "2025",
                "record_calendar_month": "09",
                "record_type_cd": "SL",
                "data_type_cd": "T",
                "line_code_nbr": "120",
                "sequence_level_nbr": "2",
                "sequence_number_cd": "1.8",
                "classification_desc": "Total",
                "current_fytd_rcpt_outly_amt": "150.00",
            },
            {
                "record_date": "2025-09-30",
                "record_fiscal_year": "2025",
                "record_calendar_month": "09",
                "record_type_cd": "F",
                "data_type_cd": "D",
                "line_code_nbr": "140",
                "sequence_level_nbr": "2",
                "sequence_number_cd": "2.1",
                "classification_id": "F1",
                "classification_desc": "National Defense",
                "current_fytd_rcpt_outly_amt": "50.00",
            },
            {
                "record_date": "2025-09-30",
                "record_fiscal_year": "2025",
                "record_calendar_month": "09",
                "record_type_cd": "F",
                "data_type_cd": "D",
                "line_code_nbr": "330",
                "sequence_level_nbr": "2",
                "sequence_number_cd": "2.2",
                "classification_id": "F2",
                "classification_desc": "Undistributed Offsetting Receipts",
                "current_fytd_rcpt_outly_amt": "10.00",
            },
            {
                "record_date": "2025-09-30",
                "record_fiscal_year": "2025",
                "record_calendar_month": "09",
                "record_type_cd": "SL",
                "data_type_cd": "T",
                "line_code_nbr": "340",
                "sequence_level_nbr": "2",
                "sequence_number_cd": "2.20",
                "classification_desc": "Total",
                "current_fytd_rcpt_outly_amt": outlay_total,
            },
        ]
    }


def test_mts_table_9_parses_exact_dollar_details_and_non_additive_controls():
    rows = parse_mts_table_9(_mts_payload(), 2025)

    receipts = [row for row in rows if row["aggregate_type"] == "receipts"]
    outlays = [row for row in rows if row["aggregate_type"] == "outlays"]
    assert [row["category_name"] for row in receipts] == [
        "Individual Income Taxes",
        "Employment and General Retirement",
        "Total",
    ]
    assert [row["amount"] for row in receipts] == [
        Decimal("100.25"),
        Decimal("49.75"),
        Decimal("150.00"),
    ]
    assert outlays[0]["category_name"] == "National Defense"
    assert outlays[0]["amount"] == Decimal("50.00")
    assert outlays[-1]["category_name"] == "Total"
    assert outlays[-1]["amount"] == Decimal("60.00")
    assert receipts[-1]["metadata"]["control_total"] is True
    assert receipts[-1]["metadata"]["additive_detail"] is False
    assert outlays[-1]["metadata"]["control_total"] is True
    assert all(
        row["metadata"]["amount_unit"] == "dollars"
        for row in rows
    )


def test_mts_table_9_rejects_nonconserving_control_total():
    with pytest.raises(ValueError, match="outlay-function detail does not reconcile"):
        parse_mts_table_9(_mts_payload(outlay_total="61.00"), 2025)


def test_mts_table_9_refuses_missing_final_fiscal_year_rows():
    payload = _mts_payload()
    for row in payload["data"]:
        row["record_calendar_month"] = "08"
    with pytest.raises(ValueError, match="no September FY2025 rows"):
        parse_mts_table_9(payload, 2025)
