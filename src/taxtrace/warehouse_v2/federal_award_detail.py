from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from taxtrace.allocation.engine import money
from taxtrace.warehouse_v2.db_models import BulkObject, DatasetDefinition, DatasetRelease
from taxtrace.warehouse_v2.federal_receipt import _ident
from taxtrace.warehouse_v2.lake import LakeStore
from taxtrace.warehouse_v2.usaspending_award_crosswalk import PRIME_DATASET, SUBAWARD_DATASET


class AwardDetailCoverage(BaseModel):
    dataset_key: str
    release_key: str | None = None
    fiscal_year: int
    status: str
    full_fiscal_year: bool = False
    row_count: int | None = None
    object_count: int = 0
    object_keys: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PrimeAwardSummary(BaseModel):
    award_identity: str
    award_family: str
    transaction_count: int
    award_id_piid: str | None = None
    award_id_fain: str | None = None
    award_id_uri: str | None = None
    recipient_name: str | None = None
    recipient_uei: str | None = None
    description: str | None = None
    awarding_agency_name: str | None = None
    funding_agency_name: str | None = None
    award_type: str | None = None
    first_action_date: str | None = None
    last_action_date: str | None = None
    additive: bool = False
    personalized_amount: None = None
    notes: list[str] = Field(default_factory=list)


class SubawardDetailNode(BaseModel):
    key: str
    prime_award_identity: str
    award_family: str
    subaward_number: str | None = None
    subawardee_name: str | None = None
    subawardee_uei: str | None = None
    subaward_amount: Decimal | None = None
    description: str | None = None
    action_date: str | None = None
    additive: bool = False
    personalized_amount: None = None
    notes: list[str] = Field(default_factory=list)


class FederalAwardDetailResult(BaseModel):
    award_identity: str
    fiscal_year: int
    prime_coverage: AwardDetailCoverage
    subaward_coverage: AwardDetailCoverage
    prime: PrimeAwardSummary | None = None
    subawards: list[SubawardDetailNode] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FederalAwardDetailEngine:
    """Read D1/D2 and File F as non-additive detail behind one collapsed award identity.

    This service never creates personalized dollars. File C remains the personalized award
    projection. D1/D2 provide prime-award transaction/recipient attributes after identity
    collapse, and File F is downstream subaward context. Querying each grain independently by
    the canonical identity avoids the many-to-many fan-out created by raw C↔D↔F row joins.
    """

    def __init__(self, lake: LakeStore | None = None):
        self.lake = lake or LakeStore()

    def get(
        self,
        session: Session,
        *,
        fiscal_year: int,
        award_identity: str,
    ) -> FederalAwardDetailResult:
        identity = award_identity.strip()
        if not identity:
            raise ValueError("award_identity must not be blank")

        prime_coverage, prime_objects = self._load_objects(session, PRIME_DATASET, fiscal_year)
        subaward_coverage, subaward_objects = self._load_objects(
            session, SUBAWARD_DATASET, fiscal_year
        )

        prime_summaries: list[PrimeAwardSummary] = []
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
                if paths:
                    summary = _query_prime(paths, key_column, identity, family)
                    if summary is not None:
                        prime_summaries.append(summary)

        warnings: list[str] = []
        prime: PrimeAwardSummary | None = None
        if len(prime_summaries) == 1:
            prime = prime_summaries[0]
        elif len(prime_summaries) > 1:
            warnings.append(
                "The canonical award identity matched both D1 and D2 full-year grains. TaxTrace refuses to collapse conflicting award families into one prime summary."
            )

        subawards: list[SubawardDetailNode] = []
        if subaward_coverage.status == "READY":
            for family in ("contract", "assistance"):
                paths = [
                    self.lake.root / obj.object_key
                    for obj in subaward_objects
                    if str((obj.partition_json or {}).get("award_family", "")).lower() == family
                ]
                for path in paths:
                    subawards.extend(_query_subawards(path, identity, family))

        if prime_coverage.status != "READY":
            warnings.append(
                "No complete local full-year D1/D2 release is available for prime-award enrichment."
            )
        if subaward_coverage.status != "READY":
            warnings.append(
                "No complete local full-year File F release is available for subaward drilldown."
            )
        warnings.append(
            "D1/D2 transaction rows and File F subawards are descriptive drilldown grains. Their monetary fields are not added to the personalized File C allocation."
        )
        warnings.append(
            "File F is downstream of the prime award. Subaward amounts describe distribution within a prime award and are never treated as additional federal spending."
        )

        return FederalAwardDetailResult(
            award_identity=identity,
            fiscal_year=fiscal_year,
            prime_coverage=prime_coverage,
            subaward_coverage=subaward_coverage,
            prime=prime,
            subawards=sorted(
                subawards,
                key=lambda row: (
                    row.award_family,
                    row.subaward_number or "",
                    row.subawardee_name or "",
                ),
            ),
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
            notes=[],
        )
        if not objects:
            coverage.status = "NO_PARQUET_OBJECTS"
            coverage.notes.append("The full-year release has no normalized Parquet objects registered.")
            return coverage, []
        missing = [
            str(self.lake.root / obj.object_key)
            for obj in objects
            if not (self.lake.root / obj.object_key).exists()
        ]
        if missing:
            coverage.status = "OBJECTS_NOT_LOCAL"
            coverage.notes.append(
                "Release metadata is present but one or more normalized award lake objects are not available on this runtime."
            )
            return coverage, []
        return coverage, list(objects)


def _query_prime(
    paths: list[Path],
    key_column: str,
    award_identity: str,
    award_family: str,
) -> PrimeAwardSummary | None:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for Warehouse V2 federal award detail queries") from exc

    connection = duckdb.connect()
    try:
        connection.execute("SELECT * FROM read_parquet(?) LIMIT 0", [[str(path) for path in paths]])
        columns = {str(item[0]).lower(): str(item[0]) for item in connection.description}
        key = columns.get(key_column)
        if key is None:
            raise ValueError(f"{award_family} prime-award data is missing canonical key {key_column!r}")

        sql = f"""
            SELECT
                count(*) AS transaction_count,
                {_aggregate_optional(columns, ['award_id_piid'])} AS award_id_piid,
                {_aggregate_optional(columns, ['award_id_fain'])} AS award_id_fain,
                {_aggregate_optional(columns, ['award_id_uri'])} AS award_id_uri,
                {_aggregate_optional(columns, ['recipient_name', 'recipient_name_raw'])} AS recipient_name,
                {_aggregate_optional(columns, ['recipient_uei'])} AS recipient_uei,
                {_aggregate_optional(columns, ['prime_award_base_transaction_description', 'award_description', 'transaction_description'])} AS description,
                {_aggregate_optional(columns, ['awarding_agency_name'])} AS awarding_agency_name,
                {_aggregate_optional(columns, ['funding_agency_name'])} AS funding_agency_name,
                {_aggregate_optional(columns, ['award_type'])} AS award_type,
                {_date_aggregate(columns, ['action_date'], 'min')} AS first_action_date,
                {_date_aggregate(columns, ['action_date'], 'max')} AS last_action_date
            FROM read_parquet(?)
            WHERE nullif(trim(CAST({_ident(key)} AS VARCHAR)), '') = ?
        """
        row = connection.execute(sql, [[str(path) for path in paths], award_identity]).fetchone()
        if row is None or int(row[0] or 0) == 0:
            return None
        return PrimeAwardSummary(
            award_identity=award_identity,
            award_family=award_family,
            transaction_count=int(row[0]),
            award_id_piid=row[1],
            award_id_fain=row[2],
            award_id_uri=row[3],
            recipient_name=row[4],
            recipient_uei=row[5],
            description=row[6],
            awarding_agency_name=row[7],
            funding_agency_name=row[8],
            award_type=row[9],
            first_action_date=row[10],
            last_action_date=row[11],
            notes=[
                "D1/D2 rows were queried only after the File C identity was collapsed; transaction count is descriptive and contributes no additional personalized dollars."
            ],
        )
    finally:
        connection.close()


def _query_subawards(path: Path, award_identity: str, award_family: str) -> list[SubawardDetailNode]:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for Warehouse V2 federal subaward queries") from exc

    connection = duckdb.connect()
    try:
        connection.execute("SELECT * FROM read_parquet(?) LIMIT 0", [str(path)])
        columns = {str(item[0]).lower(): str(item[0]) for item in connection.description}
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
        sql = f"""
            SELECT DISTINCT
                {number} AS subaward_number,
                {name} AS subawardee_name,
                {uei} AS subawardee_uei,
                {amount} AS subaward_amount,
                {description} AS description,
                {action_date} AS action_date
            FROM read_parquet(?)
            WHERE nullif(trim(CAST({_ident(key)} AS VARCHAR)), '') = ?
            ORDER BY 1 NULLS LAST, 2 NULLS LAST, 4 NULLS LAST
        """
        rows = connection.execute(sql, [str(path), award_identity]).fetchall()
        result: list[SubawardDetailNode] = []
        for index, row in enumerate(rows, start=1):
            subaward_number = row[0]
            result.append(
                SubawardDetailNode(
                    key=f"file_f:{award_identity}:{award_family}:{subaward_number or index}",
                    prime_award_identity=award_identity,
                    award_family=award_family,
                    subaward_number=subaward_number,
                    subawardee_name=row[1],
                    subawardee_uei=row[2],
                    subaward_amount=money(Decimal(str(row[3]))) if row[3] is not None else None,
                    description=row[4],
                    action_date=row[5],
                    notes=[
                        "This File F amount is downstream descriptive context and is not an additional federal expenditure or personalized tax allocation."
                    ],
                )
            )
        return result
    finally:
        connection.close()


def _aggregate_optional(columns: dict[str, str], candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate in columns:
            ident = _ident(columns[candidate])
            return f"min(nullif(trim(CAST({ident} AS VARCHAR)), ''))"
    return "CAST(NULL AS VARCHAR)"


def _date_aggregate(columns: dict[str, str], candidates: list[str], aggregate: str) -> str:
    for candidate in candidates:
        if candidate in columns:
            ident = _ident(columns[candidate])
            return f"CAST({aggregate}(try_cast({ident} AS DATE)) AS VARCHAR)"
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
