from __future__ import annotations

from sqlalchemy import select

from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.db_models import DatasetDefinition, DatasetRelease
from taxtrace.warehouse_v2.product_activation import product_data_readiness


def _release(
    db_session,
    *,
    dataset_key: str,
    release_key: str,
    row_count: int,
    government_count: int,
    coverage_type: str,
) -> None:
    dataset = db_session.scalar(
        select(DatasetDefinition).where(DatasetDefinition.key == dataset_key)
    )
    assert dataset is not None
    db_session.add(
        DatasetRelease(
            dataset_id=dataset.id,
            release_key=release_key,
            reference_year=2022 if "2022" in release_key else 2024,
            reference_period=release_key,
            status="READY",
            coverage_type=coverage_type,
            row_count=row_count,
            government_count=government_count,
            metadata_json={},
        )
    )
    db_session.flush()


def test_empty_database_reports_fixture_or_empty(db_session) -> None:
    result = product_data_readiness(db_session)

    assert result.mode == "FIXTURE_OR_EMPTY"
    assert result.national_state_local_ready is False
    assert result.federal_core_ready is False
    assert result.government_registry.ready is False
    assert result.census_finance_2022.ready is False
    assert result.real_omb_account_rows == 0
    assert result.real_treasury_rows == 0
    assert result.warnings


def test_validated_scale_census_releases_enable_national_state_local_mode(db_session) -> None:
    seed_catalog(db_session)
    _release(
        db_session,
        dataset_key="census-government-units-2022",
        release_key="2022",
        row_count=92_114,
        government_count=92_114,
        coverage_type="CENSUS",
    )
    _release(
        db_session,
        dataset_key="census-gov-finance-2022",
        release_key="FY2022",
        row_count=1_337_594,
        government_count=88_819,
        coverage_type="CENSUS",
    )
    _release(
        db_session,
        dataset_key="census-gov-finance-2024",
        release_key="FY2024",
        row_count=10_000,
        government_count=1_000,
        coverage_type="SAMPLE",
    )
    db_session.commit()

    result = product_data_readiness(db_session)

    assert result.mode == "NATIONAL_STATE_LOCAL_WITH_LIMITED_FEDERAL"
    assert result.national_state_local_ready is True
    assert result.federal_core_ready is False
    assert result.government_registry.row_count == 92_114
    assert result.census_finance_2022.row_count == 1_337_594
    assert result.census_finance_2022.government_count == 88_819
    assert result.census_finance_2024.ready is True


def test_release_below_validated_scale_does_not_claim_national_readiness(db_session) -> None:
    seed_catalog(db_session)
    _release(
        db_session,
        dataset_key="census-government-units-2022",
        release_key="2022",
        row_count=1_000,
        government_count=1_000,
        coverage_type="CENSUS",
    )
    _release(
        db_session,
        dataset_key="census-gov-finance-2022",
        release_key="FY2022",
        row_count=25_000,
        government_count=500,
        coverage_type="CENSUS",
    )
    db_session.commit()

    result = product_data_readiness(db_session)

    assert result.national_state_local_ready is False
    assert result.government_registry.ready is False
    assert result.census_finance_2022.ready is False
    assert result.mode == "FIXTURE_OR_EMPTY"
