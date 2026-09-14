from __future__ import annotations

from decimal import Decimal

from sqlalchemy import JSON, Enum, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from taxtrace.database import Base
from taxtrace.enums import DataStatus, FinancialMetric

MONEY = Numeric(24, 2)


class JurisdictionSpendFact(Base):
    """Actual state/local spending kept separate from the federal SpendFact grain."""

    __tablename__ = "jurisdiction_spend_fact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("jurisdiction.id"), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    metric: Mapped[FinancialMetric] = mapped_column(Enum(FinancialMetric), index=True)
    status: Mapped[DataStatus] = mapped_column(Enum(DataStatus), index=True)
    category_code: Mapped[str] = mapped_column(String(128), index=True)
    category_name: Mapped[str] = mapped_column(String(255), index=True)
    parent_category_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    source_snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshot.id"), index=True)
    record_scope: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "jurisdiction_id",
            "fiscal_year",
            "record_scope",
            "category_code",
            name="uq_jurisdiction_spend_fact_scope_category",
        ),
    )
