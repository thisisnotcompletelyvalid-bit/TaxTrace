"""National multi-jurisdiction data warehouse v2.

Revision ID: 0004_data_warehouse_v2
Revises: 0003_phases_7_8_9a
Create Date: 2026-09-14
"""

from alembic import op

from taxtrace.warehouse_v2.db_models import (
    BulkObject,
    CoverageRecord,
    DatasetDefinition,
    DatasetRelease,
    DetailedSpendFact,
    FinanceClassification,
    GovernmentFinanceFact,
    GovernmentIdentifier,
)

revision = "0004_data_warehouse_v2"
down_revision = "0003_phases_7_8_9a"
branch_labels = None
depends_on = None

TABLES = [
    DatasetDefinition.__table__,
    DatasetRelease.__table__,
    GovernmentIdentifier.__table__,
    FinanceClassification.__table__,
    GovernmentFinanceFact.__table__,
    DetailedSpendFact.__table__,
    BulkObject.__table__,
    CoverageRecord.__table__,
]


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
