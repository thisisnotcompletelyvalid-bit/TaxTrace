from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from taxtrace.allocation.models import (
    FederalReceiptRequest,
    FederalReceiptResult,
    NodeProvenance,
    PoolReceipt,
    ReceiptNode,
    SourceReference,
    TaxToPoolAllocation,
)
from taxtrace.db_models import (
    BudgetFunction,
    BudgetSubfunction,
    FundingPool,
    PoolSpendRule,
    RevenuePoolMapping,
    RevenueType,
    SourceSnapshot,
    SpendFact,
)
from taxtrace.enums import AllocationRelation, ConfidenceGrade, DataStatus, FinancialMetric
from taxtrace.tax.engine import FederalTaxEngine
from taxtrace.tax.models import FederalTaxInput

CENT = Decimal("0.01")
ZERO = Decimal("0")
CONFIDENCE_ORDER = {
    ConfidenceGrade.A: 0,
    ConfidenceGrade.B: 1,
    ConfidenceGrade.C: 2,
    ConfidenceGrade.D: 3,
    ConfidenceGrade.NA: 4,
}


@dataclass
class AllocatedFact:
    pool: FundingPool
    rule: PoolSpendRule
    fact: SpendFact
    allocated_amount: Decimal
    denominator: Decimal
    subfunction: BudgetSubfunction | None
    function: BudgetFunction | None


@dataclass
class PoolComputation:
    pool: FundingPool
    rule: PoolSpendRule
    contribution: Decimal
    denominator: Decimal
    allocations: list[AllocatedFact]


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def worst_confidence(values: list[ConfidenceGrade]) -> ConfidenceGrade:
    return max(values, key=lambda x: CONFIDENCE_ORDER[x]) if values else ConfidenceGrade.NA


class FederalAllocationEngine:
    """Convert supported federal tax liabilities into an auditable expenditure attribution.

    Phase 4 deliberately anchors actual spending to OMB account-level OUTLAY facts. Dedicated
    payroll taxes are restricted by explicit pool-spend rules. General revenue uses the remainder
    of the eligible OMB outlay base. If a dedicated pool has no matching public expenditure detail,
    the contribution remains conserved in an explicit UNALLOCATED_DETAIL node rather than being
    silently routed somewhere else.
    """

    def __init__(self, tax_engine: FederalTaxEngine | None = None):
        self.tax_engine = tax_engine or FederalTaxEngine()

    def calculate(self, session: Session, request: FederalReceiptRequest) -> FederalReceiptResult:
        tax_inp = FederalTaxInput(**request.model_dump(exclude={"spending_fiscal_year"}))
        tax_result = self.tax_engine.calculate(tax_inp)
        return self.calculate_from_tax_result(session, request, tax_result)

    def calculate_from_tax_result(self, session: Session, request: FederalReceiptRequest, tax_result):
        components = {
            "FED_INCOME_TAX": tax_result.federal_income_tax_liability,
            "SS_EMPLOYEE": tax_result.social_security_tax,
            "MEDICARE_EMPLOYEE": tax_result.medicare_tax,
            "ADDITIONAL_MEDICARE": tax_result.additional_medicare_tax,
        }
        total = money(sum((Decimal(v) for v in components.values()), ZERO))
        mappings, pool_contributions, tax_to_pool = self._map_revenue_to_pools(
            session, components, request.tax_year
        )
        pool_computations = self.compute_pool_allocations(
            session, pool_contributions, request.spending_fiscal_year
        )
        pools = [self._pool_receipt(session, c) for c in pool_computations]
        purpose = self._aggregate_purpose(session, pool_computations)
        allocated_total = money(sum((p.contribution for p in pools), ZERO))
        difference = money(total - allocated_total)
        warnings: list[str] = []
        if difference != ZERO:
            raise ValueError(
                "Tax-to-pool mappings do not conserve the supported liability; "
                f"refusing to publish an incomplete receipt (difference {difference})."
            )
        if any(p.allocation_status != "ALLOCATED" for p in pools):
            warnings.append(
                "One or more financing pools lack sufficiently specific actual expenditure detail; "
                "their tax dollars are preserved as explicit unallocated-detail nodes."
            )
        if mappings == 0:
            warnings.append("No active revenue-to-pool mappings were found for this tax year.")
        return FederalReceiptResult(
            tax_result=tax_result,
            spending_fiscal_year=request.spending_fiscal_year,
            total_allocable_taxes=total,
            tax_to_pool=tax_to_pool,
            pools=pools,
            purpose=purpose,
            conservation_difference=difference,
            warnings=warnings,
        )

    def _map_revenue_to_pools(self, session, components: dict[str, Decimal], tax_year: int):
        pool_contributions: dict[int, Decimal] = defaultdict(lambda: ZERO)
        rows: list[TaxToPoolAllocation] = []
        mapping_count = 0
        for code, tax_amount in components.items():
            tax_amount = money(Decimal(tax_amount))
            revenue = session.scalar(select(RevenueType).where(RevenueType.code == code))
            if revenue is None:
                continue
            mappings = session.scalars(
                select(RevenuePoolMapping).where(
                    RevenuePoolMapping.revenue_type_id == revenue.id,
                    RevenuePoolMapping.effective_start_year <= tax_year,
                    or_(
                        RevenuePoolMapping.effective_end_year.is_(None),
                        RevenuePoolMapping.effective_end_year >= tax_year,
                    ),
                )
            ).all()
            if not mappings:
                continue
            raw = [tax_amount * Decimal(m.share) for m in mappings]
            allocated = _reconcile_parts(tax_amount, raw)
            for mapping, amount in zip(mappings, allocated, strict=True):
                pool = session.get(FundingPool, mapping.funding_pool_id)
                if pool is None:
                    continue
                mapping_count += 1
                pool_contributions[pool.id] += amount
                rows.append(
                    TaxToPoolAllocation(
                        revenue_code=revenue.code,
                        revenue_name=revenue.name,
                        tax_amount=tax_amount,
                        pool_code=pool.code,
                        pool_name=pool.name,
                        mapping_share=Decimal(mapping.share),
                        allocated_to_pool=amount,
                        authority=mapping.authority,
                    )
                )
        return mapping_count, {k: money(v) for k, v in pool_contributions.items()}, rows

    def compute_pool_allocations(
        self, session: Session, pool_contributions: dict[int, Decimal], fiscal_year: int
    ) -> list[PoolComputation]:
        result: list[PoolComputation] = []
        for pool_id in sorted(pool_contributions):
            pool = session.get(FundingPool, pool_id)
            if pool is None:
                continue
            contribution = money(pool_contributions[pool_id])
            rule = session.scalar(
                select(PoolSpendRule).where(
                    PoolSpendRule.funding_pool_id == pool.id,
                    PoolSpendRule.effective_start_year <= fiscal_year,
                    or_(
                        PoolSpendRule.effective_end_year.is_(None),
                        PoolSpendRule.effective_end_year >= fiscal_year,
                    ),
                )
            )
            if rule is None:
                # This should fail visibly rather than default to all federal spending.
                rule = PoolSpendRule(
                    funding_pool_id=pool.id,
                    source_scope="omb_account_outlay",
                    include_subfunction_codes=[],
                    exclude_subfunction_codes=[],
                    relation=AllocationRelation.ALLOCATED,
                    confidence=ConfidenceGrade.NA,
                    effective_start_year=fiscal_year,
                    description="No active pool-spend rule exists.",
                )
                result.append(PoolComputation(pool, rule, contribution, ZERO, []))
                continue

            query = (
                select(SpendFact, BudgetSubfunction, BudgetFunction)
                .outerjoin(BudgetSubfunction, SpendFact.budget_subfunction_id == BudgetSubfunction.id)
                .outerjoin(BudgetFunction, BudgetSubfunction.function_id == BudgetFunction.id)
                .where(
                    SpendFact.fiscal_year == fiscal_year,
                    SpendFact.metric == FinancialMetric.OUTLAY,
                    SpendFact.status == DataStatus.ACTUAL,
                    SpendFact.record_scope == rule.source_scope,
                )
                .order_by(SpendFact.id)
            )
            candidates = list(session.execute(query).all())
            eligible = [row for row in candidates if _eligible(row[1], row[2], rule)]
            denominator = sum((Decimal(row[0].amount) for row in eligible), ZERO)
            allocations: list[AllocatedFact] = []
            if eligible and denominator != ZERO and contribution != ZERO:
                raw = [contribution * Decimal(row[0].amount) / denominator for row in eligible]
                parts = _reconcile_parts(contribution, raw)
                for (fact, subfunction, function), amount in zip(eligible, parts, strict=True):
                    allocations.append(
                        AllocatedFact(pool, rule, fact, amount, denominator, subfunction, function)
                    )
            result.append(PoolComputation(pool, rule, contribution, denominator, allocations))
        return result

    def _pool_receipt(self, session: Session, computation: PoolComputation) -> PoolReceipt:
        if not computation.allocations:
            node = ReceiptNode(
                key=f"pool:{computation.pool.code}:unallocated",
                label=f"{computation.pool.name} — expenditure detail unavailable",
                node_type="unallocated_detail",
                allocated_amount=computation.contribution,
                government_spending_amount=None,
                share_of_pool_spending=None,
                relation=computation.rule.relation,
                confidence=ConfidenceGrade.NA,
                allocation_status="UNALLOCATED_DETAIL",
                provenance=[
                    NodeProvenance(
                        formula="Tax contribution preserved because no eligible actual outlay facts matched the active pool-spend rule.",
                        pool_code=computation.pool.code,
                        pool_name=computation.pool.name,
                        rule_description=computation.rule.description,
                        source_snapshots=[],
                    )
                ],
            )
            return PoolReceipt(
                code=computation.pool.code,
                name=computation.pool.name,
                contribution=computation.contribution,
                eligible_government_spending=ZERO,
                relation=computation.rule.relation,
                confidence=ConfidenceGrade.NA,
                allocation_status="UNALLOCATED_DETAIL",
                nodes=[node],
                rule_description=computation.rule.description,
            )

        grouped = self._group_allocations(session, computation.allocations, "function")
        return PoolReceipt(
            code=computation.pool.code,
            name=computation.pool.name,
            contribution=computation.contribution,
            eligible_government_spending=money(computation.denominator),
            relation=computation.rule.relation,
            confidence=computation.rule.confidence,
            allocation_status="ALLOCATED",
            nodes=grouped,
            rule_description=computation.rule.description,
        )

    def _aggregate_purpose(self, session: Session, computations: list[PoolComputation]) -> list[ReceiptNode]:
        all_allocations = [a for c in computations for a in c.allocations]
        nodes = self._group_allocations(session, all_allocations, "function")
        # Preserve pools with unavailable spending detail in the complete additive receipt.
        for c in computations:
            if not c.allocations and c.contribution != ZERO:
                nodes.append(
                    ReceiptNode(
                        key=f"purpose:unallocated:{c.pool.code}",
                        label=f"{c.pool.name} — detail unavailable",
                        node_type="unallocated_detail",
                        allocated_amount=c.contribution,
                        relation=c.rule.relation,
                        confidence=ConfidenceGrade.NA,
                        allocation_status="UNALLOCATED_DETAIL",
                        provenance=[
                            NodeProvenance(
                                formula="Preserved financing-pool contribution; no matching actual OMB outlay detail was available.",
                                pool_code=c.pool.code,
                                pool_name=c.pool.name,
                                rule_description=c.rule.description,
                            )
                        ],
                    )
                )
        return sorted(nodes, key=lambda n: (-abs(n.allocated_amount), n.label))

    def _group_allocations(
        self, session: Session, allocations: list[AllocatedFact], dimension: str
    ) -> list[ReceiptNode]:
        buckets: dict[str, list[AllocatedFact]] = defaultdict(list)
        labels: dict[str, tuple[str, str]] = {}
        for a in allocations:
            if dimension == "function":
                code = a.function.native_code if a.function else "999"
                name = a.function.name if a.function else "Other / Unclassified"
                key = f"function:{code}"
                labels[key] = (name, "budget_function")
            elif dimension == "subfunction":
                code = a.subfunction.native_code if a.subfunction else "unknown"
                name = a.subfunction.name if a.subfunction else "Unclassified subfunction"
                key = f"subfunction:{code}"
                labels[key] = (name, "budget_subfunction")
            else:
                raise ValueError(f"Unsupported grouping dimension {dimension}")
            buckets[key].append(a)

        nodes: list[ReceiptNode] = []
        for key, rows in buckets.items():
            allocated = money(sum((r.allocated_amount for r in rows), ZERO))
            # A single government spend fact can legitimately receive allocations from more than
            # one financing pool (for example OASI and DI may both map to a broad Social Security
            # public-reporting fact). User dollars should sum across pools, but the government
            # spending base itself must be counted only once in a cross-pool view.
            unique_facts = {r.fact.id: Decimal(r.fact.amount) for r in rows}
            gov = money(sum(unique_facts.values(), ZERO))
            relations = [r.rule.relation for r in rows]
            relation = AllocationRelation.ALLOCATED if AllocationRelation.ALLOCATED in relations else relations[0]
            confidences = [r.rule.confidence for r in rows]
            provenance = _provenance_for_rows(session, rows)
            # Multiple pools can contribute to one purpose. A single share is only meaningful when
            # the node came from one pool; otherwise leave it null rather than inventing a ratio.
            pool_ids = {r.pool.id for r in rows}
            share = None
            if len(pool_ids) == 1:
                denom = rows[0].denominator
                if denom != ZERO:
                    share = Decimal(gov) / Decimal(denom)
            label, node_type = labels[key]
            mixed_funding = len(pool_ids) > 1
            if mixed_funding:
                for item in provenance:
                    item.notes.append(
                        "MIXED-FUNDING: this public spending category receives attributed contributions from multiple financing pools; the source split is not fully separable at this reporting grain."
                    )
            nodes.append(
                ReceiptNode(
                    key=key,
                    label=label,
                    node_type=node_type,
                    allocated_amount=allocated,
                    government_spending_amount=gov,
                    share_of_pool_spending=share,
                    relation=relation,
                    confidence=worst_confidence(confidences),
                    allocation_status="MIXED_FUNDING" if mixed_funding else "ALLOCATED",
                    provenance=provenance,
                )
            )
        return sorted(nodes, key=lambda n: (-abs(n.allocated_amount), n.label))


def _eligible(subfunction: BudgetSubfunction | None, function: BudgetFunction | None, rule: PoolSpendRule) -> bool:
    codes = {
        str(subfunction.native_code).zfill(3) if subfunction and subfunction.native_code else None,
        str(function.native_code).zfill(3) if function and function.native_code else None,
    }
    codes.discard(None)
    include = {str(v).zfill(3) for v in (rule.include_subfunction_codes or [])}
    exclude = {str(v).zfill(3) for v in (rule.exclude_subfunction_codes or [])}
    if include and not (codes & include):
        return False
    if exclude and (codes & exclude):
        return False
    return True


def _reconcile_parts(total: Decimal, raw_parts: list[Decimal]) -> list[Decimal]:
    """Largest-remainder cent rounding with exact conservation and stable tie-breaking.

    Rounding must not depend on source row order by assigning the entire residual to the final
    category. We floor each exact share to cents, then distribute the remaining cents to the
    largest fractional remainders. The original index is used only as a deterministic tie-breaker.
    The method also behaves correctly for negative net-outlay facts.
    """
    if not raw_parts:
        return []
    target_cents = int((money(total) * 100).to_integral_value())
    exact_cents = [Decimal(v) * 100 for v in raw_parts]
    base = [int(v.to_integral_value(rounding=ROUND_FLOOR)) for v in exact_cents]
    remainders = [v - Decimal(b) for v, b in zip(exact_cents, base, strict=True)]
    difference = target_cents - sum(base)

    if difference > 0:
        order = sorted(range(len(base)), key=lambda i: (-remainders[i], i))
        for n in range(difference):
            base[order[n % len(order)]] += 1
    elif difference < 0:
        order = sorted(range(len(base)), key=lambda i: (remainders[i], i))
        for n in range(-difference):
            base[order[n % len(order)]] -= 1

    return [Decimal(cents) / Decimal(100) for cents in base]


def _source_reference(snapshot: SourceSnapshot) -> SourceReference:
    return SourceReference(
        id=snapshot.id,
        name=snapshot.source_name,
        url=snapshot.source_url,
        reference_period=snapshot.reference_period,
        retrieved_at=snapshot.retrieved_at.isoformat() if snapshot.retrieved_at else None,
        parser_version=snapshot.parser_version,
    )


def _provenance_for_rows(session: Session, rows: list[AllocatedFact]) -> list[NodeProvenance]:
    grouped: dict[tuple[int, int], list[AllocatedFact]] = defaultdict(list)
    for row in rows:
        grouped[(row.pool.id, row.fact.source_snapshot_id)].append(row)
    result: list[NodeProvenance] = []
    for (_, snapshot_id), group in grouped.items():
        snapshot = session.get(SourceSnapshot, snapshot_id)
        first = group[0]
        result.append(
            NodeProvenance(
                formula="pool contribution × (eligible category actual outlays / total eligible pool actual outlays)",
                pool_code=first.pool.code,
                pool_name=first.pool.name,
                rule_description=first.rule.description,
                source_snapshots=[_source_reference(snapshot)] if snapshot else [],
                notes=[
                    "General-revenue allocations are analytical proportional attributions, not literal dollar tracing."
                    if first.rule.relation == AllocationRelation.ALLOCATED
                    else "Dedicated financing is restricted to the pool before proportional distribution across eligible actual outlays."
                ],
            )
        )
    return result
