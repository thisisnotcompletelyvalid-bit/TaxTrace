from __future__ import annotations

from sqlalchemy import BigInteger

from taxtrace.warehouse_v2.db_models import BulkObject, DatasetRelease


def test_multi_gigabyte_storage_metadata_uses_bigint() -> None:
    assert isinstance(DatasetRelease.__table__.c.raw_bytes.type, BigInteger)
    assert isinstance(DatasetRelease.__table__.c.normalized_bytes.type, BigInteger)
    assert isinstance(BulkObject.__table__.c.byte_count.type, BigInteger)
