"""Widen warehouse byte counters for multi-gigabyte official archives.

Revision ID: 0005_bigint_storage_bytes
Revises: 0004_data_warehouse_v2
Create Date: 2026-09-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_bigint_storage_bytes"
down_revision = "0004_data_warehouse_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("dataset_release") as batch:
        batch.alter_column(
            "raw_bytes",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )
        batch.alter_column(
            "normalized_bytes",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )

    with op.batch_alter_table("bulk_object") as batch:
        batch.alter_column(
            "byte_count",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("bulk_object") as batch:
        batch.alter_column(
            "byte_count",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )

    with op.batch_alter_table("dataset_release") as batch:
        batch.alter_column(
            "normalized_bytes",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
        batch.alter_column(
            "raw_bytes",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
