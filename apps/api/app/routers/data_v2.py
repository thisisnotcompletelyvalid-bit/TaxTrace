from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from taxtrace.database import get_db
from taxtrace.db_models import Jurisdiction
from taxtrace.warehouse_v2.catalog import load_catalog
from taxtrace.warehouse_v2.db_models import (
    BulkObject,
    CoverageRecord,
    DatasetDefinition,
    DatasetRelease,
    DetailedSpendFact,
    FinanceClassification,
    GovernmentFinanceFact,
    GovernmentIdentifier,
)

router = APIRouter(prefix="/data", tags=["data-warehouse-v2"])


@router.get("/catalog")
def catalog() -> dict:
    return load_catalog()


@router.get("/stats")
def stats(session: Session = Depends(get_db)) -> dict:
    def count(model) -> int:
        return session.scalar(select(func.count(model.id))) or 0

    return {
        "datasets": count(DatasetDefinition),
        "releases": count(DatasetRelease),
        "government_identifiers": count(GovernmentIdentifier),
        "finance_classifications": count(FinanceClassification),
        "government_finance_facts": count(GovernmentFinanceFact),
        "detailed_spend_facts": count(DetailedSpendFact),
        "coverage_records": count(CoverageRecord),
        "bulk_objects": count(BulkObject),
    }


@router.get("/datasets/{dataset_key}/releases")
def dataset_releases(
    dataset_key: str,
    session: Session = Depends(get_db),
) -> dict:
    dataset = session.scalar(
        select(DatasetDefinition).where(DatasetDefinition.key == dataset_key)
    )
    if dataset is None:
        raise HTTPException(404, "Dataset not found")

    releases = session.scalars(
        select(DatasetRelease)
        .where(DatasetRelease.dataset_id == dataset.id)
        .order_by(DatasetRelease.reference_year.desc(), DatasetRelease.release_key.desc())
    ).all()
    object_counts = dict(
        session.execute(
            select(BulkObject.dataset_release_id, func.count(BulkObject.id))
            .where(BulkObject.dataset_release_id.in_([release.id for release in releases]))
            .group_by(BulkObject.dataset_release_id)
        ).all()
    ) if releases else {}

    return {
        "dataset": {
            "key": dataset.key,
            "name": dataset.name,
            "authority": dataset.authority,
            "grain": dataset.grain,
            "coverage_level": dataset.coverage_level,
            "ingestion_status": dataset.ingestion_status,
            "source_url": dataset.source_url,
            "documentation_url": dataset.documentation_url,
            "metadata": dataset.metadata_json,
        },
        "releases": [
            {
                "release_key": release.release_key,
                "reference_year": release.reference_year,
                "reference_period": release.reference_period,
                "status": release.status,
                "coverage_type": release.coverage_type,
                "row_count": release.row_count,
                "government_count": release.government_count,
                "classification_count": release.classification_count,
                "raw_bytes": release.raw_bytes,
                "normalized_bytes": release.normalized_bytes,
                "ingested_at": release.ingested_at,
                "bulk_object_count": object_counts.get(release.id, 0),
                "metadata": release.metadata_json,
            }
            for release in releases
        ],
    }


@router.get("/datasets/{dataset_key}/releases/{release_key}/objects")
def dataset_release_objects(
    dataset_key: str,
    release_key: str,
    session: Session = Depends(get_db),
) -> dict:
    row = session.execute(
        select(DatasetDefinition, DatasetRelease)
        .join(DatasetRelease, DatasetRelease.dataset_id == DatasetDefinition.id)
        .where(
            DatasetDefinition.key == dataset_key,
            DatasetRelease.release_key == release_key,
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Dataset release not found")
    dataset, release = row

    objects = session.scalars(
        select(BulkObject)
        .where(BulkObject.dataset_release_id == release.id)
        .order_by(BulkObject.layer, BulkObject.object_key)
    ).all()
    return {
        "dataset_key": dataset.key,
        "release_key": release.release_key,
        "grain": dataset.grain,
        "additive_across_objects": False,
        "warning": (
            "Lake objects preserve native source partitions and schemas. Do not sum objects "
            "across grains or families unless an explicit additive partition says it is safe."
        ),
        "objects": [
            {
                "object_key": obj.object_key,
                "storage_format": obj.storage_format,
                "layer": obj.layer,
                "partition": obj.partition_json,
                "sha256": obj.sha256,
                "row_count": obj.row_count,
                "byte_count": obj.byte_count,
                "metadata": obj.metadata_json,
            }
            for obj in objects
        ],
    }


@router.get("/governments/search")
def government_search(
    q: str = Query(min_length=2),
    limit: int = Query(default=25, ge=1, le=100),
    session: Session = Depends(get_db),
) -> dict:
    pattern = f"%{q.strip()}%"
    rows = session.execute(
        select(Jurisdiction, GovernmentIdentifier.scheme, GovernmentIdentifier.value)
        .outerjoin(GovernmentIdentifier, GovernmentIdentifier.jurisdiction_id == Jurisdiction.id)
        .where(or_(Jurisdiction.name.ilike(pattern), Jurisdiction.code.ilike(pattern), GovernmentIdentifier.value.ilike(pattern)))
        .order_by(Jurisdiction.name)
        .limit(limit * 5)
    ).all()
    results: dict[int, dict] = {}
    for jurisdiction, scheme, value in rows:
        entry = results.setdefault(jurisdiction.id, {
            "id": jurisdiction.id,
            "code": jurisdiction.code,
            "name": jurisdiction.name,
            "level": jurisdiction.level.value,
            "parent_id": jurisdiction.parent_id,
            "identifiers": [],
        })
        if scheme and value:
            entry["identifiers"].append({"scheme": scheme, "value": value})
        if len(results) >= limit:
            break
    return {"results": list(results.values())}


@router.get("/governments/{government_id}/coverage")
def government_coverage(government_id: int, session: Session = Depends(get_db)) -> dict:
    jurisdiction = session.get(Jurisdiction, government_id)
    if jurisdiction is None:
        raise HTTPException(404, "Government not found")
    rows = session.execute(
        select(CoverageRecord, DatasetRelease, DatasetDefinition)
        .join(DatasetRelease, CoverageRecord.dataset_release_id == DatasetRelease.id)
        .join(DatasetDefinition, DatasetRelease.dataset_id == DatasetDefinition.id)
        .where(CoverageRecord.jurisdiction_id == government_id)
        .order_by(CoverageRecord.fiscal_year.desc(), DatasetDefinition.priority)
    ).all()
    return {
        "government": {"id": jurisdiction.id, "code": jurisdiction.code, "name": jurisdiction.name, "level": jurisdiction.level.value},
        "coverage": [{
            "dataset_key": dataset.key,
            "dataset_name": dataset.name,
            "release": release.release_key,
            "fiscal_year": coverage.fiscal_year,
            "grain": coverage.grain,
            "completeness": coverage.completeness,
            "record_count": coverage.record_count,
            "classification_count": coverage.classification_count,
            "quality_grade": coverage.quality_grade,
            "notes": coverage.notes,
        } for coverage, release, dataset in rows],
    }


@router.get("/governments/{government_id}/finance")
def government_finance(
    government_id: int,
    fiscal_year: int | None = None,
    flow_type: str | None = None,
    function_code: str | None = None,
    object_type: str | None = None,
    limit: int = Query(default=1000, ge=1, le=10000),
    session: Session = Depends(get_db),
) -> dict:
    jurisdiction = session.get(Jurisdiction, government_id)
    if jurisdiction is None:
        raise HTTPException(404, "Government not found")
    if fiscal_year is None:
        fiscal_year = session.scalar(select(func.max(GovernmentFinanceFact.fiscal_year)).where(GovernmentFinanceFact.jurisdiction_id == government_id))
    if fiscal_year is None:
        return {"government": {"id": jurisdiction.id, "code": jurisdiction.code, "name": jurisdiction.name}, "fiscal_year": None, "rows": [], "additive": False}

    query = (
        select(GovernmentFinanceFact, FinanceClassification, DatasetRelease, DatasetDefinition)
        .join(FinanceClassification, GovernmentFinanceFact.classification_id == FinanceClassification.id)
        .join(DatasetRelease, GovernmentFinanceFact.dataset_release_id == DatasetRelease.id)
        .join(DatasetDefinition, DatasetRelease.dataset_id == DatasetDefinition.id)
        .where(GovernmentFinanceFact.jurisdiction_id == government_id, GovernmentFinanceFact.fiscal_year == fiscal_year)
    )
    if flow_type:
        query = query.where(FinanceClassification.flow_type == flow_type.upper())
    if function_code:
        query = query.where(FinanceClassification.function_code == function_code)
    if object_type:
        query = query.where(FinanceClassification.object_type.ilike(f"%{object_type}%"))
    rows = session.execute(query.order_by(FinanceClassification.flow_type, FinanceClassification.code).limit(limit)).all()
    return {
        "government": {"id": jurisdiction.id, "code": jurisdiction.code, "name": jurisdiction.name, "level": jurisdiction.level.value},
        "fiscal_year": fiscal_year,
        "additive": False,
        "warning": "Native Census item-code rows can contain rollups and components. Do not sum this result set unless a future partition explicitly marks it additive.",
        "rows": [{
            "item_code": classification.code,
            "item_name": classification.name,
            "flow_type": classification.flow_type,
            "object_type": classification.object_type,
            "function_code": classification.function_code,
            "function_name": classification.function_name,
            "amount": str(fact.amount),
            "metric": fact.metric,
            "status": fact.status,
            "is_imputed": fact.is_imputed,
            "origin_code": fact.origin_code,
            "dataset_key": dataset.key,
            "release": release.release_key,
            "coverage_type": release.coverage_type,
        } for fact, classification, release, dataset in rows],
    }


@router.get("/governments/{government_id}/detail")
def government_detail(
    government_id: int,
    fiscal_year: int | None = None,
    q: str | None = None,
    limit: int = Query(default=250, ge=1, le=5000),
    session: Session = Depends(get_db),
) -> dict:
    jurisdiction = session.get(Jurisdiction, government_id)
    if jurisdiction is None:
        raise HTTPException(404, "Government not found")
    query = select(DetailedSpendFact).where(DetailedSpendFact.jurisdiction_id == government_id)
    if fiscal_year is not None:
        query = query.where(DetailedSpendFact.fiscal_year == fiscal_year)
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(
            DetailedSpendFact.department.ilike(pattern), DetailedSpendFact.fund.ilike(pattern),
            DetailedSpendFact.account.ilike(pattern), DetailedSpendFact.program.ilike(pattern),
            DetailedSpendFact.activity.ilike(pattern), DetailedSpendFact.object_class.ilike(pattern),
            DetailedSpendFact.project.ilike(pattern), DetailedSpendFact.vendor.ilike(pattern),
            DetailedSpendFact.recipient.ilike(pattern), DetailedSpendFact.award_id.ilike(pattern),
            DetailedSpendFact.description.ilike(pattern),
        ))
    rows = session.scalars(query.order_by(DetailedSpendFact.id).limit(limit)).all()
    return {
        "government": {"id": jurisdiction.id, "code": jurisdiction.code, "name": jurisdiction.name},
        "rows": [{
            "fiscal_year": row.fiscal_year, "amount": str(row.amount), "metric": row.metric,
            "department": row.department, "fund": row.fund, "account": row.account,
            "program": row.program, "activity": row.activity, "object_class": row.object_class,
            "project": row.project, "vendor": row.vendor, "recipient": row.recipient,
            "award_id": row.award_id, "description": row.description, "native_key": row.native_key,
        } for row in rows],
    }
