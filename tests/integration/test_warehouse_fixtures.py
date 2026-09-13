from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from taxtrace.db_models import Agency, SourceSnapshot, SpendFact, TreasuryAggregate
from taxtrace.finance.fixtures import ingest_all_fixtures
from taxtrace.finance.reconcile import reconcile_omb_outlays_to_treasury
from taxtrace.finance.seed import seed_federal_methodology_entities
from taxtrace.methodology.invariants import validate_revenue_pool_shares


def test_offline_fixture_pipeline_loads_and_reconciles(db_session, tmp_path, monkeypatch):
    # Keep archived fixture snapshots out of the repository during tests.
    from taxtrace.finance import fixtures as fixtures_module
    from taxtrace.finance.snapshot import SnapshotStore
    from taxtrace.finance.sources import omb as omb_module
    from taxtrace.finance.sources import usaspending as usaspending_module

    class TempSnapshotStore(SnapshotStore):
        def __init__(self, root=None):
            super().__init__(root=tmp_path / "raw")

    monkeypatch.setattr(fixtures_module, "SnapshotStore", TempSnapshotStore)
    monkeypatch.setattr(omb_module, "SnapshotStore", TempSnapshotStore)
    monkeypatch.setattr(usaspending_module, "SnapshotStore", TempSnapshotStore)

    seed_federal_methodology_entities(db_session)
    counts = ingest_all_fixtures(db_session, Path("data/fixtures"))
    assert counts["treasury"] > 20
    assert counts["omb"] == 8
    assert counts["usaspending"] > 0
    assert validate_revenue_pool_shares(db_session, 2026) == []

    total_outlays = db_session.scalar(
        select(TreasuryAggregate.amount).where(
            TreasuryAggregate.fiscal_year == 2025,
            TreasuryAggregate.aggregate_type == "outlays",
            TreasuryAggregate.category_name == "Total Outlays",
        )
    )
    assert Decimal(total_outlays) == Decimal("7009992000000")

    scopes = set(db_session.scalars(select(SpendFact.record_scope)).all())
    assert "omb_account_outlay" in scopes
    assert "usaspending_federal_account" in scopes
    assert "usaspending_object_class" in scopes
    assert "usaspending_program_activity" in scopes
    assert "usaspending_budget_function" in scopes

    assert db_session.scalar(select(func.count(Agency.id))) > 0
    assert db_session.scalar(select(func.count(SourceSnapshot.id))) >= 3

    result = reconcile_omb_outlays_to_treasury(db_session, 2025)
    assert result.status == "PASS"
    assert Decimal(result.absolute_difference) == 0
