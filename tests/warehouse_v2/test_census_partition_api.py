from decimal import Decimal

from sqlalchemy import select

from apps.api.app.routers.census_taxonomy_v2 import (
    census_taxonomy,
    government_finance_partition,
)
from taxtrace.db_models import Jurisdiction
from taxtrace.enums import JurisdictionLevel
from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.db_models import (
    DatasetDefinition,
    DatasetRelease,
    FinanceClassification,
    GovernmentFinanceFact,
)


def _classification(db_session, code: str, *, flow_type: str = "EXPENDITURE") -> FinanceClassification:
    row = FinanceClassification(
        scheme="CENSUS_GOV_FINANCE",
        code=code,
        name=f"Test {code}",
        flow_type=flow_type,
        object_type="test",
        function_code=code[1:] if len(code) == 3 else None,
        function_name=None,
        additive_partition=None,
        metadata_json={"native": True},
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_taxonomy_endpoint_reports_machine_valid_additive_parent() -> None:
    result = census_taxonomy()

    assert result["taxonomy_version"] == "1.0.0"
    assert result["parent"]["key"] == "direct_general_expenditure"
    assert result["parent"]["additive"] is True
    assert result["audit"]["valid"] is True
    assert result["semantics"]["raw_census_rows_additive"] is False
    assert result["semantics"]["partition_additive"] is True


def test_government_partition_uses_one_ready_census_release_and_conserves(db_session) -> None:
    seed_catalog(db_session)
    government = Jurisdiction(
        code="TEST-CITY",
        name="Test City",
        level=JurisdictionLevel.MUNICIPAL,
    )
    db_session.add(government)
    db_session.flush()

    dataset = db_session.scalar(
        select(DatasetDefinition).where(DatasetDefinition.key == "census-gov-finance-2022")
    )
    assert dataset is not None
    release = DatasetRelease(
        dataset_id=dataset.id,
        release_key="FY2022",
        reference_year=2022,
        reference_period="2022",
        status="READY",
        coverage_type="CENSUS",
        metadata_json={"raw_rows_additive": False},
    )
    db_session.add(release)
    db_session.flush()

    values = {
        "E62": Decimal("100.00"),
        "F62": Decimal("25.00"),
        "E24": Decimal("50.00"),
        "L44": Decimal("900.00"),
        "E91": Decimal("400.00"),
        "T01": Decimal("1000.00"),
    }
    for code, amount in values.items():
        classification = _classification(
            db_session,
            code,
            flow_type="REVENUE" if code.startswith("T") else "EXPENDITURE",
        )
        db_session.add(
            GovernmentFinanceFact(
                jurisdiction_id=government.id,
                dataset_release_id=release.id,
                classification_id=classification.id,
                fiscal_year=2022,
                amount=amount,
                status="ACTUAL",
                metric="REPORTED_AMOUNT",
                native_key=code,
                is_imputed=(code == "F62"),
                metadata_json={},
            )
        )
    db_session.commit()

    result = government_finance_partition(
        government.id,
        fiscal_year=2022,
        dataset_key=None,
        session=db_session,
    )

    assert result["government"]["name"] == "Test City"
    assert result["dataset_key"] == "census-gov-finance-2022"
    assert result["release"] == "FY2022"
    assert result["coverage_type"] == "CENSUS"
    assert result["additive"] is True
    assert result["parent"]["amount"] == "175.00"
    assert result["conservation_difference"] == "0.00"
    assert result["residual"]["amount"] == "0.00"
    assert result["excluded_native_expenditure_codes"] == ["E91", "L44"]
    assert result["imputed_codes"] == ["F62"]
    assert result["source_row_count"] == 5

    by_key = {node["key"]: node for node in result["nodes"]}
    assert by_key["police"]["amount"] == "125.00"
    assert by_key["police"]["item_codes"] == ["E62", "F62"]
    assert by_key["fire"]["amount"] == "50.00"
    assert sum(Decimal(node["amount"]) for node in result["nodes"]) == Decimal("175.00")
