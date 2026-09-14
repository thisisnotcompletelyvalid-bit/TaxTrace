from __future__ import annotations

import subprocess
import sys


def test_warehouse_v2_import_registers_legacy_fk_targets() -> None:
    script = """
from sqlalchemy.orm import configure_mappers
from taxtrace.database import Base
import taxtrace.warehouse_v2.db_models  # noqa: F401

assert 'source_snapshot' in Base.metadata.tables
assert 'jurisdiction' in Base.metadata.tables
configure_mappers()
"""
    subprocess.run([sys.executable, "-c", script], check=True)
