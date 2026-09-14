from decimal import Decimal
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from taxtrace.allocation.models import FederalReceiptRequest
from taxtrace.enums import FilingStatus
from taxtrace.finance.fixtures import ingest_all_fixtures
from taxtrace.finance.seed import seed_federal_methodology_entities
from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.federal_receipt import FederalReceiptV2Engine
from taxtrace.warehouse_v2.lake import LakeStore
from taxtrace.warehouse_v2.usaspending_lake import materialize_account_archive


def _load_fixture_stack(db_session, tmp_path, monkeypatch):
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
    seed_catalog(db_session)


def _request():
    return FederalReceiptRequest(
        tax_year=2026,
        filing_status=FilingStatus.SINGLE,
        wage_income=Decimal("50000"),
        spending_fiscal_year=2025,
    )


def _write_file_b_archive(path: Path) -> None:
    header = [
        "federal_account_symbol",
        "federal_account_name",
        "program_activity_code",
        "program_activity_name",
        "object_class_code",
        "object_class_name",
        "gross_outlay_amount_FYB_to_period_end",
        "financial_accounts_by_program_activity_object_class_id",
    ]
    rows = [
        [
            "012-3505",
            "Food and Nutrition Service Programs",
            "PA1",
            "Nutrition Assistance",
            "41.0",
            "Grants, subsidies, and contributions",
            "60.00",
            "1",
        ],
        [
            "012-3505",
            "Food and Nutrition Service Programs",
            "PA1",
            "Nutrition Assistance",
            "25.2",
            "Other services",
            "40.00",
            "2",
        ],
    ]
    payload = ",".join(header) + "\n" + "\n".join(",".join(row) for row in rows) + "\n"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("ObjectClassProgramActivity_1.csv", payload)


def _materialize_file_b(db_session, tmp_path, *, period: str) -> LakeStore:
    archive = tmp_path / f"accounts-period-{period}.zip"
    _write_file_b_archive(archive)
    lake = LakeStore(root=tmp_path / "lake")
    materialize_account_archive(
        db_session,
        archive,
        fiscal_year=2025,
        request={
            "account_level": "treasury_account",
            "file_format": "csv",
            "filters": {"agency": "all", "fy": "2025", "period": period},
        },
        lake=lake,
    )
    return lake


def test_v2_receipt_uses_file_b_as_conserved_account_detail(db_session, tmp_path, monkeypatch):
    _load_fixture_stack(db_session, tmp_path, monkeypatch)
    lake = _materialize_file_b(db_session, tmp_path, period="12")

    result = FederalReceiptV2Engine(lake=lake).calculate(db_session, _request())

    assert result.base_receipt.total_allocable_taxes == Decimal("7645.00")
    assert result.additive_partition_total == Decimal("7645.00")
    assert result.conservation_difference == Decimal("0.00")
    assert result.warehouse.status == "READY"
    assert result.warehouse.full_fiscal_year is True

    account = next(node for node in result.accounts if node.account_code == "012-3505")
    assert account.allocated_amount == Decimal("0.07")
    assert account.warehouse_matched is True
    assert account.file_b_government_outlay == Decimal("100.00")
    assert account.conservation_difference == Decimal("0.00")
    assert sum(child.allocated_amount for child in account.children) == account.allocated_amount
    assert {child.allocated_amount for child in account.children} == {
        Decimal("0.04"),
        Decimal("0.03"),
    }
    assert all(child.method == "OMB_ACCOUNT_PARENT__FILE_B_OUTLAY_SHARE" for child in account.children)
    assert all(child.additive is True for child in account.children)


def test_v2_receipt_refuses_partial_file_b_as_full_year_partition(db_session, tmp_path, monkeypatch):
    _load_fixture_stack(db_session, tmp_path, monkeypatch)
    lake = _materialize_file_b(db_session, tmp_path, period="6")

    result = FederalReceiptV2Engine(lake=lake).calculate(db_session, _request())

    assert result.warehouse.status == "PARTIAL_OR_UNKNOWN_PERIOD"
    assert result.warehouse.full_fiscal_year is False
    assert result.conservation_difference == Decimal("0.00")
    account = next(node for node in result.accounts if node.account_code == "012-3505")
    assert account.warehouse_matched is False
    assert len(account.children) == 1
    assert account.children[0].residual is True
    assert account.children[0].allocated_amount == account.allocated_amount


def test_v2_receipt_degrades_to_explicit_residuals_without_file_b(db_session, tmp_path, monkeypatch):
    _load_fixture_stack(db_session, tmp_path, monkeypatch)
    lake = LakeStore(root=tmp_path / "empty-lake")

    result = FederalReceiptV2Engine(lake=lake).calculate(db_session, _request())

    assert result.warehouse.status == "NO_READY_RELEASE"
    assert result.additive_partition_total == Decimal("7645.00")
    assert result.conservation_difference == Decimal("0.00")
    assert result.accounts
    assert all(
        node.children and sum(child.allocated_amount for child in node.children) == node.allocated_amount
        for node in result.accounts
    )
    assert all(node.children[0].residual is True for node in result.accounts)
