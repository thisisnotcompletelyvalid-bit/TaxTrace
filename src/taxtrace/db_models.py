from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from taxtrace.database import Base
from taxtrace.enums import (
    DataStatus,
    FinancialMetric,
    JurisdictionLevel,
    PoolType,
    SourceKind,
)

MONEY = Numeric(24, 2)
RATIO = Numeric(20, 12)


class Jurisdiction(Base):
    __tablename__ = "jurisdiction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    level: Mapped[JurisdictionLevel] = mapped_column(Enum(JurisdictionLevel))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("jurisdiction.id"), nullable=True)


class SourceSnapshot(Base):
    __tablename__ = "source_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind), index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str] = mapped_column(Text)
    reference_period: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    local_path: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(String(64), default="1")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class IngestRun(Base):
    __tablename__ = "ingest_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING")
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_loaded: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Agency(Base):
    __tablename__ = "agency"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind), index=True)
    native_code: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    abbreviation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("source_kind", "native_code", name="uq_agency_source_code"),)


class FederalAccount(Base):
    __tablename__ = "federal_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int | None] = mapped_column(ForeignKey("agency.id"), nullable=True, index=True)
    native_code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(512), index=True)
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind))
    __table_args__ = (UniqueConstraint("source_kind", "native_code", name="uq_federal_account_source_code"),)


class TreasuryAccount(Base):
    __tablename__ = "treasury_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    federal_account_id: Mapped[int | None] = mapped_column(ForeignKey("federal_account.id"), nullable=True, index=True)
    tas: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(512))
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind))
    __table_args__ = (UniqueConstraint("source_kind", "tas", name="uq_treasury_account_source_tas"),)


class ProgramActivity(Base):
    __tablename__ = "program_activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int | None] = mapped_column(ForeignKey("agency.id"), nullable=True, index=True)
    native_code: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(512), index=True)
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind))


class ObjectClass(Base):
    __tablename__ = "object_class"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int | None] = mapped_column(ForeignKey("agency.id"), nullable=True, index=True)
    native_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(512), index=True)
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind))


class BudgetFunction(Base):
    __tablename__ = "budget_function"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    native_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind))


class BudgetSubfunction(Base):
    __tablename__ = "budget_subfunction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    function_id: Mapped[int | None] = mapped_column(ForeignKey("budget_function.id"), nullable=True, index=True)
    native_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind))


class SpendFact(Base):
    __tablename__ = "spend_fact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    metric: Mapped[FinancialMetric] = mapped_column(Enum(FinancialMetric), index=True)
    status: Mapped[DataStatus] = mapped_column(Enum(DataStatus), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    source_snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshot.id"), index=True)
    agency_id: Mapped[int | None] = mapped_column(ForeignKey("agency.id"), nullable=True, index=True)
    federal_account_id: Mapped[int | None] = mapped_column(ForeignKey("federal_account.id"), nullable=True, index=True)
    treasury_account_id: Mapped[int | None] = mapped_column(ForeignKey("treasury_account.id"), nullable=True, index=True)
    program_activity_id: Mapped[int | None] = mapped_column(ForeignKey("program_activity.id"), nullable=True, index=True)
    object_class_id: Mapped[int | None] = mapped_column(ForeignKey("object_class.id"), nullable=True, index=True)
    budget_function_id: Mapped[int | None] = mapped_column(ForeignKey("budget_function.id"), nullable=True, index=True)
    budget_subfunction_id: Mapped[int | None] = mapped_column(ForeignKey("budget_subfunction.id"), nullable=True, index=True)
    record_scope: Mapped[str] = mapped_column(String(64), index=True)
    native_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class TreasuryAggregate(Base):
    __tablename__ = "treasury_aggregate"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(32), index=True)
    category_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category_name: Mapped[str] = mapped_column(String(512), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    source_snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshot.id"), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class OMBAccountRecord(Base):
    __tablename__ = "omb_account_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[DataStatus] = mapped_column(Enum(DataStatus), index=True)
    agency_code: Mapped[str] = mapped_column(String(16), index=True)
    agency_name: Mapped[str] = mapped_column(String(255))
    bureau_code: Mapped[str] = mapped_column(String(16))
    bureau_name: Mapped[str] = mapped_column(String(255))
    account_code: Mapped[str] = mapped_column(String(32), index=True)
    account_name: Mapped[str] = mapped_column(String(512))
    treasury_agency_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cgac_agency_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    subfunction_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    subfunction_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bea_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    grant_split: Mapped[str | None] = mapped_column(String(32), nullable=True)
    on_off_budget: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    source_snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshot.id"), index=True)


class OMBReceiptRecord(Base):
    __tablename__ = "omb_receipt_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[DataStatus] = mapped_column(Enum(DataStatus), index=True)
    source_category_code: Mapped[str] = mapped_column(String(16), index=True)
    source_category_name: Mapped[str] = mapped_column(String(255))
    source_subcategory_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_subcategory_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agency_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    agency_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bureau_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    bureau_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    treasury_agency_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cgac_agency_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    on_off_budget: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    source_snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshot.id"), index=True)


class FundingPool(Base):
    __tablename__ = "funding_pool"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    pool_type: Mapped[PoolType] = mapped_column(Enum(PoolType))
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("jurisdiction.id"), index=True)
    description: Mapped[str] = mapped_column(Text)


class RevenueType(Base):
    __tablename__ = "revenue_type"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("jurisdiction.id"), index=True)
    description: Mapped[str] = mapped_column(Text)


class RevenuePoolMapping(Base):
    __tablename__ = "revenue_pool_mapping"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revenue_type_id: Mapped[int] = mapped_column(ForeignKey("revenue_type.id"), index=True)
    funding_pool_id: Mapped[int] = mapped_column(ForeignKey("funding_pool.id"), index=True)
    share: Mapped[Decimal] = mapped_column(RATIO)
    effective_start_year: Mapped[int] = mapped_column(Integer)
    effective_end_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authority: Mapped[str] = mapped_column(Text)


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    comparison_name: Mapped[str] = mapped_column(String(255))
    left_value: Mapped[Decimal] = mapped_column(MONEY)
    right_value: Mapped[Decimal] = mapped_column(MONEY)
    absolute_difference: Mapped[Decimal] = mapped_column(MONEY)
    relative_difference: Mapped[Decimal | None] = mapped_column(RATIO, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
