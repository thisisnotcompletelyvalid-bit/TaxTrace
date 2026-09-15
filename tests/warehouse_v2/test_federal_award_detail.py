import csv
import io
from datetime import date
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.federal_award_detail import FederalAwardDetailEngine
from taxtrace.warehouse_v2.lake import LakeStore
from taxtrace.warehouse_v2.usaspending_award_lake import materialize_award_archive
from taxtrace.warehouse_v2.usaspending_awards import build_award_bulk_payload


def _csv_text(header: list[str], rows: list[list[str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue()


def _write_award_archive(path: Path) -> None:
    contract_header = [
        "contract_award_unique_key",
        "award_id_piid",
        "recipient_name",
        "recipient_uei",
        "prime_award_base_transaction_description",
        "awarding_agency_name",
        "funding_agency_name",
        "award_type",
        "action_date",
        "federal_action_obligation",
    ]
    contract_rows = [
        [
            "AWARD-A",
            "PIID-A",
            "Recipient A",
            "UEI-A",
            "Prime award A",
            "Agency A",
            "Agency A",
            "Contract",
            "2025-01-15",
            "100.00",
        ],
        [
            "AWARD-A",
            "PIID-A",
            "Recipient A",
            "UEI-A",
            "Prime award A",
            "Agency A",
            "Agency A",
            "Contract",
            "2025-05-20",
            "25.00",
        ],
    ]
    assistance_header = [
        "assistance_award_unique_key",
        "award_id_fain",
        "recipient_name",
        "recipient_uei",
        "prime_award_base_transaction_description",
        "awarding_agency_name",
        "funding_agency_name",
        "award_type",
        "action_date",
        "federal_action_obligation",
    ]
    assistance_rows = [
        [
            "AWARD-B",
            "FAIN-B",
            "Recipient B",
            "UEI-B",
            "Prime award B",
            "Agency B",
            "Agency B",
            "Grant",
            "2025-03-10",
            "200.00",
        ]
    ]
    contract_subaward_header = [
        "prime_award_unique_key",
        "prime_award_piid",
        "subaward_number",
        "subaward_amount",
        "subawardee_name",
        "subawardee_uei",
        "subaward_description",
        "subaward_action_date",
    ]
    contract_subaward_rows = [
        [
            "AWARD-A",
            "PIID-A",
            "SUB-A-1",
            "25.00",
            "Subrecipient One",
            "SUB-UEI-1",
            "First subcontract",
            "2025-02-01",
        ],
        [
            "AWARD-A",
            "PIID-A",
            "SUB-A-2",
            "15.00",
            "Subrecipient Two",
            "SUB-UEI-2",
            "Second subcontract",
            "2025-04-01",
        ],
    ]
    assistance_subaward_header = [
        "prime_award_unique_key",
        "prime_award_fain",
        "subaward_number",
        "subaward_amount",
        "subawardee_name",
    ]
    assistance_subaward_rows = [
        ["AWARD-B", "FAIN-B", "SUB-B-1", "50.00", "Assistance Subrecipient"]
    ]

    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("contracts.csv", _csv_text(contract_header, contract_rows))
        archive.writestr("assistance.csv", _csv_text(assistance_header, assistance_rows))
        archive.writestr(
            "contract_subawards.csv",
            _csv_text(contract_subaward_header, contract_subaward_rows),
        )
        archive.writestr(
            "assistance_subawards.csv",
            _csv_text(assistance_subaward_header, assistance_subaward_rows),
        )


def _materialize(
    db_session,
    tmp_path: Path,
    *,
    full_year: bool,
    agency: int | str = "all",
) -> LakeStore:
    seed_catalog(db_session)
    archive = tmp_path / ("awards-full.zip" if full_year else "awards-slice.zip")
    _write_award_archive(archive)
    lake = LakeStore(root=tmp_path / "lake")
    request = (
        build_award_bulk_payload(2025, agency=agency)
        if full_year
        else build_award_bulk_payload(
            2025,
            agency=agency,
            start_date=date(2025, 3, 1),
            end_date=date(2025, 3, 7),
        )
    )
    materialize_award_archive(
        db_session,
        archive,
        fiscal_year=2025,
        request=request,
        lake=lake,
    )
    return lake


def test_award_detail_collapses_prime_transactions_and_keeps_subawards_non_additive(
    db_session, tmp_path
):
    lake = _materialize(db_session, tmp_path, full_year=True)

    result = FederalAwardDetailEngine(lake=lake).get(
        db_session,
        fiscal_year=2025,
        award_identity="AWARD-A",
    )

    assert result.prime_coverage.status == "READY"
    assert result.subaward_coverage.status == "READY"
    assert result.prime is not None
    assert result.prime.award_identity == "AWARD-A"
    assert result.prime.award_family == "contract"
    assert result.prime.transaction_count == 2
    assert result.prime.recipient_name == "Recipient A"
    assert result.prime.recipient_uei == "UEI-A"
    assert result.prime.first_action_date == "2025-01-15"
    assert result.prime.last_action_date == "2025-05-20"
    assert result.prime.additive is False
    assert result.prime.personalized_amount is None

    assert len(result.subawards) == 2
    assert {row.subaward_number for row in result.subawards} == {"SUB-A-1", "SUB-A-2"}
    assert {str(row.subaward_amount) for row in result.subawards} == {"25.00", "15.00"}
    assert all(row.additive is False for row in result.subawards)
    assert all(row.personalized_amount is None for row in result.subawards)
    assert {row.subawardee_name for row in result.subawards} == {
        "Subrecipient One",
        "Subrecipient Two",
    }


def test_award_detail_does_not_promote_partial_download_to_full_year_coverage(
    db_session, tmp_path
):
    lake = _materialize(db_session, tmp_path, full_year=False)

    result = FederalAwardDetailEngine(lake=lake).get(
        db_session,
        fiscal_year=2025,
        award_identity="AWARD-A",
    )

    assert result.prime_coverage.status == "NO_FULL_YEAR_RELEASE"
    assert result.subaward_coverage.status == "NO_FULL_YEAR_RELEASE"
    assert result.prime is None
    assert result.subawards == []


def test_award_detail_does_not_promote_single_agency_full_year_to_federal_coverage(
    db_session, tmp_path
):
    lake = _materialize(db_session, tmp_path, full_year=True, agency=12)

    result = FederalAwardDetailEngine(lake=lake).get(
        db_session,
        fiscal_year=2025,
        award_identity="AWARD-A",
    )

    assert result.prime_coverage.status == "NO_FULL_YEAR_RELEASE"
    assert result.subaward_coverage.status == "NO_FULL_YEAR_RELEASE"
    assert result.prime is None
    assert result.subawards == []
