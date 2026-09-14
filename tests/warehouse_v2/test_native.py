from taxtrace.db_models import Jurisdiction
from taxtrace.enums import JurisdictionLevel
from taxtrace.warehouse_v2.native import NativeLedgerMapping, ingest_native_csv


def test_generic_native_ledger_materializer(db_session, tmp_path):
    jurisdiction = Jurisdiction(code="TEST-CITY", name="Test City", level=JurisdictionLevel.MUNICIPAL)
    db_session.add(jurisdiction)
    db_session.commit()
    path = tmp_path / "checkbook.csv"
    path.write_text("id,amount,department,program,vendor,description\n1,1250.50,Police,Patrol,Vendor A,Radio equipment\n")
    result = ingest_native_csv(
        db_session,
        path=path,
        jurisdiction_code="TEST-CITY",
        dataset_key="test-city-checkbook",
        dataset_name="Test City Checkbook",
        authority="Test City",
        release_key="FY2025",
        default_fiscal_year=2025,
        metric="EXPENDITURE",
        mapping=NativeLedgerMapping(amount="amount", native_key="id", department="department", program="program", vendor="vendor", description="description"),
        materialize_rows=True,
        convert_to_parquet=False,
    )
    assert result["materialized_rows"] == 1
