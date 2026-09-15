from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from taxtrace.allocation.models import FederalReceiptRequest
from taxtrace.search import normalize
from taxtrace.warehouse_v2.db_models import BulkObject, DatasetDefinition, DatasetRelease
from taxtrace.warehouse_v2.federal_award_detail import AwardDetailCoverage
from taxtrace.warehouse_v2.federal_awards import FederalAwardProjectionEngine
from taxtrace.warehouse_v2.federal_receipt import _ident
from taxtrace.warehouse_v2.lake import LakeStore
from taxtrace.warehouse_v2.usaspending_award_crosswalk import PRIME_DATASET, SUBAWARD_DATASET

ZERO = Decimal("0")
SEARCH_TYPES = {"prime_award", "recipient", "subaward"}


class FederalSearchV2Request(FederalReceiptRequest):
    q: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=20, ge=1, le=100)
    entity_types: list[str] = Field(default_factory=list)


class FederalSearchV2Result(BaseModel):
    entity_type: str
    key: str
    title: str
    subtitle: str | None = None
    score: Decimal
    award_identity: str | None = None
    award_family: str | None = None
    recipient_name: str | None = None
    recipient_uei: str | None = None
    description: str | None = None
    personalized_amount: Decimal | None = None
    prime_personalized_amount: Decimal | None = None
    additive: bool = False
    target_award_identity: str | None = None
    metadata: dict = Field(default_factory=dict)
    warning: str = (
        "Search results are discovery/navigation results over overlapping federal award grains and must not be summed."
    )


class FederalSearchV2Response(BaseModel):
    query: str
    normalized_query: str
    fiscal_year: int
    results: list[FederalSearchV2Result]
    prime_coverage: AwardDetailCoverage
    subaward_coverage: AwardDetailCoverage
    receipt_context: bool = False
    personalization_status: str = "NOT_REQUESTED"
    warnings: list[str] = Field(default_factory=list)


class FederalSearchV2Engine:
    """Search full-year D1/D2 and File F lake objects without creating an additive view.

    D1/D2 transaction rows are collapsed to canonical award identity before they become search
    results. Recipient results are descriptive groupings over those same prime-award identities.
    File F is searched independently and remains downstream, non-additive context. When a receipt
    request is supplied, existing File C personalized award allocations may annotate prime-award
    and recipient results; File F never inherits a personalized amount of its own.
    """

    def __init__(self, lake: LakeStore | None = None):
        self.lake = lake or LakeStore()

    def search(
        self,
        session: Session,
        *,
        fiscal_year: int,
        query: str,
        limit: int = 20,
        entity_types: list[str] | None = None,
        receipt_request: FederalReceiptRequest | None = None,
    ) -> FederalSearchV2Response:
        q = normalize(query)
        if not q:
            raise ValueError("q must contain searchable text")
        requested = set(entity_types or SEARCH_TYPES)
        unknown = requested - SEARCH_TYPES
        if unknown:
            raise ValueError(f"unsupported Warehouse V2 federal search types: {sorted(unknown)}")
        limit = max(1, min(int(limit), 100))

        prime_coverage, prime_objects = self._load_objects(session, PRIME_DATASET, fiscal_year)
        subaward_coverage, subaward_objects = self._load_objects(
            session, SUBAWARD_DATASET, fiscal_year
        )

        results: list[FederalSearchV2Result] = []
        recipient_rows: dict[str, dict] = {}
        candidate_limit = max(25, limit * 6)

        if prime_coverage.status == "READY":
            for data_class, family, key_column in (
                ("D1", "contract", "contract_award_unique_key"),
                ("D2", "assistance", "assistance_award_unique_key"),
            ):
                paths = [
                    self.lake.root / obj.object_key
                    for obj in prime_objects
                    if str((obj.partition_json or {}).get("data_class", "")).upper() == data_class
                ]
                if not paths:
                    continue
                if "prime_award" in requested:
                    for row in _query_prime_search(paths, key_column, family, q, candidate_limit):
                        results.append(_prime_result(q, row))
                if "recipient" in requested:
                    for row in _query_recipient_search(
                        paths, key_column, family, q, candidate_limit
                    ):
                        key = row["recipient_key"]
                        current = recipient_rows.get(key)
                        if current is None:
                            recipient_rows[key] = row
                        else:
                            current["award_count"] += row["award_count"]
                            current["families"].add(family)
                            if not current.get("sample_award_identity"):
                                current["sample_award_identity"] = row.get(
                                    "sample_award_identity"
                                )

        if "recipient" in requested:
            for row in recipient_rows.values():
                results.append(_recipient_result(q, row))

        if subaward_coverage.status == "READY" and "subaward" in requested:
            for family in ("contract", "assistance"):
                paths = [
                    self.lake.root / obj.object_key
                    for obj in subaward_objects
                    if str((obj.partition_json or {}).get("award_family", "")).lower()
                    == family
                ]
                if not paths:
                    continue
                for row in _query_subaward_search(paths, family, q, candidate_limit):
                    results.append(_subaward_result(q, row))

        results = _dedupe_and_rank(results, limit)
        personalization_status = "NOT_REQUESTED"
        warnings: list[str] = []
        if receipt_request is not None:
            projection = FederalAwardProjectionEngine(lake=self.lake).calculate(
                session, receipt_request
            )
            award_amounts: dict[str, Decimal] = defaultdict(lambda: ZERO)
            recipient_uei_amounts: dict[str, Decimal] = defaultdict(lambda: ZERO)
            recipient_name_amounts: dict[str, Decimal] = defaultdict(lambda: ZERO)
            available = False
            for account in projection.accounts:
                available = available or account.projection_available
                for child in account.children:
                    if child.residual or not child.linked or not child.award_identity:
                        continue
                    award_amounts[child.award_identity] += child.allocated_amount
                    if child.recipient_uei:
                        recipient_uei_amounts[child.recipient_uei.casefold()] += child.allocated_amount
                    if child.recipient_name:
                        recipient_name_amounts[normalize(child.recipient_name)] += child.allocated_amount
            personalization_status = "READY" if available else "UNAVAILABLE"
            for result in results:
                if result.entity_type == "prime_award" and result.award_identity:
                    amount = award_amounts.get(result.award_identity)
                    result.personalized_amount = amount if amount not in (None, ZERO) else None
                elif result.entity_type == "recipient":
                    amount = None
                    if result.recipient_uei:
                        value = recipient_uei_amounts.get(result.recipient_uei.casefold(), ZERO)
                        amount = value if value != ZERO else None
                    if amount is None and result.recipient_name:
                        value = recipient_name_amounts.get(normalize(result.recipient_name), ZERO)
                        amount = value if value != ZERO else None
                    result.personalized_amount = amount
                elif result.entity_type == "subaward" and result.award_identity:
                    amount = award_amounts.get(result.award_identity)
                    result.prime_personalized_amount = amount if amount not in (None, ZERO) else None
            warnings.append(
                "Receipt-context amounts come only from the conserved File C award projection. Search ranking and D1/D2/File F monetary fields never create personalized dollars."
            )
            warnings.append(
                "A subaward may show its prime award's personalized amount as context, but File F is not used to allocate that amount to the subaward."
            )

        if prime_coverage.status != "READY":
            warnings.append(
                "Full-year local D1/D2 data are unavailable, so prime-award and recipient search coverage is incomplete."
            )
        if subaward_coverage.status != "READY":
            warnings.append(
                "Full-year local File F data are unavailable, so subaward search coverage is incomplete."
            )
        warnings.append(
            "Warehouse V2 federal search results overlap across prime awards, recipients, and subawards. They are non-additive navigation results."
        )

        return FederalSearchV2Response(
            query=query,
            normalized_query=q,
            fiscal_year=fiscal_year,
            results=results,
            prime_coverage=prime_coverage,
            subaward_coverage=subaward_coverage,
            receipt_context=receipt_request is not None,
            personalization_status=personalization_status,
            warnings=warnings,
        )

    def _load_objects(
        self,
        session: Session,
        dataset_key: str,
        fiscal_year: int,
    ) -> tuple[AwardDetailCoverage, list[BulkObject]]:
        release = session.scalar(
            select(DatasetRelease)
            .join(DatasetDefinition, DatasetDefinition.id == DatasetRelease.dataset_id)
            .where(
                DatasetDefinition.key == dataset_key,
                DatasetRelease.reference_year == fiscal_year,
                DatasetRelease.release_key == f"FY{fiscal_year}",
                DatasetRelease.status == "READY",
                DatasetRelease.coverage_type == "FEDERAL_AWARD",
            )
            .order_by(DatasetRelease.ingested_at.desc(), DatasetRelease.id.desc())
        )
        if release is None:
            return (
                AwardDetailCoverage(
                    dataset_key=dataset_key,
                    fiscal_year=fiscal_year,
                    status="NO_FULL_YEAR_RELEASE",
                    notes=[
                        "No READY full-fiscal-year USAspending award release is registered for this dataset."
                    ],
                ),
                [],
            )
        objects = session.scalars(
            select(BulkObject)
            .where(
                BulkObject.dataset_release_id == release.id,
                BulkObject.layer == "normalized",
                BulkObject.storage_format == "PARQUET",
            )
            .order_by(BulkObject.object_key)
        ).all()
        coverage = AwardDetailCoverage(
            dataset_key=dataset_key,
            release_key=release.release_key,
            fiscal_year=fiscal_year,
            status="READY",
            full_fiscal_year=True,
            row_count=release.row_count,
            object_count=len(objects),
            object_keys=[obj.object_key for obj in objects],
        )
        if not objects:
            coverage.status = "NO_PARQUET_OBJECTS"
            coverage.notes.append("The full-year release has no normalized Parquet objects registered.")
            return coverage, []
        missing = [
            obj.object_key for obj in objects if not (self.lake.root / obj.object_key).exists()
        ]
        if missing:
            coverage.status = "OBJECTS_NOT_LOCAL"
            coverage.notes.append(
                "Release metadata is present but one or more normalized award lake objects are not local to this runtime."
            )
            return coverage, []
        return coverage, list(objects)


def _query_prime_search(
    paths: list[Path],
    key_column: str,
    family: str,
    query: str,
    limit: int,
) -> list[dict]:
    connection, columns = _open_paths(paths)
    try:
        key = columns.get(key_column)
        if key is None:
            raise ValueError(f"{family} prime data are missing canonical key {key_column!r}")
        search_expr = _search_expr(
            columns,
            [
                key_column,
                "award_id_piid",
                "award_id_fain",
                "award_id_uri",
                "recipient_name",
                "recipient_name_raw",
                "recipient_uei",
                "prime_award_base_transaction_description",
                "award_description",
                "transaction_description",
                "awarding_agency_name",
                "funding_agency_name",
                "award_type",
            ],
        )
        conditions, params = _token_conditions(search_expr, query)
        sql = f"""
            SELECT
                nullif(trim(CAST({_ident(key)} AS VARCHAR)), '') AS award_identity,
                {_aggregate_optional(columns, ['award_id_piid'])} AS award_id_piid,
                {_aggregate_optional(columns, ['award_id_fain'])} AS award_id_fain,
                {_aggregate_optional(columns, ['award_id_uri'])} AS award_id_uri,
                {_aggregate_optional(columns, ['recipient_name', 'recipient_name_raw'])} AS recipient_name,
                {_aggregate_optional(columns, ['recipient_uei'])} AS recipient_uei,
                {_aggregate_optional(columns, ['prime_award_base_transaction_description', 'award_description', 'transaction_description'])} AS description,
                {_aggregate_optional(columns, ['awarding_agency_name'])} AS awarding_agency_name,
                {_aggregate_optional(columns, ['funding_agency_name'])} AS funding_agency_name,
                {_aggregate_optional(columns, ['award_type'])} AS award_type,
                count(*) AS transaction_count
            FROM read_parquet(?)
            WHERE nullif(trim(CAST({_ident(key)} AS VARCHAR)), '') IS NOT NULL
              AND {conditions}
            GROUP BY 1
            ORDER BY transaction_count DESC, award_identity
            LIMIT ?
        """
        rows = connection.execute(
            sql, [[str(path) for path in paths], *params, limit]
        ).fetchall()
        return [
            {
                "award_identity": row[0],
                "award_family": family,
                "award_id_piid": row[1],
                "award_id_fain": row[2],
                "award_id_uri": row[3],
                "recipient_name": row[4],
                "recipient_uei": row[5],
                "description": row[6],
                "awarding_agency_name": row[7],
                "funding_agency_name": row[8],
                "award_type": row[9],
                "transaction_count": int(row[10] or 0),
            }
            for row in rows
        ]
    finally:
        connection.close()


def _query_recipient_search(
    paths: list[Path],
    key_column: str,
    family: str,
    query: str,
    limit: int,
) -> list[dict]:
    connection, columns = _open_paths(paths)
    try:
        key = columns.get(key_column)
        if key is None:
            raise ValueError(f"{family} prime data are missing canonical key {key_column!r}")
        name_expr = _plain_optional(columns, ["recipient_name", "recipient_name_raw"])
        uei_expr = _plain_optional(columns, ["recipient_uei"])
        if name_expr == "CAST(NULL AS VARCHAR)" and uei_expr == "CAST(NULL AS VARCHAR)":
            return []
        search_expr = _search_expr(columns, ["recipient_name", "recipient_name_raw", "recipient_uei"])
        conditions, params = _token_conditions(search_expr, query)
        sql = f"""
            SELECT
                {name_expr} AS recipient_name,
                {uei_expr} AS recipient_uei,
                count(DISTINCT nullif(trim(CAST({_ident(key)} AS VARCHAR)), '')) AS award_count,
                min(nullif(trim(CAST({_ident(key)} AS VARCHAR)), '')) AS sample_award_identity
            FROM read_parquet(?)
            WHERE ({name_expr} IS NOT NULL OR {uei_expr} IS NOT NULL)
              AND {conditions}
            GROUP BY 1, 2
            ORDER BY award_count DESC, recipient_name NULLS LAST, recipient_uei NULLS LAST
            LIMIT ?
        """
        rows = connection.execute(
            sql, [[str(path) for path in paths], *params, limit]
        ).fetchall()
        result = []
        for row in rows:
            name, uei = row[0], row[1]
            recipient_key = f"recipient:{(uei or normalize(name or 'unknown')).casefold()}"
            result.append(
                {
                    "recipient_key": recipient_key,
                    "recipient_name": name,
                    "recipient_uei": uei,
                    "award_count": int(row[2] or 0),
                    "sample_award_identity": row[3],
                    "families": {family},
                }
            )
        return result
    finally:
        connection.close()


def _query_subaward_search(
    paths: list[Path],
    family: str,
    query: str,
    limit: int,
) -> list[dict]:
    connection, columns = _open_paths(paths)
    try:
        key = columns.get("prime_award_unique_key")
        if key is None:
            raise ValueError("File F is missing canonical key 'prime_award_unique_key'")
        number = _plain_optional(columns, ["subaward_number"])
        name = _plain_optional(
            columns,
            ["subawardee_name", "sub_awardee_or_recipient_legal", "subawardee_or_recipient_legal"],
        )
        uei = _plain_optional(columns, ["subawardee_uei", "sub_awardee_or_recipient_uei"])
        amount = _numeric_optional(columns, ["subaward_amount"])
        description = _plain_optional(columns, ["subaward_description"])
        action_date = _plain_optional(columns, ["subaward_action_date", "action_date"])
        search_expr = _search_expr(
            columns,
            [
                "prime_award_unique_key",
                "prime_award_piid",
                "prime_award_fain",
                "subaward_number",
                "subawardee_name",
                "sub_awardee_or_recipient_legal",
                "subawardee_or_recipient_legal",
                "subawardee_uei",
                "sub_awardee_or_recipient_uei",
                "subaward_description",
            ],
        )
        conditions, params = _token_conditions(search_expr, query)
        sql = f"""
            SELECT DISTINCT
                nullif(trim(CAST({_ident(key)} AS VARCHAR)), '') AS prime_award_identity,
                {number} AS subaward_number,
                {name} AS subawardee_name,
                {uei} AS subawardee_uei,
                {amount} AS subaward_amount,
                {description} AS description,
                {action_date} AS action_date
            FROM read_parquet(?)
            WHERE nullif(trim(CAST({_ident(key)} AS VARCHAR)), '') IS NOT NULL
              AND {conditions}
            ORDER BY subaward_number NULLS LAST, subawardee_name NULLS LAST
            LIMIT ?
        """
        rows = connection.execute(
            sql, [[str(path) for path in paths], *params, limit]
        ).fetchall()
        return [
            {
                "prime_award_identity": row[0],
                "award_family": family,
                "subaward_number": row[1],
                "subawardee_name": row[2],
                "subawardee_uei": row[3],
                "subaward_amount": Decimal(str(row[4])) if row[4] is not None else None,
                "description": row[5],
                "action_date": row[6],
            }
            for row in rows
        ]
    finally:
        connection.close()


def _prime_result(query: str, row: dict) -> FederalSearchV2Result:
    award_id = row.get("award_id_piid") or row.get("award_id_fain") or row.get("award_id_uri")
    fields = [
        row.get("award_identity"),
        award_id,
        row.get("recipient_name"),
        row.get("recipient_uei"),
        row.get("description"),
        row.get("awarding_agency_name"),
        row.get("funding_agency_name"),
        row.get("award_type"),
    ]
    identity = row["award_identity"]
    return FederalSearchV2Result(
        entity_type="prime_award",
        key=f"prime_award:{identity}",
        title=award_id or identity,
        subtitle=row.get("recipient_name") or row.get("award_type"),
        score=_score(query, fields, exact=[identity, award_id, row.get("recipient_uei")]),
        award_identity=identity,
        award_family=row.get("award_family"),
        recipient_name=row.get("recipient_name"),
        recipient_uei=row.get("recipient_uei"),
        description=row.get("description"),
        target_award_identity=identity,
        metadata={
            "transaction_count": row.get("transaction_count", 0),
            "award_id_piid": row.get("award_id_piid"),
            "award_id_fain": row.get("award_id_fain"),
            "award_id_uri": row.get("award_id_uri"),
            "awarding_agency_name": row.get("awarding_agency_name"),
            "funding_agency_name": row.get("funding_agency_name"),
            "award_type": row.get("award_type"),
        },
    )


def _recipient_result(query: str, row: dict) -> FederalSearchV2Result:
    name = row.get("recipient_name")
    uei = row.get("recipient_uei")
    return FederalSearchV2Result(
        entity_type="recipient",
        key=row["recipient_key"],
        title=name or uei or "Unnamed recipient",
        subtitle=f"{row.get('award_count', 0)} matching prime award identities",
        score=_score(query, [name, uei], exact=[name, uei]),
        award_identity=row.get("sample_award_identity"),
        recipient_name=name,
        recipient_uei=uei,
        target_award_identity=row.get("sample_award_identity"),
        metadata={
            "award_count": row.get("award_count", 0),
            "award_families": sorted(row.get("families") or []),
            "sample_award_identity": row.get("sample_award_identity"),
        },
        warning=(
            "Recipient results group overlapping prime-award identities for navigation. A personalized amount, when present, is an aggregate of File C award allocations for that recipient and must not be added to other search results."
        ),
    )


def _subaward_result(query: str, row: dict) -> FederalSearchV2Result:
    identity = row["prime_award_identity"]
    number = row.get("subaward_number")
    name = row.get("subawardee_name")
    fallback = normalize(name or "subaward") or "subaward"
    key_suffix = number or row.get("subawardee_uei") or fallback
    return FederalSearchV2Result(
        entity_type="subaward",
        key=f"subaward:{row.get('award_family')}:{identity}:{key_suffix}",
        title=name or number or "Subaward",
        subtitle=f"Subaward {number}" if number else "File F subaward",
        score=_score(
            query,
            [identity, number, name, row.get("subawardee_uei"), row.get("description")],
            exact=[number, row.get("subawardee_uei")],
        ),
        award_identity=identity,
        award_family=row.get("award_family"),
        description=row.get("description"),
        target_award_identity=identity,
        metadata={
            "subaward_number": number,
            "subawardee_name": name,
            "subawardee_uei": row.get("subawardee_uei"),
            "subaward_amount": str(row["subaward_amount"]) if row.get("subaward_amount") is not None else None,
            "action_date": row.get("action_date"),
        },
        warning=(
            "File F is downstream descriptive context. This subaward result has no personalized amount and must not be added beside its prime award."
        ),
    )


def _dedupe_and_rank(
    results: list[FederalSearchV2Result], limit: int
) -> list[FederalSearchV2Result]:
    best: dict[tuple[str, str], FederalSearchV2Result] = {}
    for result in results:
        key = (result.entity_type, result.key)
        current = best.get(key)
        if current is None or result.score > current.score:
            best[key] = result
    return sorted(
        best.values(),
        key=lambda row: (-row.score, row.entity_type, row.title.casefold(), row.key),
    )[:limit]


def _score(query: str, fields: list, *, exact: list | None = None) -> Decimal:
    q = normalize(query)
    normalized = [normalize(str(field)) for field in fields if field]
    exact_values = [normalize(str(field)) for field in (exact or []) if field]
    score = 0.0
    if q in exact_values:
        score = 100.0
    for field in normalized:
        if field == q:
            score = max(score, 96.0)
        elif field.startswith(q):
            score = max(score, 84.0)
        elif q in field:
            score = max(score, 72.0)
    tokens = q.split()
    if tokens and normalized:
        hay = " ".join(normalized)
        token_hits = sum(1 for token in tokens if token in hay)
        score = max(score, 55.0 * token_hits / len(tokens))
        score = max(score, max(SequenceMatcher(None, q, field).ratio() for field in normalized) * 45.0)
    return Decimal(str(round(score, 2)))


def _open_paths(paths: list[Path]):
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for Warehouse V2 federal search") from exc
    connection = duckdb.connect()
    connection.execute("SELECT * FROM read_parquet(?) LIMIT 0", [[str(path) for path in paths]])
    columns = {str(item[0]).lower(): str(item[0]) for item in connection.description}
    return connection, columns


def _search_expr(columns: dict[str, str], candidates: list[str]) -> str:
    pieces = []
    seen = set()
    for candidate in candidates:
        column = columns.get(candidate)
        if column is None or column in seen:
            continue
        seen.add(column)
        pieces.append(f"coalesce(lower(CAST({_ident(column)} AS VARCHAR)), '')")
    if not pieces:
        return "''"
    return "(" + " || ' ' || ".join(pieces) + ")"


def _token_conditions(search_expr: str, query: str) -> tuple[str, list[str]]:
    tokens = normalize(query).split()
    if not tokens:
        return "FALSE", []
    return " AND ".join(f"{search_expr} LIKE ?" for _ in tokens), [
        f"%{token}%" for token in tokens
    ]


def _aggregate_optional(columns: dict[str, str], candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate in columns:
            return f"min(nullif(trim(CAST({_ident(columns[candidate])} AS VARCHAR)), ''))"
    return "CAST(NULL AS VARCHAR)"


def _plain_optional(columns: dict[str, str], candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate in columns:
            return f"nullif(trim(CAST({_ident(columns[candidate])} AS VARCHAR)), '')"
    return "CAST(NULL AS VARCHAR)"


def _numeric_optional(columns: dict[str, str], candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate in columns:
            return f"try_cast({_ident(columns[candidate])} AS DECIMAL(38, 2))"
    return "CAST(NULL AS DECIMAL(38, 2))"
