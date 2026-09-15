from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from taxtrace.enums import AllocationRelation, ConfidenceGrade, DataStatus, FinancialMetric
from taxtrace.methodology.version import METHODOLOGY_VERSION
from taxtrace.tax.models import FederalTaxInput, FederalTaxResult


class FederalReceiptRequest(FederalTaxInput):
    spending_fiscal_year: int = Field(default=2025, ge=1900, le=2200)


class SourceReference(BaseModel):
    id: int
    name: str
    url: str
    reference_period: str | None = None
    retrieved_at: str | None = None
    parser_version: str


class NodeProvenance(BaseModel):
    formula: str
    pool_code: str
    pool_name: str
    rule_description: str
    metric: FinancialMetric = FinancialMetric.OUTLAY
    status: DataStatus = DataStatus.ACTUAL
    source_snapshots: list[SourceReference] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ReceiptNode(BaseModel):
    key: str
    label: str
    node_type: str
    allocated_amount: Decimal
    government_spending_amount: Decimal | None = None
    share_of_pool_spending: Decimal | None = None
    relation: AllocationRelation
    confidence: ConfidenceGrade
    additive: bool = True
    allocation_status: str = "ALLOCATED"
    provenance: list[NodeProvenance] = Field(default_factory=list)
    children: list["ReceiptNode"] = Field(default_factory=list)


class PoolReceipt(BaseModel):
    code: str
    name: str
    contribution: Decimal
    eligible_government_spending: Decimal
    relation: AllocationRelation
    confidence: ConfidenceGrade
    allocation_status: str
    nodes: list[ReceiptNode]
    rule_description: str


class TaxToPoolAllocation(BaseModel):
    revenue_code: str
    revenue_name: str
    tax_amount: Decimal
    pool_code: str
    pool_name: str
    mapping_share: Decimal
    allocated_to_pool: Decimal
    authority: str


class FederalReceiptResult(BaseModel):
    methodology_version: str = METHODOLOGY_VERSION
    tax_result: FederalTaxResult
    spending_fiscal_year: int
    spending_metric: FinancialMetric = FinancialMetric.OUTLAY
    spending_status: DataStatus = DataStatus.ACTUAL
    total_allocable_taxes: Decimal
    tax_to_pool: list[TaxToPoolAllocation]
    pools: list[PoolReceipt]
    purpose: list[ReceiptNode]
    conservation_difference: Decimal
    warnings: list[str] = Field(default_factory=list)
