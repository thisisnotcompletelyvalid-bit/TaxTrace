from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from taxtrace.allocation.engine import FederalAllocationEngine, _reconcile_parts, money
from taxtrace.allocation.models import FederalReceiptRequest, FederalReceiptResult
from taxtrace.db_models import FederalAccount
from taxtrace.warehouse_v2.db_models import BulkObject, DatasetDefinition, DatasetRelease
from taxtrace.warehouse_v2.lake import LakeStore

ZERO = Decimal("0")
FILE_B_DATASET = "usaspending-file-b"
FILE_B_OUTLAY_COLUMN = "gross_outlay_amount_fyb_to_period_end"


class WarehouseCoverage(BaseModel):
    dataset_key: str = FILE_B_DATASET
    release_key: str | None = None
    fiscal_year: int
    status: str
    full_fiscal_year: bool = False
    row_count: int | None = None
    object_count: int = 0
    object_keys: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class WarehouseReceiptChild(BaseModel):
    key: str
    label: str
    node_type: str = "program_activity_object_class"
    allocated_amount: Decimal
    government_outlay: Decimal | None = None
    program_activity_code: str | None = None
    program_activity_name: str | None = None
    object_class_code: str | None = None
    object_class_name: str | None = None
    additive: bool = True
    residual: bool = False
    method: str
    notes: list[str] = Field(default_factory=list)


class WarehouseAccountNode(BaseModel):
    key: str
    account_code: str
    account_name: str
    allocated_amount: Decimal
    omb_government_outlay: Decimal
    file_b_government_outlay: Decimal | None = None
    children: list[WarehouseReceiptChild] = Field(default_factory=list)
    conservation_difference: Decimal = ZERO
    warehouse_matched: bool = False
    notes: list[str] = Field(default_factory=list)


class FederalReceiptV2Result(BaseModel):
    """Conserved federal receipt with Warehouse V2 File B as an additive detail partition."""

    base_receipt: FederalReceiptResult
    warehouse: WarehouseCoverage
    accounts: list[WarehouseAccountNode]
    residual_amount: Decimal
    additive_partition_total: Decimal
    conservation_difference: Decimal
    warnings: list[str] = Field(default_factory=list)


class _FileBRow(BaseModel):
    account_code: str
    account_name: str | None = None
    program_activity_code: str | None = None
    program_activity_name: str | None = None
    object_class_code: str | None = None
    object_class_name: str | None = None
    outlay: Decimal


class FederalReceiptV2Engine:
    """Bridge the conserved OMB receipt into Warehouse V2 File B detail.

    OMB actual account outlays remain the controlling attribution base. File B is used only to
    partition an already-attributed account amount across program-activity × object-class rows.
    OMB and USAspending values are therefore never added together.
    """

    def __init__(
        self,
        allocation_engine: FederalAllocationEngine | None = None,
        lake: LakeStore | None = None,
    ):
        self.allocation_engine = allocation_engine or FederalAllocationEngine()
        self.lake = lake or LakeStore()

    def calculate(self, session: Session, request: FederalReceiptRequest) -> FederalReceiptV2Result:
        base = self.allocation_engine.calculate(session, request)
        computations = self._computations(session, request, base)
        allocations = [allocation for computation in computations for allocation in computation.allocations]
        account_buckets: dict[str, list] = defaultdict(list)
        account_names: dict[str, str] = {}
        residual = sum((c.contribution for c in computations if not c.allocations), ZERO)

        for allocation in allocations:
            if not allocation.fact.federal_account_id:
                residual += allocation.allocated_amount
                continue
            account = session.get(FederalAccount, allocation.fact.federal_account_id)
            if account is None or not account.native_code:
                residual += allocation.allocated_amount
                continue
            code = _normalize_account_code(account.native_code)
            account_buckets[code].append(allocation)
            account_names[code] = account.name

        coverage, file_b_rows = self._load_file_b(
            session,
            fiscal_year=request.spending_fiscal_year,
            account_codes=set(account_buckets),
        )
        file_b_by_account: dict[str, list[_FileBRow]] = defaultdict(list)
        for row in file_b_rows:
            file_b_by_account[_normalize_account_code(row.account_code)].append(row)

        nodes: list[WarehouseAccountNode] = []
        warnings: list[str] = []
        if coverage.status != "READY":
            warnings.append(
                "Warehouse V2 File B is not safely available for this fiscal year; account dollars remain visible with explicit detail-unavailable children."
            )

        for code, rows in account_buckets.items():
            allocated_amount = money(sum((row.allocated_amount for row in rows), ZERO))
            unique_facts = {row.fact.id: Decimal(row.fact.amount) for row in rows}
            omb_outlay = money(sum(unique_facts.values(), ZERO))
            detail = file_b_by_account.get(code, [])
            children = self._children(code, allocated_amount, detail)
            child_total = money(sum((child.allocated_amount for child in children), ZERO))
            file_b_outlay = money(sum((row.outlay for row in detail), ZERO)) if detail else None
            notes: list[str] = []
            if detail:
                notes.append(
                    "OMB actual account outlay controls the parent attribution; File B outlays supply only the program/activity/object-class shares."
                )
                if file_b_outlay != omb_outlay:
                    notes.append(
                        "OMB and File B government outlay totals differ at this account. TaxTrace preserves the OMB parent and does not scale or add the source totals together."
                    )
            else:
                notes.append("No safe FY-matched File B rows were available for this OMB federal account.")
            nodes.append(
                WarehouseAccountNode(
                    key=f"federal_account:{code}",
                    account_code=code,
                    account_name=account_names[code],
                    allocated_amount=allocated_amount,
                    omb_government_outlay=omb_outlay,
                    file_b_government_outlay=file_b_outlay,
                    children=children,
                    conservation_difference=money(allocated_amount - child_total),
                    warehouse_matched=bool(detail),
                    notes=notes,
                )
            )

        account_total = money(sum((node.allocated_amount for node in nodes), ZERO))
        residual = money(Decimal(residual))
        partition_total = money(account_total + residual)
        difference = money(base.total_allocable_taxes - partition_total)
        if difference != ZERO:
            raise ValueError(
                "Warehouse V2 account bridge does not conserve the base federal receipt; "
                f"refusing to publish (difference {difference})."
            )
        if any(node.conservation_difference != ZERO for node in nodes):
            raise ValueError("Warehouse V2 File B child partition failed account-level conservation")
        if residual:
            warnings.append(
                "Some supported tax dollars have no OMB federal-account parent or no allocatable pool detail; they remain an explicit top-level residual."
            )
        warnings.append(
            "File B is additive only within this account detail view. Do not add these children to purpose, agency, award, File C, D1/D2, or File F views."
        )
        return FederalReceiptV2Result(
            base_receipt=base,
            warehouse=coverage,
            accounts=sorted(nodes, key=lambda node: (-abs(node.allocated_amount), node.account_name)),
            residual_amount=residual,
            additive_partition_total=partition_total,
            conservation_difference=difference,
            warnings=warnings,
        )

    def _computations(
        self,
        session: Session,
        request: FederalReceiptRequest,
        base: FederalReceiptResult,
    ):
        tax_result = base.tax_result
        components = {
            "FED_INCOME_TAX": tax_result.federal_income_tax_liability,
            "SS_EMPLOYEE": tax_result.social_security_tax,
            "MEDICARE_EMPLOYEE": tax_result.medicare_tax,
            "ADDITIONAL_MEDICARE": tax_result.additional_medicare_tax,
        }
        _, pool_contributions, _ = self.allocation_engine._map_revenue_to_pools(
            session, components, request.tax_year
        )
        return self.allocation_engine.compute_pool_allocations(
            session, pool_contributions, request.spending_fiscal_year
        )

    def _children(
        self,
        account_code: str,
        parent_amount: Decimal,
        rows: list[_FileBRow],
    ) -> list[WarehouseReceiptChild]:
        if not rows:
            return [_residual_child(account_code, parent_amount, "Warehouse V2 File B detail unavailable")]
        denominator = sum((row.outlay for row in rows), ZERO)
        if denominator == ZERO:
            return [_residual_child(account_code, parent_amount, "File B net outlay denominator is zero")]
        raw = [parent_amount * row.outlay / denominator for row in rows]
        allocated = _reconcile_parts(parent_amount, raw)
        result: list[WarehouseReceiptChild] = []
        for index, (row, amount) in enumerate(zip(rows, allocated, strict=True), start=1):
            program_label = row.program_activity_name or row.program_activity_code or "Unclassified program activity"
            object_label = row.object_class_name or row.object_class_code or "Unclassified object class"
            result.append(
                WarehouseReceiptChild(
                    key=(
                        f"file_b:{account_code}:"
                        f"{row.program_activity_code or index}:"
                        f"{row.object_class_code or index}"
                    ),
                    label=f"{program_label} — {object_label}",
                    allocated_amount=amount,
                    government_outlay=money(row.outlay),
                    program_activity_code=row.program_activity_code,
                    program_activity_name=row.program_activity_name,
                    object_class_code=row.object_class_code,
                    object_class_name=row.object_class_name,
                    method="OMB_ACCOUNT_PARENT__FILE_B_OUTLAY_SHARE",
                    notes=[
                        "This child is a proportional classification of the OMB-controlled parent amount, not a second expenditure."
                    ],
                )
            )
        return sorted(result, key=lambda child: (-abs(child.allocated_amount), child.label))

    def _load_file_b(
        self,
        session: Session,
        *,
        fiscal_year: int,
        account_codes: set[str],
    ) -> tuple[WarehouseCoverage, list[_FileBRow]]:
        release_row = session.execute(
            select(DatasetDefinition, DatasetRelease)
            .join(DatasetRelease, DatasetRelease.dataset_id == DatasetDefinition.id)
            .where(
                DatasetDefinition.key == FILE_B_DATASET,
                DatasetRelease.reference_year == fiscal_year,
                DatasetRelease.status == "READY",
            )
            .order_by(DatasetRelease.ingested_at.desc(), DatasetRelease.id.desc())
        ).first()
        if release_row is None:
            return (
                WarehouseCoverage(
                    fiscal_year=fiscal_year,
                    status="NO_READY_RELEASE",
                    notes=["No READY USAspending File B release is registered for this fiscal year."],
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
        coverage = WarehouseCoverage(
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
                "File B release is not proven to be reporting period 12, so it is not used to partition a full-year OMB receipt."
            )
            return coverage, []
        if not objects:
            coverage.status = "NO_PARQUET_OBJECTS"
            coverage.notes.append("READY File B release has no normalized Parquet objects registered.")
            return coverage, []
        paths = [self.lake.root / obj.object_key for obj in objects]
        missing = [str(path) for path in paths if not path.exists()]
        if missing:
            coverage.status = "OBJECTS_NOT_LOCAL"
            coverage.notes.append(
                "File B metadata is present but one or more normalized lake objects are not available on this runtime."
            )
            return coverage, []
        if not account_codes:
            return coverage, []
        try:
            rows = _query_file_b(paths, account_codes)
        except (RuntimeError, ValueError) as exc:
            coverage.status = "UNSUPPORTED_SCHEMA"
            coverage.notes.append(str(exc))
            return coverage, []
        return coverage, rows


def _query_file_b(paths: list[Path], account_codes: set[str]) -> list[_FileBRow]:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for Warehouse V2 federal receipt queries") from exc
    connection = duckdb.connect()
    try:
        connection.execute("SELECT * FROM read_parquet(?) LIMIT 0", [[str(path) for path in paths]])
        columns = {str(item[0]).lower(): str(item[0]) for item in connection.description}
        amount = columns.get(FILE_B_OUTLAY_COLUMN)
        if amount is None:
            raise ValueError(f"File B is missing required outlay column {FILE_B_OUTLAY_COLUMN!r}")
        if "federal_account_symbol" in columns:
            account_expr = _ident(columns["federal_account_symbol"])
        elif "agency_identifier_code" in columns and "main_account_code" in columns:
            account_expr = (
                f"lpad(trim(CAST({_ident(columns['agency_identifier_code'])} AS VARCHAR)), 3, '0') "
                f"|| '-' || lpad(trim(CAST({_ident(columns['main_account_code'])} AS VARCHAR)), 4, '0')"
            )
        else:
            raise ValueError(
                "File B lacks federal_account_symbol and the agency_identifier_code/main_account_code fallback"
            )
        account_name = _optional_expr(columns, ["federal_account_name", "treasury_account_name"])
        pa_code = _optional_expr(columns, ["program_activity_code"])
        pa_name = _optional_expr(columns, ["program_activity_name"])
        obj_code = _optional_expr(columns, ["object_class_code"])
        obj_name = _optional_expr(columns, ["object_class_name"])
        amount_expr = f"try_cast({_ident(amount)} AS DECIMAL(38, 2))"
        normalized_codes = sorted({_normalize_account_code(code) for code in account_codes})
        placeholders = ", ".join("?" for _ in normalized_codes)
        sql = f"""
            SELECT
                upper(trim(CAST({account_expr} AS VARCHAR))) AS account_code,
                {account_name} AS account_name,
                {pa_code} AS program_activity_code,
                {pa_name} AS program_activity_name,
                {obj_code} AS object_class_code,
                {obj_name} AS object_class_name,
                SUM({amount_expr}) AS outlay
            FROM read_parquet(?)
            WHERE {amount_expr} IS NOT NULL
              AND {amount_expr} <> 0
              AND upper(trim(CAST({account_expr} AS VARCHAR))) IN ({placeholders})
            GROUP BY 1, 2, 3, 4, 5, 6
            ORDER BY 1, 4, 6, 3, 5
        """
        result = connection.execute(
            sql,
            [[str(path) for path in paths], *normalized_codes],
        ).fetchall()
        return [
            _FileBRow(
                account_code=row[0],
                account_name=row[1],
                program_activity_code=row[2],
                program_activity_name=row[3],
                object_class_code=row[4],
                object_class_name=row[5],
                outlay=Decimal(str(row[6])),
            )
            for row in result
        ]
    finally:
        connection.close()


def _optional_expr(columns: dict[str, str], candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate in columns:
            return f"CAST({_ident(columns[candidate])} AS VARCHAR)"
    return "CAST(NULL AS VARCHAR)"


def _ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _normalize_account_code(value: str) -> str:
    text = str(value).strip().upper()
    if "-" not in text:
        return text
    agency, account = text.split("-", 1)
    return f"{agency.zfill(3)}-{account[-4:].zfill(4)}"


def _residual_child(account_code: str, amount: Decimal, note: str) -> WarehouseReceiptChild:
    return WarehouseReceiptChild(
        key=f"file_b:{account_code}:residual",
        label="Program/activity/object-class detail unavailable",
        node_type="residual",
        allocated_amount=money(amount),
        additive=True,
        residual=True,
        method="RESIDUAL_DETAIL_UNAVAILABLE",
        notes=[note],
    )
