"""Phases 7, 8 and 9A jurisdiction spending schema.

Revision ID: 0003_phases_7_8_9a
Revises: 0002_phases_4_6
Create Date: 2026-09-13
"""

from alembic import op

from taxtrace.jurisdictional.db_models import JurisdictionSpendFact

revision = "0003_phases_7_8_9a"
down_revision = "0002_phases_4_6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    JurisdictionSpendFact.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    JurisdictionSpendFact.__table__.drop(bind=op.get_bind(), checkfirst=True)
