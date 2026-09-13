from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from taxtrace.config import get_settings
from taxtrace.db_models import SourceSnapshot
from taxtrace.enums import SourceKind


class SnapshotStore:
    def __init__(self, root: Path | None = None):
        self.root = root or get_settings().raw_data_dir

    def save_bytes(
        self,
        session: Session,
        *,
        source_kind: SourceKind,
        source_name: str,
        source_url: str,
        content: bytes,
        filename: str,
        reference_period: str | None = None,
        parser_version: str = "1",
        metadata: dict | None = None,
    ) -> SourceSnapshot:
        digest = hashlib.sha256(content).hexdigest()
        target_dir = self.root / source_kind.value.lower() / (reference_period or "unperiodized")
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{digest[:12]}-{filename}"
        if not path.exists():
            path.write_bytes(content)
        snapshot = SourceSnapshot(
            source_kind=source_kind,
            source_name=source_name,
            source_url=source_url,
            reference_period=reference_period,
            retrieved_at=datetime.now(UTC),
            sha256=digest,
            original_filename=filename,
            local_path=str(path),
            parser_version=parser_version,
            metadata_json=metadata or {},
        )
        session.add(snapshot)
        session.flush()
        return snapshot

    def save_json(self, session: Session, **kwargs) -> SourceSnapshot:
        data = kwargs.pop("data")
        content = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.save_bytes(session, content=content, **kwargs)

    def register_local_file(
        self,
        session: Session,
        *,
        source_kind: SourceKind,
        source_name: str,
        source_url: str,
        path: Path,
        reference_period: str | None = None,
        parser_version: str = "1",
        metadata: dict | None = None,
    ) -> SourceSnapshot:
        return self.save_bytes(
            session,
            source_kind=source_kind,
            source_name=source_name,
            source_url=source_url,
            content=path.read_bytes(),
            filename=path.name,
            reference_period=reference_period,
            parser_version=parser_version,
            metadata=metadata,
        )
