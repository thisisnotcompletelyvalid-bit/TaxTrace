from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from taxtrace.allocation.engine import (
    FederalAllocationEngine,
    _reconcile_parts,
    _source_reference,
    money,
    worst_confidence,
)
from taxtrace.allocation.models import FederalReceiptRequest, SourceReference
from taxtrace.db_models import (
    Agency,
    Award,
    AwardAccountLink,
    FederalAccount,
    ObjectClass,
    ProgramActivity,
    SourceSnapshot,
    SpendFact,
)
from taxtrace.enums import AllocationRelation, ConfidenceGrade, FinancialMetric, SourceKind
from taxtrace.tax.models import FederalTaxInput

ZERO = Decimal("0")


class ExplorerView(StrEnum):
    PURPOSE = "purpose"
    AGENCY = "agency"
    ACCOUNT = "account"
    PROGRAM_ACTIVITY = "program_activity"
    OBJECT_CLASS = "object_class"
    AWARD = "award"


class FederalExplorerRequest(FederalReceiptRequest):
    view: ExplorerView
    parent_type: str | None = None
    parent_key: str | None = None


class ExplorerNode(BaseModel):
    key: str
    label: str
    node_type: str
    allocated_amount: Decimal
    government_amount: Decimal | None = None
    relation: AllocationRelation
    confidence: ConfidenceGrade
    additive: bool = True
    method: str
    source_snapshot_ids: list[int] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)
    drilldown_views: list[ExplorerView] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ExplorerResult(BaseModel):
    view: ExplorerView
    parent_type: str | None
    parent_key: str | None
    scope_amount: Decimal
    nodes: list[ExplorerNode]
    conservation_difference: Decimal
    additive_within_view: bool = True
    warnings: list[str] = Field(default_factory=list)


class FederalExplorer:
    def __init__(self, allocation_engine: FederalAllocationEngine | None = None):
        self.allocation_engine = allocation_engine or FederalAllocationEngine()

    def explore(self, session: Session, request: FederalExplorerRequest) -> ExplorerResult:
        tax_input = FederalTaxInput(**request.model_dump(exclude={"spending_fiscal_year", "view", "parent_type", "parent_key"}))
        tax_result = self.allocation_engine.tax_engine.calculate(tax_input)
        components = {
            "FED_INCOME_TAX": tax_result.federal_income_tax_liability,
            "SS_EMPLOYEE": tax_result.social_security_tax,
            "MEDICARE_EMPLOYEE": tax_result.medicare_tax,
            "ADDITIONAL_MEDICARE": tax_result.additional_medicare_tax,
        }
        _, pool_contributions, _ = self.allocation_engine._map_revenue_to_pools(
            session, components, request.tax_year
        )
        computations = self.allocation_engine.compute_pool_allocations(
            session, pool_contributions, request.spending_fiscal_year
        )
        allocations = [a for c in computations for a in c.allocations]
        unallocated = sum((c.contribution for c in computations if not c.allocations), ZERO)

        filtered = self._filter_parent(session, allocations, request.parent_type, request.parent_key)
        if request.parent_type or request.parent_key:
            scope_amount = money(sum((a.allocated_amount for a in filtered), ZERO))
        else:
            scope_amount = money(sum((c.contribution for c in computations), ZERO))

        warnings: list[str] = []
        if request.view == ExplorerView.PURPOSE:
            nodes = self._purpose(session, filtered, request)
        elif request.view == ExplorerView.AGENCY:
            nodes = self._agency(session, filtered)
        elif request.view == ExplorerView.ACCOUNT:
            nodes = self._account(session, filtered)
        elif request.view == ExplorerView.PROGRAM_ACTIVITY:
            nodes = self._program_activity(session, filtered, request.spending_fiscal_year)
            warnings.append(
                "Program-activity detail uses USAspending account data where it can be crosswalked to an OMB federal account; unmatched receipt dollars remain explicit residuals."
            )
        elif request.view == ExplorerView.OBJECT_CLASS:
            nodes = self._object_class(session, filtered, request.spending_fiscal_year)
            warnings.append(
                "Object-class detail is a separate USAspending classification. It is additive within this view but must not be added to agency/purpose/account totals from another view."
            )
        elif request.view == ExplorerView.AWARD:
            nodes = self._awards(session, filtered, request.spending_fiscal_year)
            warnings.append(
                "Awards are an overlapping detail view. Award-reported amounts are used to distribute only the crosswalked parent receipt amount; non-award or unmatched spending remains residual."
            )
        else:
            raise ValueError(f"Unsupported explorer view {request.view}")

        # At the root, pool-level detail unavailable cannot be assigned to dimensions; keep it visible.
        if not request.parent_type and unallocated and request.view in {
            ExplorerView.PURPOSE,
            ExplorerView.AGENCY,
            ExplorerView.ACCOUNT,
        }:
            nodes.append(
                ExplorerNode(
                    key="residual:pool-detail-unavailable",
                    label="Financing-pool expenditure detail unavailable",
                    node_type="residual",
                    allocated_amount=money(unallocated),
                    relation=AllocationRelation.DIRECT,
                    confidence=ConfidenceGrade.NA,
                    method="UNALLOCATED_DETAIL",
                    notes=["Preserves dedicated tax contributions whose matching actual expenditure facts are unavailable."],
                )
            )

        node_total = money(sum((n.allocated_amount for n in nodes), ZERO))
        diff = money(scope_amount - node_total)
        if diff != ZERO:
            nodes.append(
                ExplorerNode(
                    key=f"residual:{request.view}",
                    label="No supported detail in this view",
                    node_type="residual",
                    allocated_amount=diff,
                    relation=AllocationRelation.ALLOCATED,
                    confidence=ConfidenceGrade.NA,
                    method="RESIDUAL",
                    notes=["This amount is intentionally retained so the view conserves its parent receipt amount."],
                )
            )
            node_total = money(node_total + diff)
        return ExplorerResult(
            view=request.view,
            parent_type=request.parent_type,
            parent_key=request.parent_key,
            scope_amount=scope_amount,
            nodes=sorted(nodes, key=lambda n: (-abs(n.allocated_amount), n.label)),
            conservation_difference=money(scope_amount - node_total),
            warnings=warnings,
        )

    def _filter_parent(self, session, allocations, parent_type, parent_key):
        if not parent_type and not parent_key:
            return allocations
        if not parent_type or not parent_key:
            raise ValueError("parent_type and parent_key must be supplied together")
        if parent_type == "budget_function":
            code = parent_key.split(":")[-1]
            return [a for a in allocations if a.function and a.function.native_code == code]
        if parent_type == "budget_subfunction":
            code = parent_key.split(":")[-1]
            return [a for a in allocations if a.subfunction and a.subfunction.native_code == code]
        if parent_type == "agency":
            native = parent_key.split(":")[-1]
            ids = set(session.scalars(select(Agency.id).where(Agency.native_code == native)).all())
            return [a for a in allocations if a.fact.agency_id in ids]
        if parent_type == "federal_account":
            native = parent_key.split(":", 1)[-1]
            ids = set(session.scalars(select(FederalAccount.id).where(FederalAccount.native_code == native)).all())
            return [a for a in allocations if a.fact.federal_account_id in ids]
        raise ValueError(f"Unsupported parent_type {parent_type}")

    def _purpose(self, session: Session, allocations, request):
        dimension = "subfunction" if request.parent_type == "budget_function" else "function"
        rows = self.allocation_engine._group_allocations(session, allocations, dimension)
        return [
            ExplorerNode(
                key=n.key,
                label=n.label,
                node_type=n.node_type,
                allocated_amount=n.allocated_amount,
                government_amount=n.government_spending_amount,
                relation=n.relation,
                confidence=n.confidence,
                method="OMB_ACTUAL_OUTLAY_PROPORTIONAL",
                source_snapshot_ids=sorted({s.id for p in n.provenance for s in p.source_snapshots}),
                sources=_dedupe_source_refs([s for p in n.provenance for s in p.source_snapshots]),
                drilldown_views=[ExplorerView.PURPOSE, ExplorerView.AGENCY, ExplorerView.ACCOUNT]
                if n.node_type == "budget_function"
                else [ExplorerView.AGENCY, ExplorerView.ACCOUNT],
            )
            for n in rows
        ]

    def _agency(self, session: Session, allocations):
        buckets = defaultdict(list)
        for a in allocations:
            buckets[a.fact.agency_id].append(a)
        nodes=[]
        for agency_id, rows in buckets.items():
            agency=session.get(Agency, agency_id) if agency_id else None
            if not agency:
                continue
            nodes.append(self._omb_bucket_node(
                session, f"agency:{agency.native_code}", agency.name, "agency", rows,
                [ExplorerView.ACCOUNT, ExplorerView.PROGRAM_ACTIVITY, ExplorerView.OBJECT_CLASS, ExplorerView.AWARD]
            ))
        return nodes

    def _account(self, session: Session, allocations):
        buckets=defaultdict(list)
        for a in allocations:
            buckets[a.fact.federal_account_id].append(a)
        nodes=[]
        for account_id, rows in buckets.items():
            account=session.get(FederalAccount, account_id) if account_id else None
            if not account:
                continue
            nodes.append(self._omb_bucket_node(
                session, f"federal_account:{account.native_code}", account.name, "federal_account", rows,
                [ExplorerView.PROGRAM_ACTIVITY, ExplorerView.AWARD]
            ))
        return nodes

    def _omb_bucket_node(self, session, key, label, node_type, rows, drilldowns):
        amount=money(sum((r.allocated_amount for r in rows),ZERO))
        unique_facts={r.fact.id: Decimal(r.fact.amount) for r in rows}
        gov=money(sum(unique_facts.values(),ZERO))
        relation=AllocationRelation.ALLOCATED if any(r.rule.relation==AllocationRelation.ALLOCATED for r in rows) else AllocationRelation.DIRECT
        return ExplorerNode(
            key=key,label=label,node_type=node_type,allocated_amount=amount,government_amount=gov,
            relation=relation,confidence=worst_confidence([r.rule.confidence for r in rows]),
            method="OMB_ACTUAL_OUTLAY_PROPORTIONAL",source_snapshot_ids=sorted({r.fact.source_snapshot_id for r in rows}),
            sources=_source_refs(session, {r.fact.source_snapshot_id for r in rows}),
            drilldown_views=drilldowns,
        )

    def _program_activity(self, session: Session, allocations, fiscal_year: int):
        # Crosswalk exact federal-account codes across OMB and USAspending.
        by_native=defaultdict(list)
        for a in allocations:
            if a.fact.federal_account_id:
                account=session.get(FederalAccount,a.fact.federal_account_id)
                if account:
                    by_native[account.native_code].append(a)
        nodes=[]
        covered=ZERO
        for native, parent_rows in by_native.items():
            parent_amount=money(sum((r.allocated_amount for r in parent_rows),ZERO))
            us_accounts=session.scalars(select(FederalAccount).where(FederalAccount.source_kind==SourceKind.USASPENDING,FederalAccount.native_code==native)).all()
            ids=[a.id for a in us_accounts]
            if not ids:
                continue
            facts=session.scalars(select(SpendFact).where(
                SpendFact.fiscal_year==fiscal_year,SpendFact.metric==FinancialMetric.OUTLAY,
                SpendFact.record_scope=="usaspending_account_program_activity",SpendFact.federal_account_id.in_(ids)
            )).all()
            facts=[f for f in facts if Decimal(f.amount)>0]
            total=sum((Decimal(f.amount) for f in facts),ZERO)
            if not facts or total<=0:
                continue
            parts=_distribute(parent_amount,[Decimal(f.amount) for f in facts])
            covered += parent_amount
            for fact,part in zip(facts,parts,strict=True):
                pa=session.get(ProgramActivity,fact.program_activity_id) if fact.program_activity_id else None
                nodes.append(ExplorerNode(
                    key=f"program_activity:{native}:{pa.native_code if pa else fact.id}",
                    label=pa.name if pa else "Program activity",
                    node_type="program_activity",allocated_amount=part,government_amount=money(Decimal(fact.amount)),
                    relation=AllocationRelation.ALLOCATED,confidence=ConfidenceGrade.C,
                    method="ACCOUNT_CROSSWALK_USASPENDING_OUTLAY_SHARE",source_snapshot_ids=[fact.source_snapshot_id],
                    sources=_source_refs(session, {fact.source_snapshot_id}),
                    notes=[f"Crosswalked exactly by federal account code {native}; program-activity shares come from USAspending."],
                ))
        scope=money(sum((a.allocated_amount for a in allocations),ZERO))
        residual=money(scope-covered)
        if residual:
            nodes.append(_residual_node("program_activity",residual,"No account-linked USAspending program-activity detail"))
        return nodes

    def _object_class(self, session: Session, allocations, fiscal_year: int):
        # Crosswalk by agency native code or normalized name; then distribute each OMB agency receipt
        # across that agency's object-class outlay dimension.
        by_agency=defaultdict(list)
        for a in allocations:
            by_agency[a.fact.agency_id].append(a)
        nodes=[]; covered=ZERO
        for agency_id,parent_rows in by_agency.items():
            omb=session.get(Agency,agency_id) if agency_id else None
            if not omb: continue
            candidates=session.scalars(select(Agency).where(Agency.source_kind==SourceKind.USASPENDING)).all()
            usa=next((x for x in candidates if x.native_code==omb.native_code),None) or next((x for x in candidates if _norm(x.name)==_norm(omb.name)),None)
            if not usa: continue
            facts=session.scalars(select(SpendFact).where(
                SpendFact.fiscal_year==fiscal_year,SpendFact.metric==FinancialMetric.OUTLAY,
                SpendFact.record_scope=="usaspending_object_class",SpendFact.agency_id==usa.id
            )).all()
            facts=[f for f in facts if Decimal(f.amount)>0]
            total=sum((Decimal(f.amount) for f in facts),ZERO)
            if not facts or total<=0: continue
            parent=money(sum((r.allocated_amount for r in parent_rows),ZERO)); covered += parent
            parts=_distribute(parent,[Decimal(f.amount) for f in facts])
            for fact,part in zip(facts,parts,strict=True):
                obj=session.get(ObjectClass,fact.object_class_id) if fact.object_class_id else None
                nodes.append(ExplorerNode(
                    key=f"object_class:{usa.native_code}:{obj.native_code if obj else fact.id}",label=obj.name if obj else "Object class",
                    node_type="object_class",allocated_amount=part,government_amount=money(Decimal(fact.amount)),
                    relation=AllocationRelation.ALLOCATED,confidence=ConfidenceGrade.C,method="AGENCY_CROSSWALK_USASPENDING_OUTLAY_SHARE",
                    source_snapshot_ids=[fact.source_snapshot_id],sources=_source_refs(session, {fact.source_snapshot_id}),
                    notes=[f"Crosswalked from OMB agency {omb.name} to USAspending agency {usa.name}."],
                ))
        scope=money(sum((a.allocated_amount for a in allocations),ZERO)); residual=money(scope-covered)
        if residual: nodes.append(_residual_node("object_class",residual,"No crosswalked USAspending object-class detail"))
        return nodes

    def _awards(self, session: Session, allocations, fiscal_year: int):
        by_native=defaultdict(list)
        for a in allocations:
            if a.fact.federal_account_id:
                account=session.get(FederalAccount,a.fact.federal_account_id)
                if account: by_native[account.native_code].append(a)
        nodes=[]; covered=ZERO
        for native,parent_rows in by_native.items():
            us_accounts=session.scalars(select(FederalAccount).where(FederalAccount.source_kind==SourceKind.USASPENDING,FederalAccount.native_code==native)).all()
            ids=[a.id for a in us_accounts]
            if not ids: continue
            pairs=session.execute(
                select(Award, AwardAccountLink).join(AwardAccountLink,Award.id==AwardAccountLink.award_id).where(
                    Award.fiscal_year==fiscal_year,AwardAccountLink.federal_account_id.in_(ids)
                )
            ).all()
            weighted=[]
            for award,link in pairs:
                # The explorer is an OUTLAY view. Do not silently substitute award value or
                # obligations when USAspending does not report award outlays. Those dollars remain
                # in the explicit residual instead.
                value = award.outlay_amount if award.outlay_amount is not None else link.amount
                if value is not None and Decimal(value)>0:
                    weighted.append((award,Decimal(value)))
            if not weighted: continue
            parent=money(sum((r.allocated_amount for r in parent_rows),ZERO)); covered += parent
            parts=_distribute(parent,[v for _,v in weighted])
            for (award,value),part in zip(weighted,parts,strict=True):
                recipient=session.get(__import__('taxtrace.db_models',fromlist=['Recipient']).Recipient,award.recipient_id) if award.recipient_id else None
                label=f"{award.native_id} — {award.description or (recipient.name if recipient else 'Award')}"
                nodes.append(ExplorerNode(
                    key=f"award:{award.native_id}",label=label,node_type="award",allocated_amount=part,government_amount=money(value),
                    relation=AllocationRelation.ALLOCATED,confidence=ConfidenceGrade.C,method="ACCOUNT_CROSSWALK_AWARD_REPORTED_SHARE",
                    source_snapshot_ids=[award.source_snapshot_id],sources=_source_refs(session, {award.source_snapshot_id}),additive=True,
                    notes=[f"Recipient: {recipient.name}" if recipient else "Recipient unavailable",f"Crosswalked by federal account code {native}."],
                ))
        scope=money(sum((a.allocated_amount for a in allocations),ZERO)); residual=money(scope-covered)
        if residual: nodes.append(_residual_node("award",residual,"Non-award spending or no account-linked award detail"))
        return nodes


def _distribute(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    denom=sum(weights,ZERO)
    if not weights or denom<=0:
        return []
    raw=[total*w/denom for w in weights]
    return _reconcile_parts(total, raw)


def _residual_node(kind: str, amount: Decimal, label: str) -> ExplorerNode:
    return ExplorerNode(
        key=f"residual:{kind}",label=label,node_type="residual",allocated_amount=money(amount),
        relation=AllocationRelation.ALLOCATED,confidence=ConfidenceGrade.NA,method="RESIDUAL",
        notes=["Residual preserves conservation and must not be interpreted as a known program/object/award."],
    )


def _source_refs(session: Session, ids: set[int]) -> list[SourceReference]:
    refs=[]
    for snapshot_id in sorted(ids):
        snapshot=session.get(SourceSnapshot,snapshot_id)
        if snapshot is not None:
            refs.append(_source_reference(snapshot))
    return refs


def _dedupe_source_refs(refs: list[SourceReference]) -> list[SourceReference]:
    by_id={ref.id: ref for ref in refs}
    return [by_id[key] for key in sorted(by_id)]


def _norm(text: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())
