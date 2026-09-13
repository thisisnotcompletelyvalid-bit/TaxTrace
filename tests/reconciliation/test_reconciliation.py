from decimal import Decimal

from taxtrace.finance.reconcile import ReconciliationPolicy, compare_values


def test_reconciliation_policy_boundaries():
    policy = ReconciliationPolicy()
    assert compare_values(left=Decimal("1000.5"), right=Decimal("1000"), policy=policy)[2] == "PASS"
    assert compare_values(left=Decimal("1005"), right=Decimal("1000"), policy=policy)[2] == "REVIEW"
    assert compare_values(left=Decimal("1020"), right=Decimal("1000"), policy=policy)[2] == "FAIL"
