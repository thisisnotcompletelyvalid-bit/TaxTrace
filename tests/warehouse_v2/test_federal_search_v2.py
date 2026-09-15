from __future__ import annotations

import csv
import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.federal_search import FederalSearchV2Engine
from taxtrace.warehouse_v2.lake import LakeStore
from taxtrace.warehouse_v2.usaspending_award_lake import materialize_award_archive


def _csv(header: list[str], rows: list[list[str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue()


def _award_archive(path: Path) -> None:
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
                        "2022-01-10",
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
                        "2022-05-12",
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
                        "2022-03-03",
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
                        "2022-02-14",
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
                        "2022-04-01",
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
