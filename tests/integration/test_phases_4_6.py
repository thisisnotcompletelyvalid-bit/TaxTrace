from decimal import Decimal
from pathlib import Path

from taxtrace.allocation.engine import FederalAllocationEngine
from taxtrace.allocation.models import FederalReceiptRequest
from taxtrace.enums import FilingStatus
from taxtrace.explorer import ExplorerView, FederalExplorer, FederalExplorerRequest
from taxtrace.finance.fixtures import ingest_all_fixtures
from taxtrace.finance.seed import seed_federal_methodology_entities
from taxtrace.search import FederalSearchRequest, rebuild_search_index, search, search_with_receipt


def load_fixture_stack(db_session, tmp_path, monkeypatch):
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
    ingest_all_fixtures(db_session, Path("data/fixtures"))
    rebuild_search_index(db_session)


def request(**extra):
    return FederalReceiptRequest(
        tax_year=2026,
        filing_status=FilingStatus.SINGLE,
        wage_income=Decimal("50000"),
        spending_fiscal_year=2025,
        **extra,
    )


def test_complete_receipt_conserves_every_supported_tax_dollar(db_session, tmp_path, monkeypatch):
    load_fixture_stack(db_session, tmp_path, monkeypatch)
    result = FederalAllocationEngine().calculate(db_session, request())

    assert result.total_allocable_taxes == Decimal("7645.00")
    assert result.conservation_difference == Decimal("0.00")
    assert sum(node.allocated_amount for node in result.purpose) == Decimal("7645.00")
    assert sum(pool.contribution for pool in result.pools) == Decimal("7645.00")
    for pool in result.pools:
        assert sum(node.allocated_amount for node in pool.nodes) == pool.contribution

    pools = {pool.code: pool for pool in result.pools}
    assert pools["FED_GENERAL"].contribution == Decimal("3820.00")
    assert pools["OASI"].contribution == Decimal("2650.00")
    assert pools["DI"].contribution == Decimal("450.00")
    assert pools["MEDICARE_HI"].contribution == Decimal("725.00")
    assert pools["OASI"].nodes[0].label == "Social Security"
    assert pools["DI"].nodes[0].label == "Social Security"
    assert pools["MEDICARE_HI"].nodes[0].label == "Medicare"
    assert all(node.label != "Social Security" for node in pools["FED_GENERAL"].nodes)
    assert any(node.label == "Medicare" for node in pools["FED_GENERAL"].nodes)
    medicare = next(node for node in result.purpose if node.label == "Medicare")
    assert medicare.allocation_status == "MIXED_FUNDING"
    assert medicare.confidence.value == "D"
    social_security = next(node for node in result.purpose if node.label == "Social Security")
    assert social_security.government_spending_amount == Decimal("1580686000000.00")


def test_explorer_views_conserve_scope_and_account_program_drilldown(db_session, tmp_path, monkeypatch):
    load_fixture_stack(db_session, tmp_path, monkeypatch)
    explorer = FederalExplorer()

    root = explorer.explore(
        db_session,
        FederalExplorerRequest(**request().model_dump(), view=ExplorerView.PURPOSE),
    )
    assert root.scope_amount == Decimal("7645.00")
    assert root.conservation_difference == Decimal("0.00")
    assert sum(node.allocated_amount for node in root.nodes) == root.scope_amount

    account_programs = explorer.explore(
        db_session,
        FederalExplorerRequest(
            **request().model_dump(),
            view=ExplorerView.PROGRAM_ACTIVITY,
            parent_type="federal_account",
            parent_key="federal_account:012-3505",
        ),
    )
    assert account_programs.scope_amount == Decimal("0.07")
    assert account_programs.conservation_difference == Decimal("0.00")
    assert any(node.label == "Nutrition Assistance" for node in account_programs.nodes)

    account_awards = explorer.explore(
        db_session,
        FederalExplorerRequest(
            **request().model_dump(),
            view=ExplorerView.AWARD,
            parent_type="federal_account",
            parent_key="federal_account:012-3505",
        ),
    )
    assert account_awards.scope_amount == Decimal("0.07")
    assert account_awards.conservation_difference == Decimal("0.00")
    assert any("Florida" in " ".join(node.notes) for node in account_awards.nodes)


def test_search_indexes_aliases_awards_and_recipients(db_session, tmp_path, monkeypatch):
    load_fixture_stack(db_session, tmp_path, monkeypatch)

    food = search(db_session, "food stamps")
    assert food.results
    assert food.results[0].title == "Supplemental Nutrition Assistance Program"
    assert "food stamps" in [a.lower() for a in food.results[0].matched_aliases]

    florida = search(db_session, "Florida")
    assert any(r.entity_type == "recipient" and "Florida" in r.title for r in florida.results)

    dod = search(db_session, "DOD")
    assert any(r.entity_type == "agency" and "Defense" in r.title for r in dod.results)
    assert all(r.additive is False for r in dod.results)


def test_search_with_receipt_returns_nonadditive_user_amounts(db_session, tmp_path, monkeypatch):
    load_fixture_stack(db_session, tmp_path, monkeypatch)
    result = search_with_receipt(
        db_session,
        FederalSearchRequest(
            **request().model_dump(),
            q="food stamps",
            limit=20,
        ),
    )
    assert result.receipt_context is True
    snap = next(r for r in result.results if r.title == "Supplemental Nutrition Assistance Program")
    assert snap.attributable_amount == Decimal("0.07")
    assert snap.additive is False
    assert snap.suggested_view == "program_activity"
    assert snap.parent_type == "federal_account"
    assert snap.parent_key == "federal_account:012-3505"

    florida = search_with_receipt(
        db_session,
        FederalSearchRequest(
            **request().model_dump(),
            q="Florida",
            limit=20,
        ),
    )
    recipient = next(r for r in florida.results if r.entity_type == "recipient")
    assert recipient.attributable_amount is not None
    assert recipient.attributable_amount > Decimal("0")
    assert recipient.additive is False
