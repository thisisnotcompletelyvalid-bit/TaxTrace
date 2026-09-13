from decimal import Decimal
from pathlib import Path

from taxtrace.enums import DataStatus
from taxtrace.finance.sources.omb import parse_omb_outlays, parse_omb_receipts


FIXTURE_ROOT = Path("data/fixtures/omb")


def test_omb_outlay_fixture_uses_thousands_and_actual_status():
    rows = parse_omb_outlays(FIXTURE_ROOT / "outlays_fixture.xlsx", 2025, 2025)
    assert len(rows) == 4
    assert rows[0]["status"] == DataStatus.ACTUAL
    assert rows[0]["amount"] == Decimal("916649000000")
    assert sum(r["amount"] for r in rows) == Decimal("7009992000000")


def test_omb_future_year_is_proposed():
    rows = parse_omb_outlays(FIXTURE_ROOT / "outlays_fixture.xlsx", 2026, 2025)
    assert all(row["status"] == DataStatus.PROPOSED for row in rows)


def test_omb_receipts_fixture():
    rows = parse_omb_receipts(FIXTURE_ROOT / "receipts_fixture.xlsx", 2025, 2025)
    assert sum(r["amount"] for r in rows) == Decimal("5234617000000")
