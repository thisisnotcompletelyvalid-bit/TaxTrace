from __future__ import annotations

import csv
import io
from decimal import Decimal
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from taxtrace.allocation.models import FederalReceiptRequest
from taxtrace.enums import FilingStatus
from taxtrace.finance.fixtures import ingest_all_fixtures
from taxtrace.finance.seed import seed_federal_methodology_entities
from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.federal_search import FederalSearchV2Engine
from taxtrace.warehouse_v2.lake import LakeStore
from taxtrace.warehouse_v2.usaspending_award_lake import materialize_award_archive
from taxtrace.warehouse_v2.usaspending_lake import materialize_account_archive


def _csv(header: list[str], rows: list[list[str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue()


def _award_archive(path: Path, fiscal_year: int = 2022) -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "contracts.csv",
            _csv(
                [
                    "contract_award_unique_key",
                    "award_id_piid",
                    "recipient_name",
                    "recipient_uei",
                    "transaction_description",
                    "awarding_agency_name",
                    "award_type",
                    "action_date",
                    "total_obligated_amount",
                ],
                [
                    [
                        "CONT_AWD_ACME",
                        "PIID-ACME",
                        "Acme Research LLC",
                        "UEI-ACME",
                        "Quantum sensor prototype",
                        "National Aeronautics and Space Administration",
                        "Definitive Contract",
                        f"{fiscal_year}-01-10",
                        "100.00",
                    ],
                    [
                        "CONT_AWD_ACME",
                        "PIID-ACME",
                        "Acme Research LLC",
                        "UEI-ACME",
                        "Quantum sensor prototype modification",
                        "National Aeronautics and Space Administration",
                        "Definitive Contract",
                        f"{fiscal_year}-05-12",
                        "25.00",
                    ],
                ],
            ),
        )
        archive.writestr(
            "assistance.csv",
            _csv(
                [
                    "assistance_award_unique_key",
                    "award_id_fain",
                    "recipient_name",
                    "recipient_uei",
                    "award_description",
                    "awarding_agency_name",
                    "award_type",
                    "action_date",
                    "total_obligated_amount",
                ],
                [
                    [
                        "ASST_AWARD_UNI",
                        "FAIN-UNI",
                        "State University",
                        "UEI-UNI",
                        "Genomics research grant",
                        "National Institutes of Health",
                        "Grant",
                        f"{fiscal_year}-03-03",
                        "200.00",
                    ]
                ],
            ),
        )
        archive.writestr(
            "contract_subawards.csv",
            _csv(
                [
                    "prime_award_unique_key",
                    "prime_award_piid",
                    "subaward_number",
                    "subaward_amount",
                    "subawardee_name",
                    "subawardee_uei",
                    "subaward_description",
                    "subaward_action_date",
                ],
                [
                    [
                        "CONT_AWD_ACME",
                        "PIID-ACME",
                        "SUB-001",
                        "25.00",
                        "Small Partner Inc",
                        "UEI-SMALL",
                        "Sensor electronics subcontract",
                        f"{fiscal_year}-02-14",
                    ]
                ],
            ),
        )
        archive.writestr(
            "assistance_subawards.csv",
            _csv(
                [
                    "prime_award_unique_key",
                    "prime_award_fain",
                    "subaward_number",
                    "subaward_amount",
                    "subawardee_name",
                    "subawardee_uei",
                    "subaward_description",
                    "subaward_action_date",
                ],
                [
                    [
                        "ASST_AWARD_UNI",
                        "FAIN-UNI",
                        "SUB-A-1",
                        "50.00",
                        "Genome Center",
                        "UEI-GENOME",
                        "Sequencing core support",
                        f"{fiscal_year}-04-01",
                    ]
                ],
            ),
        )


def _materialize(db_session, tmp_path: Path, *, full_year: bool = True) -> LakeStore:
    seed_catalog(db_session)
    archive_path = tmp_path / ("full.zip" if full_year else "slice.zip")
    _award_archive(archive_path)
    lake = LakeStore(root=tmp_path / ("lake-full" if full_year else "lake-slice"))
    date_range = (
        {"start_date": "2021-10-01", "end_date": "2022-09-30"}
        if full_year
        else {"start_date": "2022-03-01", "end_date": "2022-03-01"}
    )
    materialize_award_archive(
        db_session,
        archive_path,
        fiscal_year=2022,
        request={"filters": {"date_range": date_range}},
        lake=lake,
    )
    return lake


def _load_fixture_stack(db_session, tmp_path: Path, monkeypatch) -> None:
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


def _account_archive(path: Path) -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "ObjectClassProgramActivity_1.csv",
            _csv(
                [
                    "federal_account_symbol",
                    "federal_account_name",
                    "program_activity_code",
                    "program_activity_name",
                    "object_class_code",
                    "object_class_name",
                    "gross_outlay_amount_FYB_to_period_end",
                    "financial_accounts_by_program_activity_object_class_id",
                ],
                [[
                    "012-3505",
                    "Food and Nutrition Service Programs",
                    "PA1",
                    "Nutrition Assistance",
                    "41.0",
                    "Grants and contributions",
                    "100.00",
                    "1",
                ]],
            ),
        )
        archive.writestr(
            "AwardFinancial_1.csv",
            _csv(
                [
                    "federal_account_symbol",
                    "federal_account_name",
                    "award_unique_key",
                    "award_id_piid",
                    "recipient_name",
                    "recipient_uei",
                    "prime_award_base_transaction_description",
                    "awarding_agency_name",
                    "funding_agency_name",
                    "award_type",
                    "gross_outlay_amount_FYB_to_period_end",
                    "financial_accounts_by_awards_id",
                ],
                [[
                    "012-3505",
                    "Food and Nutrition Service Programs",
                    "CONT_AWD_ACME",
                    "PIID-ACME",
                    "Acme Research LLC",
                    "UEI-ACME",
                    "Quantum sensor prototype",
                    "National Aeronautics and Space Administration",
                    "National Aeronautics and Space Administration",
                    "Contract",
                    "30.00",
                    "101",
                ]],
            ),
        )


def _materialize_personalized_stack(db_session, tmp_path: Path, monkeypatch) -> LakeStore:
    _load_fixture_stack(db_session, tmp_path, monkeypatch)
    lake = LakeStore(root=tmp_path / "lake-personalized")

    account_path = tmp_path / "accounts.zip"
    _account_archive(account_path)
    materialize_account_archive(
        db_session,
        account_path,
        fiscal_year=2025,
        request={
            "account_level": "treasury_account",
            "file_format": "csv",
            "filters": {
                "agency": "all",
                "fy": "2025",
                "period": "12",
                "submission_types": ["object_class_program_activity", "award_financial"],
            },
        },
        lake=lake,
    )

    award_path = tmp_path / "awards-2025.zip"
    _award_archive(award_path, fiscal_year=2025)
    materialize_award_archive(
        db_session,
        award_path,
        fiscal_year=2025,
        request={
            "filters": {
                "date_range": {"start_date": "2024-10-01", "end_date": "2025-09-30"}
            }
        },
        lake=lake,
    )
    return lake


def _receipt_request() -> FederalReceiptRequest:
    return FederalReceiptRequest(
        tax_year=2026,
        filing_status=FilingStatus.SINGLE,
        wage_income=Decimal("50000"),
        spending_fiscal_year=2025,
    )


def test_search_collapses_prime_transactions_and_surfaces_recipients(db_session, tmp_path: Path) -> None:
    lake = _materialize(db_session, tmp_path)
    result = FederalSearchV2Engine(lake=lake).search(
        db_session,
        fiscal_year=2022,
        query="Acme Research",
        limit=20,
    )

    assert result.prime_coverage.status == "READY"
    assert result.subaward_coverage.status == "READY"
    assert result.receipt_context is False
    assert result.personalization_status == "NOT_REQUESTED"

    prime = next(row for row in result.results if row.entity_type == "prime_award")
    recipient = next(row for row in result.results if row.entity_type == "recipient")
    assert prime.award_identity == "CONT_AWD_ACME"
    assert prime.metadata["transaction_count"] == 2
    assert prime.target_award_identity == "CONT_AWD_ACME"
    assert prime.additive is False
    assert recipient.recipient_name == "Acme Research LLC"
    assert recipient.metadata["award_count"] == 1
    assert recipient.target_award_identity == "CONT_AWD_ACME"
    assert recipient.additive is False


def test_search_subaward_is_non_additive_and_targets_prime_award(db_session, tmp_path: Path) -> None:
    lake = _materialize(db_session, tmp_path)
    result = FederalSearchV2Engine(lake=lake).search(
        db_session,
        fiscal_year=2022,
        query="Small Partner",
        entity_types=["subaward"],
        limit=10,
    )

    assert len(result.results) == 1
    subaward = result.results[0]
    assert subaward.entity_type == "subaward"
    assert subaward.title == "Small Partner Inc"
    assert subaward.award_identity == "CONT_AWD_ACME"
    assert subaward.target_award_identity == "CONT_AWD_ACME"
    assert subaward.personalized_amount is None
    assert subaward.prime_personalized_amount is None
    assert subaward.metadata["subaward_number"] == "SUB-001"
    assert subaward.metadata["subaward_amount"] == "25.00"
    assert subaward.additive is False


def test_receipt_context_annotates_prime_but_never_allocates_to_subaward(
    db_session, tmp_path: Path, monkeypatch
) -> None:
    lake = _materialize_personalized_stack(db_session, tmp_path, monkeypatch)
    engine = FederalSearchV2Engine(lake=lake)

    prime_search = engine.search(
        db_session,
        fiscal_year=2025,
        query="Acme Research",
        receipt_request=_receipt_request(),
    )
    assert prime_search.personalization_status == "READY"
    prime = next(row for row in prime_search.results if row.entity_type == "prime_award")
    recipient = next(row for row in prime_search.results if row.entity_type == "recipient")
    assert prime.personalized_amount == Decimal("0.02")
    assert recipient.personalized_amount == Decimal("0.02")

    subaward_search = engine.search(
        db_session,
        fiscal_year=2025,
        query="Small Partner",
        entity_types=["subaward"],
        receipt_request=_receipt_request(),
    )
    subaward = subaward_search.results[0]
    assert subaward.personalized_amount is None
    assert subaward.prime_personalized_amount == Decimal("0.02")
    assert "not allocated" in subaward.warning or "no personalized amount" in subaward.warning


def test_search_uses_only_full_year_award_releases(db_session, tmp_path: Path) -> None:
    lake = _materialize(db_session, tmp_path, full_year=False)
    result = FederalSearchV2Engine(lake=lake).search(
        db_session,
        fiscal_year=2022,
        query="Acme",
    )

    assert result.results == []
    assert result.prime_coverage.status == "NO_FULL_YEAR_RELEASE"
    assert result.subaward_coverage.status == "NO_FULL_YEAR_RELEASE"
    assert any("incomplete" in warning for warning in result.warnings)


def test_search_rejects_unknown_entity_type(db_session, tmp_path: Path) -> None:
    lake = _materialize(db_session, tmp_path)
    with pytest.raises(ValueError, match="unsupported Warehouse V2 federal search types"):
        FederalSearchV2Engine(lake=lake).search(
            db_session,
            fiscal_year=2022,
            query="Acme",
            entity_types=["obligation"],
        )
