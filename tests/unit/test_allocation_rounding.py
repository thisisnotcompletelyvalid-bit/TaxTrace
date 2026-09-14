from decimal import Decimal

from taxtrace.allocation.engine import _reconcile_parts


def test_largest_remainder_conserves_and_does_not_dump_residual_into_last_row():
    raw = [
        Decimal("790.5525560889222826329903601"),
        Decimal("836.8740791446786471740719652"),
        Decimal("0.08451888399672544637918445915"),
        Decimal("2192.488845882402344746558490"),
    ]
    parts = _reconcile_parts(Decimal("3820.00"), raw)
    assert sum(parts) == Decimal("3820.00")
    assert parts[2] == Decimal("0.09")


def test_largest_remainder_handles_negative_parts_and_conserves():
    parts = _reconcile_parts(
        Decimal("10.00"),
        [Decimal("10.006"), Decimal("0.004"), Decimal("-0.010")],
    )
    assert sum(parts) == Decimal("10.00")
