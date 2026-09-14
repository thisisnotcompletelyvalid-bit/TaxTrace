from pathlib import Path

from taxtrace.warehouse_v2.lake import LakeStore


def test_file_info_uses_relative_key_inside_lake(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    path = lake_root / "normalized" / "dataset" / "FY2025" / "part.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"parquet-ish")

    info = LakeStore.file_info(path, lake_root)

    assert info.object_key == "normalized/dataset/FY2025/part.parquet"
    assert info.path == path
    assert info.byte_count == len(b"parquet-ish")


def test_file_info_hides_external_absolute_path(tmp_path: Path) -> None:
    lake_root = tmp_path / "lake"
    lake_root.mkdir()
    raw = tmp_path / "private" / "source.zip"
    raw.parent.mkdir()
    raw.write_bytes(b"official-source-bytes")

    info = LakeStore.file_info(raw, lake_root)

    assert info.object_key == f"external/{info.sha256}/source.zip"
    assert str(tmp_path) not in info.object_key
    assert info.path == raw
