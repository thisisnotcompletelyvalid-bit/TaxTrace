from sqlalchemy import func, select

from taxtrace.warehouse_v2.catalog import load_catalog, seed_catalog
from taxtrace.warehouse_v2.db_models import DatasetDefinition


def test_catalog_contains_national_and_federal_backbones(db_session):
    catalog = load_catalog()
    by_key = {row["key"]: row for row in catalog["sources"]}
    assert "census-government-units-2022" in by_key
    assert "census-gov-finance-2022" in by_key
    assert "census-gov-finance-2024" in by_key
    assert "usaspending-file-b" in by_key
    assert "usaspending-file-c" in by_key
    assert "native-local-ledgers" in by_key

    prime_awards = by_key["usaspending-file-d1-d2"]
    assert prime_awards["grain"] == "prime_award_summary"
    assert prime_awards["source_url"].endswith("/api/v2/bulk_download/awards/")

    subawards = by_key["usaspending-file-f"]
    assert subawards["grain"] == "subaward"
    assert subawards["source_url"].endswith("/api/v2/bulk_download/awards/")

    seed_catalog(db_session)
    assert db_session.scalar(select(func.count(DatasetDefinition.id))) >= 10
