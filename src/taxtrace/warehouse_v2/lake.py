from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from taxtrace.config import get_settings
from taxtrace.warehouse_v2.db_models import BulkObject


@dataclass(frozen=True)
class LakeObjectInfo:
    object_key: str
    path: Path
    sha256: str
    byte_count: int


class LakeStore:
    """Filesystem/object-store-shaped lake for raw and high-cardinality normalized data."""

    def __init__(self, root: Path | None = None):
        self.root = root or get_settings().warehouse_data_dir / "lake"
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, dataset_key: str, release_key: str, layer: str, filename: str) -> Path:
        path = self.root / layer / dataset_key / release_key / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def file_info(path: Path, root: Path | None = None) -> LakeObjectInfo:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        object_key = str(path.relative_to(root)) if root and path.is_relative_to(root) else str(path)
        return LakeObjectInfo(object_key, path, digest.hexdigest(), size)

    def register_file(
        self,
        session: Session,
        *,
        dataset_release_id: int,
        path: Path,
        layer: str,
        storage_format: str,
        row_count: int | None = None,
        partition: dict | None = None,
        metadata: dict | None = None,
    ) -> BulkObject:
        info = self.file_info(path, self.root)
        row = session.scalar(
            select(BulkObject).where(
                BulkObject.dataset_release_id == dataset_release_id,
                BulkObject.object_key == info.object_key,
            )
        )
        values = {
            "storage_format": storage_format,
            "layer": layer,
            "partition_json": partition or {},
            "sha256": info.sha256,
            "row_count": row_count,
            "byte_count": info.byte_count,
            "metadata_json": metadata or {},
        }
        if row is None:
            row = BulkObject(
                dataset_release_id=dataset_release_id,
                object_key=info.object_key,
                **values,
            )
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        session.commit()
        return row

    def csv_to_parquet(self, source: Path, destination: Path) -> int:
        """Normalize a huge CSV to compressed Parquet with DuckDB streaming through disk."""
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - dependency error is operational
            raise RuntimeError("duckdb is required for CSV-to-Parquet lake materialization") from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect()
        try:
            connection.execute(
                "COPY (SELECT * FROM read_csv_auto(?, header=true, all_varchar=true, "
                "sample_size=-1)) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                [str(source), str(destination)],
            )
            return int(connection.execute("SELECT count(*) FROM read_parquet(?)", [str(destination)]).fetchone()[0])
        finally:
            connection.close()
