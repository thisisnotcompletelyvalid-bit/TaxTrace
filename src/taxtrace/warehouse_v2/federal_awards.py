from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from taxtrace.allocation.engine import _reconcile_parts, money
from taxtrace.allocation.models import FederalReceiptRequest
from taxtrace.warehouse_v2.db_models import BulkObject, DatasetDefinition, DatasetRelease
from taxtrace.warehouse_v2.federal_receipt import (
    FederalReceiptV2Engine,
    FederalReceiptV2Result,
    _ident,
    _normalize_account_code,
    _optional_expr,
)
from taxtrace.warehouse_v2.lake import LakeStore
from taxtrace.warehouse_v2.usaspending_award_crosswalk import FILE_C_DATASET

ZERO = Decimal("0")
FILE_C_OUTLAY_COLUMN = "gross_outlay_amount_fyb_to_period_end"


class FederalAwardCoverage(BaseModel):
    dataset_key: str = FILE_C_DATASET
    release_key: str | None = None
    fiscal_year: int
    status: str
    full_fiscal_year: bool = False
    row_count: int | None = None
    object_count: int = 0
    object_keys: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class FederalAwardNode(BaseModel):
    key: str
    label: str
    node_type: str
    allocated_amount: Decimal
    file_c_government_outlay: Decimal | None = None
    award_identity: str | None = None
    award_family: str | None = None
    award_id_piid: str | None = None
    award_id_fain: str | None = None
    award_id_uri: str | None = None
    recipient_name: str | None = None
    recipient_uei: str | None = None
    description: str | None = None
    awarding_agency_name: str | None = None
    funding_agency_name: str | None = None
    award_type: str | None = None
    usaspending_permalink: str | None = None
    source_row_count: int = 0
    linked: bool = False
    residual: bool = False
    additive_within_account: bool = True
    method: str
    notes: list[str] = Field(default_factory=list)


class FederalAccountAwardProjection(BaseModel):
    key: str
    account_code: str
    account_name: str
    allocated_amount: Decimal
    file_b_government_outlay: Decimal | None = None
    file_c_government_outlay: Decimal | None = None
    file_c_share_of_file_b: Decimal | None = None
    children: list[FederalAwardNode] = Field(default_factory=list)
    conservation_difference: Decimal = ZERO
    projection_available: bool = False
    notes: list[str] = Field(default_factory=list)


class FederalAwardProjectionResult(BaseModel):
    receipt: FederalReceiptV2Result
    file_c: FederalAwardCoverage
    accounts: list[FederalAccountAwardProjection]
    warnings: list[str] = Field(default_factory=list)


class _FileCAwardRow(BaseModel):
    account_code: str
    award_identity: str | None = None
    award_family: str | None = None
    award_id_piid: str | None = None
    award_id_fain: str | None = None
    award_id_uri: str | None = None
    recipient_name: str | None = None
    recipient_uei: str | None = None
    description: str | None = None
    awarding_agency_name: str | None = None
    funding_agency_name: str | None = None
    award_type: str | None = None
    usaspending_permalink: str | None = None
    source_row_count: int
    outlay: Decimal


class FederalAwardProjectionEngine:
    """Project OMB-controlled account attribution into a conservative File C award view.

    File C is award-financial activity, not proof that every dollar in an OMB account is
    award spending. The projection therefore uses a full-year File B account total as the
    USAspending denominator. File C supplies only the award-financial numerator and identity
    shares. Any remainder stays explicit rather than being silently assigned to awards.

    File C identities are collapsed before later D1/D2 enrichment. This is required because
    File C and D1/D2 can both repeat the same canonical award identity and a raw join can
    create many-to-many fan-out.
    """

    def __init__(
        self,
        receipt_engine: FederalReceiptV2Engine | None = None,
        lake: LakeStore | None = None,
    ):
        self.lake = lake or LakeStore()
        self.receipt_engine = receipt_engine or FederalReceiptV2Engine(lake=self.lake)

    def calculate(
        self,
        session: Session,
        request: FederalReceiptRequest,
    ) -> FederalAwardProjectionResult:
        receipt = self.receipt_engine.calculate(session, request)
        account_codes = {account.account_code for account in receipt.accounts}
        coverage, rows = self._load_file_c(
            session,
            fiscal_year=request.spending_fiscal_year,
            account_codes=account_codes,
        )
        by_account: dict[str, list[_FileCAwardRow]] = defaultdict(list)
        for row in rows:
            by_account[_normalize_account_code(row.account_code)].append(row)

        accounts: list[FederalAccountAwardProjection] = []
        warnings: list[str] = []
        if coverage.status != "READY":
            warnings.append(
                "Warehouse V2 File C is not safely available as a full-year award-financial view; account dollars remain conserved in explicit residual children."
            )
        if receipt.warehouse.status != "READY":
            warnings.append(
                "A full-year local File B denominator is required before File C can receive personalized award attribution."
            )

        for account in receipt.accounts:
            detail = by_account.get(account.account_code, [])
            projected = self._project_account(account, detail, coverage)
            accounts.append(projected)

        warnings.append(
            "This award view is an alternate classification of the same account attribution. Do not add it to File B program/object detail, purpose, agency, D1/D2, or File F views."
        )
        warnings.append(
            "D1/D2 and File F may enrich these collapsed award identities later, but those grains are non-additive and must never create additional personalized spending."
        )
        return FederalAwardProjectionResult(
            receipt=receipt,
            file_c=coverage,
            accounts=sorted(accounts, key=lambda node: (-abs(node.allocated_amount), node.account_name)),
            warnings=warnings,
        )

    def _project_account(
        self,
        account,
        rows: list[_FileCAwardRow],
        coverage: FederalAwardCoverage,
    ) -> FederalAccountAwardProjection:
        parent = money(account.allocated_amount)
        file_b_total = account.file_b_government_outlay
        file_c_total = money(sum((row.outlay for row in rows), ZERO)) if rows else None
        notes: list[str] = []

        if coverage.status != "READY":
            children = [_award_residual(account.account_code, parent, "Full-year File C detail unavailable")]
            return self._account_result(account, file_c_total, None, children, False, notes)
        if not rows:
            children = [_award_residual(account.account_code, parent, "No File C award-financial rows matched this account")]
            return self._account_result(account, file_c_total, None, children, False, notes)
        if file_b_total is None or file_b_total == ZERO:
            children = [_award_residual(account.account_code, parent, "No nonzero full-year File B account denominator is available")]
            return self._account_result(account, file_c_total, None, children, False, notes)

        file_b_total = money(file_b_total)
        file_c_total = file_c_total or ZERO
        if file_b_total <= ZERO or file_c_total < ZERO or file_c_total > file_b_total:
            notes.append(
                "File C cannot be reconciled conservatively to this File B account total, so no personalized dollars are assigned to awards."
            )
            children = [_award_residual(account.account_code, parent, "File C/File B totals fail conservative award-share bounds")]
            return self._account_result(account, file_c_total, None, children, False, notes)

        ratio = file_c_total / file_b_total
        raw_award = parent * ratio
        award_pool, residual_amount = _reconcile_parts(parent, [raw_award, parent - raw_award])
        children = self._award_children(account.account_code, award_pool, rows, file_c_total)
        if residual_amount != ZERO:
            children.append(
                _award_residual(
                    account.account_code,
                    residual_amount,
                    "OMB-controlled account attribution not represented by full-year File C award-financial outlays",
                )
            )
        children = sorted(children, key=lambda child: (-abs(child.allocated_amount), child.label, child.key))
        child_total = money(sum((child.allocated_amount for child in children), ZERO))
        if child_total != parent:
            raise ValueError(
                f"File C award projection failed account-level conservation for {account.account_code}: "
                f"{money(parent - child_total)}"
            )
        notes.append(
            "Personalized award dollars use File C outlays divided by the matching full-year File B account outlay; the remaining account amount stays explicit."
        )
        if any(row.outlay < ZERO for row in rows):
            notes.append("File C contains signed negative outlay adjustments; child allocations preserve those signed shares.")
        return self._account_result(account, file_c_total, ratio, children, True, notes)

    def _award_children(
        self,
        account_code: str,
        award_pool: Decimal,
        rows: list[_FileCAwardRow],
        file_c_total: Decimal,
    ) -> list[FederalAwardNode]:
        if file_c_total == ZERO:
            return []
        raw = [award_pool * row.outlay / file_c_total for row in rows]
        amounts = _reconcile_parts(award_pool, raw)
        children: list[FederalAwardNode] = []
        for row, amount in zip(rows, amounts, strict=True):
            linked = bool(row.award_identity)
            if linked:
                label = (
                    row.recipient_name
                    or row.description
                    or row.award_id_piid
                    or row.award_id_fain
                    or row.award_id_uri
                    or row.award_identity
                )
                key_suffix = row.award_identity
                node_type = "prime_award"
                notes = [
                    "File C rows were collapsed to one canonical award identity before this personalized share was calculated."
                ]
            else:
                label = "Unlinked award-financial activity"
                key_suffix = "unlinked"
                node_type = "unlinked_award_financial"
                notes = [
                    "USAspending reports this File C activity without a canonical prime-award identity; TaxTrace preserves it instead of dropping or guessing a link."
                ]
            children.append(
                FederalAwardNode(
                    key=f"file_c:{account_code}:{key_suffix}",
                    label=label,
                    node_type=node_type,
                    allocated_amount=money(amount),
                    file_c_government_outlay=money(row.outlay),
                    award_identity=row.award_identity,
                    award_family=row.award_family,
                    award_id_piid=row.award_id_piid,
                    award_id_fain=row.award_id_fain,
                    award_id_uri=row.award_id_uri,
                    recipient_name=row.recipient_name,
                    recipient_uei=row.recipient_uei,
                    description=row.description,
                    awarding_agency_name=row.awarding_agency_name,
                    funding_agency_name=row.funding_agency_name,
                    award_type=row.award_type,
                    usaspending_permalink=row.usaspending_permalink,
                    source_row_count=row.source_row_count,
                    linked=linked,
                    method="OMB_ACCOUNT_PARENT__FILE_B_DENOMINATOR__FILE_C_AWARD_SHARE",
                    notes=notes,
                )
            )
        return children

    def _account_result(
        self,
        account,
        file_c_total: Decimal | None,
        ratio: Decimal | None,
        children: list[FederalAwardNode],
        available: bool,
        notes: list[str],
    ) -> FederalAccountAwardProjection:
        parent = money(account.allocated_amount)
        child_total = money(sum((child.allocated_amount for child in children), ZERO))
        difference = money(parent - child_total)
        if difference != ZERO:
            raise ValueError(
                f"File C award projection does not conserve account {account.account_code}: {difference}"
            )
        return FederalAccountAwardProjection(
            key=f"federal_account_awards:{account.account_code}",
            account_code=account.account_code,
            account_name=account.account_name,
            allocated_amount=parent,
            file_b_government_outlay=account.file_b_government_outlay,
            file_c_government_outlay=file_c_total,
            file_c_share_of_file_b=ratio,
            children=children,
            conservation_difference=difference,
            projection_available=available,
            notes=notes,
        )

    def _load_file_c(
        self,
        session: Session,
        *,
        fiscal_year: int,
        account_codes: set[str],
    ) -> tuple[FederalAwardCoverage, list[_FileCAwardRow]]:
        release_row = session.execute(
            select(DatasetDefinition, DatasetRelease)
            .join(DatasetRelease, DatasetRelease.dataset_id == DatasetDefinition.id)
            .where(
                DatasetDefinition.key == FILE_C_DATASET,
                DatasetRelease.reference_year == fiscal_year,
                DatasetRelease.status == "READY",
            )
            .order_by(DatasetRelease.ingested_at.desc(), DatasetRelease.id.desc())
        ).first()
        if release_row is None:
            return (
                FederalAwardCoverage(
                    fiscal_year=fiscal_year,
                    status="NO_READY_RELEASE",
                    notes=["No READY USAspending File C release is registered for this fiscal year."],
                ),
                [],
            )

        _, release = release_row
        request = (release.metadata_json or {}).get("download_request") or {}
        filters = request.get("filters") or {}
        period = str(filters.get("period") or "")
        full_fiscal_year = period == "12"
        objects = session.scalars(
            select(BulkObject)
            .where(
                BulkObject.dataset_release_id == release.id,
                BulkObject.layer == "normalized",
                BulkObject.storage_format == "PARQUET",
            )
            .order_by(BulkObject.object_key)
        ).all()
        coverage = FederalAwardCoverage(
            release_key=release.release_key,
            fiscal_year=fiscal_year,
            status="READY" if full_fiscal_year else "PARTIAL_OR_UNKNOWN_PERIOD",
            full_fiscal_year=full_fiscal_year,
            row_count=release.row_count,
            object_count=len(objects),
            object_keys=[obj.object_key for obj in objects],
            notes=[],
        )
        if not full_fiscal_year:
            coverage.notes.append(
                "File C release is not proven to be reporting period 12, so it is not used for a full-year personalized award projection."
            )
            return coverage, []
        if not objects:
            coverage.status = "NO_PARQUET_OBJECTS"
            coverage.notes.append("READY File C release has no normalized Parquet objects registered.")
            return coverage, []
        paths = [self.lake.root / obj.object_key for obj in objects]
        missing = [str(path) for path in paths if not path.exists()]
        if missing:
            coverage.status = "OBJECTS_NOT_LOCAL"
            coverage.notes.append(
                "File C metadata is present but one or more normalized lake objects are not available on this runtime."
            )
            return coverage, []
        if not account_codes:
            return coverage, []
        try:
            rows = _query_file_c(paths, account_codes)
        except (RuntimeError, ValueError) as exc:
            coverage.status = "UNSUPPORTED_SCHEMA"
            coverage.notes.append(str(exc))
            return coverage, []
        return coverage, rows


def _query_file_c(paths: list[Path], account_codes: set[str]) -> list[_FileCAwardRow]:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for Warehouse V2 federal award queries") from exc

    connection = duckdb.connect()
    try:
        connection.execute("SELECT * FROM read_parquet(?) LIMIT 0", [[str(path) for path in paths]])
        columns = {str(item[0]).lower(): str(item[0]) for item in connection.description}
        amount = columns.get(FILE_C_OUTLAY_COLUMN)
        award_key = columns.get("award_unique_key")
        if amount is None:
            raise ValueError(f"File C is missing required outlay column {FILE_C_OUTLAY_COLUMN!r}")
        if award_key is None:
            raise ValueError("File C is missing canonical award identity column 'award_unique_key'")

        if "federal_account_symbol" in columns:
            account_expr = _ident(columns["federal_account_symbol"])
        elif "agency_identifier_code" in columns and "main_account_code" in columns:
            account_expr = (
                f"lpad(trim(CAST({_ident(columns['agency_identifier_code'])} AS VARCHAR)), 3, '0') "
                f"|| '-' || lpad(trim(CAST({_ident(columns['main_account_code'])} AS VARCHAR)), 4, '0')"
            )
        else:
            raise ValueError(
                "File C lacks federal_account_symbol and the agency_identifier_code/main_account_code fallback"
            )

        amount_expr = f"try_cast({_ident(amount)} AS DECIMAL(38, 2))"
        identity_expr = f"nullif(trim(CAST({_ident(award_key)} AS VARCHAR)), '')"
        normalized_codes = sorted({_normalize_account_code(code) for code in account_codes})
        placeholders = ", ".join("?" for _ in normalized_codes)

        piid = _aggregate_optional(columns, ["award_id_piid"])
        fain = _aggregate_optional(columns, ["award_id_fain"])
        uri = _aggregate_optional(columns, ["award_id_uri"])
        recipient = _aggregate_optional(columns, ["recipient_name", "recipient_name_raw"])
        recipient_uei = _aggregate_optional(columns, ["recipient_uei"])
        description = _aggregate_optional(
            columns,
            ["prime_award_base_transaction_description", "award_description"],
        )
        awarding_agency = _aggregate_optional(columns, ["awarding_agency_name"])
        funding_agency = _aggregate_optional(columns, ["funding_agency_name"])
        award_type = _aggregate_optional(columns, ["award_type"])
        permalink = _aggregate_optional(columns, ["usaspending_permalink"])

        piid_raw = _optional_expr(columns, ["award_id_piid"])
        fain_raw = _optional_expr(columns, ["award_id_fain"])
        uri_raw = _optional_expr(columns, ["award_id_uri"])
        family_expr = f"""
            CASE
                WHEN max(CASE WHEN nullif(trim({piid_raw}), '') IS NOT NULL THEN 1 ELSE 0 END) = 1 THEN 'contract'
                WHEN max(CASE WHEN nullif(trim({fain_raw}), '') IS NOT NULL OR nullif(trim({uri_raw}), '') IS NOT NULL THEN 1 ELSE 0 END) = 1 THEN 'assistance'
                WHEN {identity_expr} IS NULL THEN 'unlinked'
                ELSE 'unknown'
            END
        """

        sql = f"""
            SELECT
                upper(trim(CAST({account_expr} AS VARCHAR))) AS account_code,
                {identity_expr} AS award_identity,
                {family_expr} AS award_family,
                {piid} AS award_id_piid,
                {fain} AS award_id_fain,
                {uri} AS award_id_uri,
                {recipient} AS recipient_name,
                {recipient_uei} AS recipient_uei,
                {description} AS description,
                {awarding_agency} AS awarding_agency_name,
                {funding_agency} AS funding_agency_name,
                {award_type} AS award_type,
                {permalink} AS usaspending_permalink,
                count(*) AS source_row_count,
                SUM({amount_expr}) AS outlay
            FROM read_parquet(?)
            WHERE {amount_expr} IS NOT NULL
              AND {amount_expr} <> 0
              AND upper(trim(CAST({account_expr} AS VARCHAR))) IN ({placeholders})
            GROUP BY 1, 2
            ORDER BY 1, 2 NULLS LAST
        """
        result = connection.execute(
            sql,
            [[str(path) for path in paths], *normalized_codes],
        ).fetchall()
        return [
            _FileCAwardRow(
                account_code=row[0],
                award_identity=row[1],
                award_family=row[2],
                award_id_piid=row[3],
                award_id_fain=row[4],
                award_id_uri=row[5],
                recipient_name=row[6],
                recipient_uei=row[7],
                description=row[8],
                awarding_agency_name=row[9],
                funding_agency_name=row[10],
                award_type=row[11],
                usaspending_permalink=row[12],
                source_row_count=int(row[13]),
                outlay=Decimal(str(row[14])),
            )
            for row in result
        ]
    finally:
        connection.close()


def _aggregate_optional(columns: dict[str, str], candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate in columns:
            ident = _ident(columns[candidate])
            return f"min(nullif(trim(CAST({ident} AS VARCHAR)), ''))"
    return "CAST(NULL AS VARCHAR)"


def _award_residual(account_code: str, amount: Decimal, note: str) -> FederalAwardNode:
    return FederalAwardNode(
        key=f"file_c:{account_code}:residual",
        label="Non-award or unreconciled account activity",
        node_type="residual",
        allocated_amount=money(amount),
        residual=True,
        method="RESIDUAL_AWARD_DETAIL_UNAVAILABLE",
        notes=[note],
    )
