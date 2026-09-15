import csv
import io
from decimal import Decimal
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from taxtrace.allocation.models import FederalReceiptRequest
from taxtrace.enums import FilingStatus
from taxtrace.finance.fixtures import ingest_all_fixtures
from taxtrace.finance.seed import seed_federal_methodology_entities
from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.federal_awards import FederalAwardProjectionEngine
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


def _csv_text(header: list[str], rows: list[list[str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue()


def _write_account_archive(path: Path, *, file_b_total: str = "100.00") -> None:
    file_b_header = [
        "federal_account_symbol",
        "federal_account_name",
        "program_activity_code",
        "program_activity_name",
        "object_class_code",
        "object_class_name",
        "gross_outlay_amount_FYB_to_period_end",
        "financial_accounts_by_program_activity_object_class_id",
    ]
    file_b_rows = [
        [
            "012-3505",
            "Food and Nutrition Service Programs",
            "PA1",
            "Nutrition Assistance",
            "41.0",
            "Grants and contributions",
            file_b_total,
            "1",
        ]
    ]

    file_c_header = [
        "federal_account_symbol",
        "federal_account_name",
        "award_unique_key",
        "award_id_piid",
        "award_id_fain",
        "award_id_uri",
        "recipient_name",
        "recipient_uei",
        "prime_award_base_transaction_description",
        "awarding_agency_name",
        "funding_agency_name",
        "award_type",
        "usaspending_permalink",
        "gross_outlay_amount_FYB_to_period_end",
        "financial_accounts_by_awards_id",
    ]
    file_c_rows = [
        [
            "012-3505",
            "Food and Nutrition Service Programs",
            "AWARD-A",
            "PIID-A",
            "",
            "",
            "Recipient A",
            "UEI-A",
            "Award A description",
            "Department A",
            "Department A",
            "Contract",
            "https://example.test/award-a",
            "10.00",
            "101",
        ],
        [
            "012-3505",
            "Food and Nutrition Service Programs",
            "AWARD-A",
            "PIID-A",
            "",
            "",
            "Recipient A",
            "UEI-A",
            "Award A description",
            "Department A",
            "Department A",
            "Contract",
            "https://example.test/award-a",
            "20.00",
            "102",
        ],
        [
            "012-3505",
            "Food and Nutrition Service Programs",
            "AWARD-B",
            "",
            "FAIN-B",
            "",
            "Recipient B",
            "UEI-B",
            "Award B description",
            "Department B",
            "Department B",
            "Assistance",
            "https://example.test/award-b",
            "20.00",
            "103",
        ],
        [
            "012-3505",
            "Food and Nutrition Service Programs",
            "",
            "",
            "",
            "",
            "Unlinked source row",
            "",
            "Unlinked activity",
            "Department C",
            "Department C",
            "",
            "",
            "10.00",
            "104",
        ],
    ]

    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("ObjectClassProgramActivity_1.csv", _csv_text(file_b_header, file_b_rows))
        archive.writestr("AwardFinancial_1.csv", _csv_text(file_c_header, file_c_rows))


def _materialize(db_session, tmp_path, *, period: str = "12", file_b_total: str = "100.00"):
    archive = tmp_path / f"accounts-{period}-{file_b_total}.zip"
    _write_account_archive(archive, file_b_total=file_b_total)
    lake = LakeStore(root=tmp_path / "lake")
    materialize_account_archive(
        db_session,
        archive,
        fiscal_year=2025,
        request={
            "account_level": "treasury_account",
            "file_format": "csv",
            "filters": {
                "agency": "all",
                "fy": "2025",
                "period": period,
                "submission_types": [
                    "object_class_program_activity",
                    "award_financial",
                ],
            },
        },
        lake=lake,
    )
    return lake


def test_file_c_projection_collapses_identity_and_preserves_non_award_residual(
    db_session, tmp_path, monkeypatch
):
    _load_fixture_stack(db_session, tmp_path, monkeypatch)
    lake = _materialize(db_session, tmp_path)

    result = FederalAwardProjectionEngine(lake=lake).calculate(db_session, _request())

    assert result.file_c.status == "READY"
    account = next(node for node in result.accounts if node.account_code == "012-3505")
    assert account.allocated_amount == Decimal("0.07")
    assert account.file_b_government_outlay == Decimal("100.00")
    assert account.file_c_government_outlay == Decimal("60.00")
    assert account.file_c_share_of_file_b == Decimal("0.6")
    assert account.projection_available is True
    assert account.conservation_difference == Decimal("0.00")
    assert sum(child.allocated_amount for child in account.children) == Decimal("0.07")

    award_a = next(child for child in account.children if child.award_identity == "AWARD-A")
    assert award_a.source_row_count == 2
    assert award_a.file_c_government_outlay == Decimal("30.00")
    assert award_a.allocated_amount == Decimal("0.02")
    assert award_a.award_family == "contract"
    assert award_a.recipient_name == "Recipient A"

    award_b = next(child for child in account.children if child.award_identity == "AWARD-B")
    assert award_b.source_row_count == 1
    assert award_b.file_c_government_outlay == Decimal("20.00")
    assert award_b.allocated_amount == Decimal("0.01")
    assert award_b.award_family == "assistance"

    unlinked = next(child for child in account.children if child.node_type == "unlinked_award_financial")
    assert unlinked.award_identity is None
    assert unlinked.file_c_government_outlay == Decimal("10.00")
    assert unlinked.allocated_amount == Decimal("0.01")

    residual = next(child for child in account.children if child.residual)
    assert residual.allocated_amount == Decimal("0.03")
    assert residual.label == "Non-award or unreconciled account activity"


def test_file_c_projection_rejects_partial_period_for_personalized_awards(
    db_session, tmp_path, monkeypatch
):
    _load_fixture_stack(db_session, tmp_path, monkeypatch)
    lake = _materialize(db_session, tmp_path, period="6")

    result = FederalAwardProjectionEngine(lake=lake).calculate(db_session, _request())

    assert result.file_c.status == "PARTIAL_OR_UNKNOWN_PERIOD"
    account = next(node for node in result.accounts if node.account_code == "012-3505")
    assert account.projection_available is False
    assert len(account.children) == 1
    assert account.children[0].residual is True
    assert account.children[0].allocated_amount == account.allocated_amount
    assert account.conservation_difference == Decimal("0.00")


def test_file_c_projection_refuses_to_overallocate_when_file_c_exceeds_file_b(
    db_session, tmp_path, monkeypatch
):
    _load_fixture_stack(db_session, tmp_path, monkeypatch)
    lake = _materialize(db_session, tmp_path, file_b_total="50.00")

    result = FederalAwardProjectionEngine(lake=lake).calculate(db_session, _request())

    account = next(node for node in result.accounts if node.account_code == "012-3505")
    assert account.file_b_government_outlay == Decimal("50.00")
    assert account.file_c_government_outlay == Decimal("60.00")
    assert account.projection_available is False
    assert account.file_c_share_of_file_b is None
    assert len(account.children) == 1
    assert account.children[0].residual is True
    assert account.children[0].allocated_amount == Decimal("0.07")
    assert account.conservation_difference == Decimal("0.00")
