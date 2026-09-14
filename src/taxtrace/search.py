from __future__ import annotations

from decimal import Decimal
from difflib import SequenceMatcher

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from taxtrace.db_models import (
    Agency,
    Award,
    BudgetFunction,
    BudgetSubfunction,
    CanonicalCategory,
    FederalAccount,
    ObjectClass,
    ProgramActivity,
    Recipient,
    SearchAlias,
    SearchDocument,
    TreasuryAccount,
)

from taxtrace.allocation.models import FederalReceiptRequest
from taxtrace.enums import AllocationRelation, ConfidenceGrade, SourceKind


class SearchResult(BaseModel):
    entity_type: str
    entity_key: str
    title: str
    subtitle: str | None = None
    score: Decimal
    matched_aliases: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    additive: bool = False
    warning: str = "Search results can overlap and should not be summed unless an explorer view explicitly marks them additive."
    attributable_amount: Decimal | None = None
    government_amount: Decimal | None = None
    relation: AllocationRelation | None = None
    confidence: ConfidenceGrade | None = None
    attribution_note: str | None = None
    suggested_view: str | None = None
    parent_type: str | None = None
    parent_key: str | None = None


class SearchResponse(BaseModel):
    query: str
    normalized_query: str
    results: list[SearchResult]
    index_documents: int
    receipt_context: bool = False
    warnings: list[str] = Field(default_factory=list)


class FederalSearchRequest(FederalReceiptRequest):
    q: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=20, ge=1, le=100)


def normalize(text: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())


def rebuild_search_index(session: Session) -> int:
    """Rebuild the portable Phase-6 search index from normalized warehouse entities.

    PostgreSQL full-text/OpenSearch can replace the ranking implementation later without changing
    the public search contract. This first index is intentionally SQLite-compatible so the entire
    product remains runnable without Docker.
    """
    session.execute(delete(SearchDocument))
    session.execute(delete(SearchAlias))
    _ensure_canonical_categories(session)
    session.flush()

    docs: list[SearchDocument] = []

    for obj in session.scalars(select(Agency)).all():
        key=f"{obj.source_kind.value}:{obj.native_code}"
        docs.append(_doc("agency",key,obj.name,obj.abbreviation or obj.native_code,"",None,{"native_code":obj.native_code,"source_kind":obj.source_kind.value}))
        if obj.abbreviation:
            _alias(session,"agency",key,obj.abbreviation,"automatic")

    for obj in session.scalars(select(FederalAccount)).all():
        agency=session.get(Agency,obj.agency_id) if obj.agency_id else None
        key=f"{obj.source_kind.value}:{obj.native_code}"
        docs.append(_doc("federal_account",key,obj.name,agency.name if agency else obj.native_code,"",None,{"native_code":obj.native_code,"agency":agency.name if agency else None,"source_kind":obj.source_kind.value}))

    for obj in session.scalars(select(TreasuryAccount)).all():
        docs.append(_doc("treasury_account",obj.tas,obj.name,obj.tas,"",None,{"tas":obj.tas,"source_kind":obj.source_kind.value}))

    for obj in session.scalars(select(ProgramActivity)).all():
        agency=session.get(Agency,obj.agency_id) if obj.agency_id else None
        key=f"{obj.source_kind.value}:{obj.agency_id or 0}:{obj.native_code or normalize(obj.name)}"
        docs.append(_doc("program_activity",key,obj.name,agency.name if agency else obj.native_code or None,"",None,{"native_code":obj.native_code,"agency":agency.name if agency else None,"source_kind":obj.source_kind.value}))

    for obj in session.scalars(select(ObjectClass)).all():
        agency=session.get(Agency,obj.agency_id) if obj.agency_id else None
        key=f"{obj.source_kind.value}:{obj.agency_id or 0}:{obj.native_code or normalize(obj.name)}"
        docs.append(_doc("object_class",key,obj.name,agency.name if agency else obj.native_code or None,"",None,{"native_code":obj.native_code,"agency":agency.name if agency else None,"source_kind":obj.source_kind.value}))

    for obj in session.scalars(select(BudgetFunction)).all():
        key=f"{obj.source_kind.value}:{obj.native_code or normalize(obj.name)}"
        docs.append(_doc("budget_function",key,obj.name,obj.native_code or None,"",None,{"native_code":obj.native_code,"source_kind":obj.source_kind.value}))

    for obj in session.scalars(select(BudgetSubfunction)).all():
        function=session.get(BudgetFunction,obj.function_id) if obj.function_id else None
        key=f"{obj.source_kind.value}:{obj.native_code or normalize(obj.name)}"
        docs.append(_doc("budget_subfunction",key,obj.name,function.name if function else obj.native_code or None,"",None,{"native_code":obj.native_code,"function":function.name if function else None,"source_kind":obj.source_kind.value}))

    for obj in session.scalars(select(Award)).all():
        recipient=session.get(Recipient,obj.recipient_id) if obj.recipient_id else None
        subtitle=recipient.name if recipient else obj.award_type
        docs.append(_doc("award",obj.native_id,obj.native_id,subtitle,obj.description,obj.fiscal_year,{"description":obj.description,"award_type":obj.award_type,"amount":str(obj.amount) if obj.amount is not None else None,"outlay_amount":str(obj.outlay_amount) if obj.outlay_amount is not None else None,"recipient":recipient.name if recipient else None}))

    for obj in session.scalars(select(Recipient)).all():
        docs.append(_doc("recipient",obj.native_id,obj.name,obj.uei,"",None,{"uei":obj.uei,"source_kind":obj.source_kind.value}))

    for obj in session.scalars(select(CanonicalCategory)).all():
        docs.append(_doc("canonical_category",obj.code,obj.name,"Standardized TaxTrace category",obj.description,None,{"code":obj.code}))

    session.add_all(docs)
    session.flush()
    _seed_manual_aliases(session)
    session.commit()
    return len(docs)


def search(session: Session, query: str, *, limit: int = 20, entity_types: list[str] | None = None) -> SearchResponse:
    q=normalize(query)
    if not q:
        return SearchResponse(query=query,normalized_query=q,results=[],index_documents=0)
    count=session.scalar(select(func.count(SearchDocument.id))) or 0
    if count == 0:
        count=rebuild_search_index(session)

    docs=session.scalars(select(SearchDocument)).all()
    if entity_types:
        allowed=set(entity_types)
        docs=[d for d in docs if d.entity_type in allowed]
    aliases=session.scalars(select(SearchAlias)).all()
    by_entity: dict[tuple[str,str],list[SearchAlias]]={}
    for a in aliases:
        by_entity.setdefault((a.entity_type,a.entity_key),[]).append(a)

    results=[]
    q_tokens=q.split()
    for d in docs:
        title=normalize(d.title)
        body=normalize(d.body)
        subtitle=normalize(d.subtitle or "")
        alias_rows=by_entity.get((d.entity_type,d.entity_key),[])
        alias_norm=[a.normalized_alias for a in alias_rows]
        score=0.0
        matched=[]
        if title == q: score=max(score,100.0)
        elif title.startswith(q): score=max(score,82.0)
        elif q in title: score=max(score,70.0)
        if q in subtitle: score=max(score,55.0)
        if q in body: score=max(score,48.0)
        for a in alias_rows:
            if a.normalized_alias == q:
                score=max(score,96.0); matched.append(a.alias)
            elif q in a.normalized_alias or a.normalized_alias in q:
                score=max(score,72.0); matched.append(a.alias)
        hay=" ".join([title,subtitle,body,*alias_norm])
        token_hits=sum(1 for t in q_tokens if t in hay)
        if q_tokens:
            score=max(score,40.0*token_hits/len(q_tokens))
        ratio=SequenceMatcher(None,q,title).ratio()
        score=max(score,ratio*45.0)
        if score < 20:
            continue
        results.append(SearchResult(
            entity_type=d.entity_type,entity_key=d.entity_key,title=d.title,subtitle=d.subtitle,
            score=Decimal(str(round(score,2))),matched_aliases=sorted(set(matched)),metadata=d.metadata_json or {},
        ))
    results.sort(key=lambda r:(-r.score,r.entity_type,r.title.lower()))
    deduped=[]
    seen=set()
    for result in results:
        canonical=(
            result.entity_type,
            normalize(result.title),
            str(result.metadata.get("native_code") or result.metadata.get("uei") or result.entity_key),
        )
        if canonical in seen:
            continue
        seen.add(canonical)
        deduped.append(result)
    return SearchResponse(query=query,normalized_query=q,results=deduped[:max(1,min(limit,100))],index_documents=int(count))



CANONICAL_FUNCTION_CODES = {
    "national_defense": "050",
    "social_security": "650",
    "medicare": "570",
    "income_security": "600",
    "net_interest": "900",
    "justice": "750",
    "science_space": "250",
}


def search_with_receipt(
    session: Session, request: FederalSearchRequest
) -> SearchResponse:
    """Search the index and, where defensible, attach this taxpayer's attributable amount.

    Search remains non-additive: an agency, account, program activity, award, recipient, and
    canonical topic can describe overlapping slices of the same underlying spending. The amount is
    therefore a navigation aid into the audited explorer, never another partition to be summed.
    """
    from taxtrace.explorer import ExplorerView, FederalExplorer, FederalExplorerRequest

    response = search(session, request.q, limit=request.limit)
    explorer = FederalExplorer()
    base = request.model_dump(exclude={"q", "limit"})
    cache: dict[tuple[str, str | None, str | None], object] = {}

    def view(view_name: str, parent_type: str | None = None, parent_key: str | None = None):
        key = (view_name, parent_type, parent_key)
        if key not in cache:
            cache[key] = explorer.explore(
                session,
                FederalExplorerRequest(
                    **base,
                    view=ExplorerView(view_name),
                    parent_type=parent_type,
                    parent_key=parent_key,
                ),
            )
        return cache[key]

    for result in response.results:
        nodes = []
        note = None
        suggested_view = None
        parent_type = None
        parent_key = None
        native_code = str(result.metadata.get("native_code") or "")

        if result.entity_type == "budget_function":
            code = native_code.zfill(3) if native_code else result.entity_key.split(":")[-1].zfill(3)
            nodes = [n for n in view("purpose").nodes if n.key == f"function:{code}"]
            suggested_view, parent_type, parent_key = "agency", "budget_function", f"function:{code}"
        elif result.entity_type == "canonical_category":
            code = CANONICAL_FUNCTION_CODES.get(result.entity_key)
            if code:
                nodes = [n for n in view("purpose").nodes if n.key == f"function:{code}"]
                suggested_view, parent_type, parent_key = "agency", "budget_function", f"function:{code}"
            else:
                note = "This standardized category does not yet have a one-to-one federal budget-function mapping."
        elif result.entity_type == "budget_subfunction":
            source, _, code = result.entity_key.partition(":")
            sub = session.scalar(
                select(BudgetSubfunction).where(
                    BudgetSubfunction.source_kind == SourceKind(source),
                    BudgetSubfunction.native_code == code,
                )
            ) if source in {kind.value for kind in SourceKind} else None
            function = session.get(BudgetFunction, sub.function_id) if sub and sub.function_id else None
            if function and function.native_code:
                parent = f"function:{str(function.native_code).zfill(3)}"
                nodes = [
                    n for n in view("purpose", "budget_function", parent).nodes
                    if n.key == f"subfunction:{str(code).zfill(3)}"
                ]
                suggested_view, parent_type, parent_key = "agency", "budget_subfunction", f"subfunction:{str(code).zfill(3)}"
        elif result.entity_type == "agency":
            code = native_code or result.entity_key.split(":")[-1]
            nodes = [n for n in view("agency").nodes if n.key == f"agency:{code}"]
            suggested_view, parent_type, parent_key = "account", "agency", f"agency:{code}"
        elif result.entity_type == "federal_account":
            code = native_code or result.entity_key.split(":", 1)[-1]
            nodes = [n for n in view("account").nodes if n.key == f"federal_account:{code}"]
            suggested_view, parent_type, parent_key = "program_activity", "federal_account", f"federal_account:{code}"
        elif result.entity_type == "program_activity":
            code = native_code
            parts = result.entity_key.split(":")
            agency = session.get(Agency, int(parts[1])) if len(parts) >= 3 and parts[1].isdigit() else None
            candidates = view("program_activity").nodes
            nodes = [
                n for n in candidates
                if (
                    (not agency or n.key.startswith(f"program_activity:{agency.native_code}-"))
                    and ((code and n.key.endswith(f":{code}")) or n.label.casefold() == result.title.casefold())
                )
            ]
            note = "Same-named program activities can exist under multiple accounts; matching receipt slices within the indexed agency are aggregated here and remain non-additive with other search results."
        elif result.entity_type == "object_class":
            parts = result.entity_key.split(":")
            agency = session.get(Agency, int(parts[1])) if len(parts) >= 3 and parts[1].isdigit() else None
            code = native_code or (parts[-1] if parts else "")
            candidates = view("object_class").nodes
            if agency:
                nodes = [n for n in candidates if n.key == f"object_class:{agency.native_code}:{code}"]
            if not nodes:
                nodes = [n for n in candidates if n.label.casefold() == result.title.casefold()]
        elif result.entity_type == "award":
            nodes = [n for n in view("award").nodes if n.key == f"award:{result.entity_key}"]
        elif result.entity_type == "recipient":
            recipient = session.scalar(
                select(Recipient).where(Recipient.native_id == result.entity_key)
            )
            award_ids = set(
                session.scalars(select(Award.native_id).where(Award.recipient_id == recipient.id)).all()
            ) if recipient else set()
            nodes = [n for n in view("award").nodes if n.key.removeprefix("award:") in award_ids]
            note = "Recipient amount is the sum of account-crosswalked award slices currently indexed for this recipient; it can overlap program, agency, and account results."
        elif result.entity_type == "treasury_account":
            note = "Treasury-account attribution is indexed for discovery, but this release does not infer a receipt share below the parent federal account unless linked program-activity data support it."

        if nodes:
            result.attributable_amount = sum((n.allocated_amount for n in nodes), Decimal("0"))
            gov_values = [n.government_amount for n in nodes if n.government_amount is not None]
            result.government_amount = sum(gov_values, Decimal("0")) if gov_values else None
            result.relation = (
                AllocationRelation.ALLOCATED
                if any(n.relation == AllocationRelation.ALLOCATED for n in nodes)
                else nodes[0].relation
            )
            confidence_rank = {
                ConfidenceGrade.A: 0,
                ConfidenceGrade.B: 1,
                ConfidenceGrade.C: 2,
                ConfidenceGrade.D: 3,
                ConfidenceGrade.NA: 4,
            }
            result.confidence = max((n.confidence for n in nodes), key=confidence_rank.get)
            result.attribution_note = note or "Matched to the current federal receipt/explorer context."
            result.suggested_view = suggested_view
            result.parent_type = parent_type
            result.parent_key = parent_key
        elif note:
            result.attribution_note = note

    response.receipt_context = True
    response.warnings = [
        "Search matches can overlap across agencies, accounts, programs, awards, recipients, and canonical topics. Never sum search results unless an explorer view explicitly marks the rows additive.",
        "An attributable amount is shown only when the indexed entity can be mapped back to the current receipt without inventing unsupported granularity.",
    ]
    return response

def _doc(entity_type,key,title,subtitle,body,fiscal_year,metadata):
    text=" ".join(filter(None,[title,subtitle,body,key]))
    return SearchDocument(entity_type=entity_type,entity_key=str(key),title=str(title),subtitle=subtitle,body=body or "",normalized_text=normalize(text),fiscal_year=fiscal_year,metadata_json=metadata or {})


def _alias(session,entity_type,key,alias,source="manual"):
    normalized=normalize(alias)
    if not normalized:return
    exists=session.scalar(select(SearchAlias).where(SearchAlias.entity_type==entity_type,SearchAlias.entity_key==str(key),SearchAlias.normalized_alias==normalized))
    if exists is None:
        session.add(SearchAlias(entity_type=entity_type,entity_key=str(key),alias=alias,normalized_alias=normalized,source=source))


def _ensure_canonical_categories(session):
    categories={
        "national_defense":("National Defense","Military and national-defense budget function."),
        "social_security":("Social Security","Social Security retirement, survivors, and disability financing/spending."),
        "medicare":("Medicare","Federal Medicare spending, including Hospital Insurance where separately identifiable."),
        "income_security":("Income Security","Income-support and nutrition-assistance programs."),
        "net_interest":("Net Interest","Federal net interest and debt-service spending."),
        "justice":("Administration of Justice","Federal courts, law enforcement, corrections, and justice administration."),
        "science_space":("Science and Space","General science, space, and technology spending."),
    }
    for code,(name,desc) in categories.items():
        obj=session.scalar(select(CanonicalCategory).where(CanonicalCategory.code==code))
        if obj is None: session.add(CanonicalCategory(code=code,name=name,description=desc))


def _seed_manual_aliases(session):
    docs=session.scalars(select(SearchDocument)).all()
    for d in docs:
        n=normalize(d.title)
        if "supplemental nutrition assistance" in n:
            _alias(session,d.entity_type,d.entity_key,"SNAP")
            _alias(session,d.entity_type,d.entity_key,"food stamps")
        if d.entity_type in {"budget_function","canonical_category"} and "national defense" in n:
            _alias(session,d.entity_type,d.entity_key,"military")
            _alias(session,d.entity_type,d.entity_key,"defense")
        if d.entity_type=="agency" and "department of defense" in n:
            _alias(session,d.entity_type,d.entity_key,"DOD")
            _alias(session,d.entity_type,d.entity_key,"Pentagon")
        if "social security" in n:
            _alias(session,d.entity_type,d.entity_key,"SSA")
            _alias(session,d.entity_type,d.entity_key,"retirement benefits")
        if "medicare" in n:
            _alias(session,d.entity_type,d.entity_key,"Medicare Part A")
            _alias(session,d.entity_type,d.entity_key,"Hospital Insurance")
        if "net interest" in n or "interest on treasury debt" in n:
            _alias(session,d.entity_type,d.entity_key,"debt interest")
            _alias(session,d.entity_type,d.entity_key,"interest on the debt")
