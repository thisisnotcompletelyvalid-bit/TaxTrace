from sqlalchemy import func, select

from taxtrace.warehouse_v2.catalog import load_catalog, seed_catalog
from taxtrace.warehouse_v2.db_models import DatasetDefinition


def test_catalog_contains_national_and_federal_backbones(db_session):
    catalog = load_catalog()
    keys = {row["key"] for row in catalog["sources"]}
    assert "census-government-units-2022" in keys
    assert "census-gov-finance-2022" in keys
    assert "census-gov-finance-2024" in keys
    assert "usaspending-file-b" in keys
    assert "usaspending-file-c" in keys
    assert "native-local-ledgers" in keys
    seed_catalog(db_session)
    assert db_session.scalar(select(func.count(DatasetDefinition.id))) >= 10
