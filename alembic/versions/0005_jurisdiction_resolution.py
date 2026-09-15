"""Jurisdiction resolution relation graph.

Revision ID: 0005_jurisdiction_resolution
Revises: 0004_data_warehouse_v2
Create Date: 2026-09-14
"""

from alembic import op

from taxtrace.warehouse_v2.db_models import JurisdictionRelation

revision = "0005_jurisdiction_resolution"
down_revision = "0004_data_warehouse_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    JurisdictionRelation.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    JurisdictionRelation.__table__.drop(bind=op.get_bind(), checkfirst=True)
