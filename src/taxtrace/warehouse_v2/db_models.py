from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from taxtrace.database import Base
from taxtrace.db_models import SourceSnapshot

MONEY = Numeric(24, 2)
SOURCE_SNAPSHOT_TABLE = SourceSnapshot.__tablename__


class DatasetDefinition(Base):
    """A durable description of one authoritative upstream dataset/grain."""

    __tablename__ = "dataset_definition"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    authority: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(512))
    grain: Mapped[str] = mapped_column(String(128), index=True)
    coverage_level: Mapped[str] = mapped_column(String(64), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    documentation_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    bulk_available: Mapped[bool] = mapped_column(Boolean, default=False)
    ingestion_status: Mapped[str] = mapped_column(String(32), default="PLANNED", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class DatasetRelease(Base):
    """One immutable vintage/release of an upstream dataset."""

    __tablename__ = "dataset_release"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset_definition.id"), index=True)
    release_key: Mapped[str] = mapped_column(String(128), index=True)
    reference_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reference_period: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{SOURCE_SNAPSHOT_TABLE}.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="DISCOVERED", index=True)
    coverage_type: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    government_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    classification_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    normalized_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("dataset_id", "release_key", name="uq_dataset_release_key"),
    )


class GovernmentIdentifier(Base):
    """Crosswalk from a TaxTrace jurisdiction to external government identifiers."""

    __tablename__ = "government_identifier"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("jurisdiction.id"), index=True)
    scheme: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(String(255), index=True)
    valid_from_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_to_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("scheme", "value", name="uq_government_identifier_scheme_value"),
    )


class FinanceClassification(Base):
    """Native and standardized finance classifications without forcing them into one tree."""

    __tablename__ = "finance_classification"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(512), index=True)
    flow_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    object_type: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    function_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    function_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("finance_classification.id"), nullable=True, index=True
    )
    additive_partition: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("scheme", "code", name="uq_finance_classification_scheme_code"),
    )


class GovernmentFinanceFact(Base):
    """Standardized government finance facts, including Census item-code records."""

    __tablename__ = "government_finance_fact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("jurisdiction.id"), index=True)
    dataset_release_id: Mapped[int] = mapped_column(ForeignKey("dataset_release.id"), index=True)
    classification_id: Mapped[int] = mapped_column(
        ForeignKey("finance_classification.id"), index=True
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(32), default="ACTUAL", index=True)
    metric: Mapped[str] = mapped_column(String(64), default="REPORTED_AMOUNT", index=True)
    native_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    is_imputed: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    origin_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "dataset_release_id",
            "jurisdiction_id",
            "classification_id",
            "fiscal_year",
            "native_key",
            name="uq_government_finance_fact_native",
        ),
        Index(
            "ix_gov_finance_jur_year_class",
            "jurisdiction_id",
            "fiscal_year",
            "classification_id",
        ),
    )


class DetailedSpendFact(Base):
    """Materialized high-detail spending rows from native ledgers or federal award/account data."""

    __tablename__ = "detailed_spend_fact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("jurisdiction.id"), index=True)
    dataset_release_id: Mapped[int] = mapped_column(ForeignKey("dataset_release.id"), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    metric: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTUAL", index=True)
    department: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    fund: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    account: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    program: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    activity: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    object_class: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    project: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    vendor: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    recipient: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    award_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    native_key: Mapped[str] = mapped_column(String(512), index=True)
    classification_id: Mapped[int | None] = mapped_column(
        ForeignKey("finance_classification.id"), nullable=True, index=True
    )
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "dataset_release_id", "native_key", name="uq_detailed_spend_release_native"
        ),
        Index("ix_detailed_spend_jur_year_metric", "jurisdiction_id", "fiscal_year", "metric"),
    )


class BulkObject(Base):
    """A raw or normalized lake object kept outside the relational hot path."""

    __tablename__ = "bulk_object"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_release_id: Mapped[int] = mapped_column(ForeignKey("dataset_release.id"), index=True)
    object_key: Mapped[str] = mapped_column(String(1024), index=True)
    storage_format: Mapped[str] = mapped_column(String(32), index=True)
    layer: Mapped[str] = mapped_column(String(32), index=True)
    partition_json: Mapped[dict] = mapped_column(JSON, default=dict)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    byte_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "dataset_release_id", "object_key", name="uq_bulk_object_release_key"
        ),
    )


class CoverageRecord(Base):
    """What TaxTrace actually knows about a government at one grain/vintage."""

    __tablename__ = "coverage_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("jurisdiction.id"), index=True)
    dataset_release_id: Mapped[int] = mapped_column(ForeignKey("dataset_release.id"), index=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    grain: Mapped[str] = mapped_column(String(128), index=True)
    completeness: Mapped[str] = mapped_column(String(32), index=True)
    record_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    classification_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_grade: Mapped[str | None] = mapped_column(String(8), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "jurisdiction_id",
            "dataset_release_id",
            "fiscal_year",
            "grain",
            name="uq_coverage_jur_release_year_grain",
        ),
    )
