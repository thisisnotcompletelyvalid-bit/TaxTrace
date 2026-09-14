from fastapi import HTTPException
from sqlalchemy import select

from apps.api.app.routers.data_v2 import dataset_release_objects, dataset_releases
from taxtrace.warehouse_v2.catalog import seed_catalog
from taxtrace.warehouse_v2.db_models import BulkObject, DatasetDefinition, DatasetRelease


def test_dataset_release_and_object_metadata_api(db_session) -> None:
    seed_catalog(db_session)
    dataset = db_session.scalar(
        select(DatasetDefinition).where(DatasetDefinition.key == "usaspending-file-d1-d2")
    )
    assert dataset is not None

    release = DatasetRelease(
        dataset_id=dataset.id,
        release_key="FY2022",
        reference_year=2022,
        reference_period="FY2022",
        status="READY",
        coverage_type="FEDERAL_AWARD",
        row_count=12,
        raw_bytes=1000,
        normalized_bytes=400,
        metadata_json={"native_data_classes": ["D1", "D2"]},
    )
    db_session.add(release)
    db_session.flush()
    db_session.add_all(
        [
            BulkObject(
                dataset_release_id=release.id,
                object_key="normalized/usaspending-file-d1-d2/FY2022/d1_contract_0001.parquet",
                storage_format="PARQUET",
                layer="normalized",
                partition_json={"fiscal_year": 2022, "data_class": "D1"},
                sha256="a" * 64,
                row_count=5,
                byte_count=150,
                metadata_json={"source_member": "contracts.csv"},
            ),
            BulkObject(
                dataset_release_id=release.id,
                object_key="normalized/usaspending-file-d1-d2/FY2022/d2_assistance_0002.parquet",
                storage_format="PARQUET",
                layer="normalized",
                partition_json={"fiscal_year": 2022, "data_class": "D2"},
                sha256="b" * 64,
                row_count=7,
                byte_count=250,
                metadata_json={"source_member": "assistance.csv"},
            ),
        ]
    )
    db_session.commit()

    releases = dataset_releases("usaspending-file-d1-d2", session=db_session)
    assert releases["dataset"]["grain"] == dataset.grain
    assert releases["releases"][0]["release_key"] == "FY2022"
    assert releases["releases"][0]["row_count"] == 12
    assert releases["releases"][0]["bulk_object_count"] == 2

    objects = dataset_release_objects(
        "usaspending-file-d1-d2",
        "FY2022",
        session=db_session,
    )
    assert objects["additive_across_objects"] is False
    assert [obj["row_count"] for obj in objects["objects"]] == [5, 7]
    assert {obj["partition"]["data_class"] for obj in objects["objects"]} == {"D1", "D2"}


def test_dataset_release_metadata_api_404s(db_session) -> None:
    seed_catalog(db_session)
    try:
        dataset_releases("does-not-exist", session=db_session)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("dataset_releases should reject an unknown dataset")

    try:
        dataset_release_objects("usaspending-file-d1-d2", "FY9999", session=db_session)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("dataset_release_objects should reject an unknown release")
