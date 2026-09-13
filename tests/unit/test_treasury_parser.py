from decimal import Decimal

import pandas as pd
import pytest

from taxtrace.finance.sources.treasury import parse_treasury_summary_xlsx


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
