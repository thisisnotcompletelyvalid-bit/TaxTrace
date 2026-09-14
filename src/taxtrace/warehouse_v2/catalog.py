from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from taxtrace.warehouse_v2.db_models import DatasetDefinition

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "source_catalog_v2.json"


@dataclass(frozen=True)
class CatalogSource:
    key: str
    authority: str
    name: str
    grain: str
    coverage_level: str
    source_url: str | None
    documentation_url: str | None
    bulk_available: bool
    ingestion_status: str
    priority: int
    metadata: dict


def load_catalog(path: Path | None = None) -> dict:
    return json.loads((path or CATALOG_PATH).read_text())


def sources(path: Path | None = None) -> list[CatalogSource]:
    payload = load_catalog(path)
    return [CatalogSource(**row) for row in payload["sources"]]


def get_source(key: str, path: Path | None = None) -> CatalogSource:
    for source in sources(path):
        if source.key == key:
            return source
    raise KeyError(f"Unknown data source {key!r}")


def seed_catalog(session: Session, path: Path | None = None) -> int:
    count = 0
    for item in sources(path):
        row = session.scalar(select(DatasetDefinition).where(DatasetDefinition.key == item.key))
        values = {
            "authority": item.authority,
            "name": item.name,
            "grain": item.grain,
            "coverage_level": item.coverage_level,
            "source_url": item.source_url,
            "documentation_url": item.documentation_url,
            "bulk_available": item.bulk_available,
            "ingestion_status": item.ingestion_status,
            "priority": item.priority,
            "metadata_json": item.metadata,
        }
        if row is None:
            row = DatasetDefinition(key=item.key, **values)
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        count += 1
    session.commit()
    return count
