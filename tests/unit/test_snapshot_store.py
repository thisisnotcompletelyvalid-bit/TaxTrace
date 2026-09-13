import hashlib

from taxtrace.enums import SourceKind
from taxtrace.finance.snapshot import SnapshotStore


def test_snapshot_is_content_addressed(db_session, tmp_path):
    store = SnapshotStore(root=tmp_path / "raw")
    content = b"same official bytes"
    snapshot = store.save_bytes(
        db_session,
        source_kind=SourceKind.FIXTURE,
        source_name="fixture",
        source_url="https://example.invalid/source",
        content=content,
        filename="x.dat",
        reference_period="FY2025",
    )
    assert snapshot.sha256 == hashlib.sha256(content).hexdigest()
    assert snapshot.local_path.endswith("-x.dat")
    assert (tmp_path / "raw" / "fixture" / "FY2025").exists()
