"""Phase 4-6 allocation, explorer, awards, and search schema.

Revision ID: 0002_phases_4_6
Revises: 0001_initial
Create Date: 2026-09-13
"""
from alembic import op

from taxtrace import db_models  # noqa: F401
from taxtrace.database import Base

revision = "0002_phases_4_6"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

NEW_TABLES = [
    "pool_spend_rule",
    "recipient",
    "award",
    "award_account_link",
    "canonical_category",
    "search_alias",
    "search_document",
]


def upgrade() -> None:
    # create_all is intentionally used here because SQLAlchemy's metadata is the canonical
    # cross-SQLite/PostgreSQL schema in this early project. It creates only missing tables.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(NEW_TABLES):
        table = Base.metadata.tables.get(name)
        if table is not None:
            table.drop(bind=bind, checkfirst=True)
