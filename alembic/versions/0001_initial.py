"""Initial TaxTrace schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-13
"""
from alembic import op

from taxtrace.database import Base
from taxtrace import db_models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
