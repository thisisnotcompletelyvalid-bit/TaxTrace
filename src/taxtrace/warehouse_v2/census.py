from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from itertools import islice
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from taxtrace.config import get_settings
from taxtrace.db_models import Jurisdiction
from taxtrace.enums import JurisdictionLevel
from taxtrace.warehouse_v2.catalog import get_source, seed_catalog
from taxtrace.warehouse_v2.census_codes import GOV_TYPE, STATE_AREA, classify_item_code
from taxtrace.warehouse_v2.db_models import (
    CoverageRecord,
    DatasetDefinition,
    DatasetRelease,
    FinanceClassification,
    GovernmentFinanceFact,
    GovernmentIdentifier,
)
from taxtrace.warehouse_v2.download import stream_download
from taxtrace.warehouse_v2.lake import LakeStore


@dataclass(frozen=True)
class CensusFinanceRecord:
    government_id: str
    item_code: str
    amount_thousands: Decimal
    survey_year: str | None = None
    year_of_data: str | None = None
    origin_code: str | None = None

    @property
    def amount_dollars(self) -> Decimal:
        return self.amount_thousands * Decimal("1000")


@dataclass(frozen=True)
class CensusGovernmentUnit:
    government_id: str
    name: str


def _money(value: str) -> Decimal | None:
    try:
        return Decimal(value.strip().replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def _valid_gov_id(value: str) -> bool:
    return len(value) >= 12 and value[:2].isdigit() and value[2:3] in GOV_TYPE and value.isalnum()


def parse_finance_line(line: str) -> CensusFinanceRecord | None:
    """Parse the documented 35-character Census finance record and common older variants."""
    raw = line.rstrip("\r\n")
    layouts = []
    if len(raw) >= 35:
        layouts.append((14, 14, 17, 17, 29, raw[29:31], raw[31:33], raw[33:35]))
    if len(raw) >= 31:
        layouts.append((14, 14, 17, 17, 29, raw[29:31], None, None))
    if len(raw) >= 29:
        layouts.append((14, 14, 17, 17, 29, None, None, None))
    if len(raw) >= 27:
        layouts.append((12, 12, 15, 15, 27, None, None, None))
    for gid_end, item_start, item_end, amount_start, amount_end, survey, data_year, origin in layouts:
        gid = raw[:gid_end].strip()
        item = raw[item_start:item_end].strip().upper()
        amount = _money(raw[amount_start:amount_end])
        if _valid_gov_id(gid) and re.fullmatch(r"[A-Z0-9]{3}", item) and amount is not None:
            return CensusFinanceRecord(
                government_id=gid,
                item_code=item,
                amount_thousands=amount,
                survey_year=survey.strip() if survey else None,
                year_of_data=data_year.strip() if data_year else None,
                origin_code=origin.strip() if origin else None,
            )
    return None


def parse_government_unit_line(line: str) -> CensusGovernmentUnit | None:
    """Parse the Census government-ID layout: 14-char ID + 64-char government name."""
    raw = line.rstrip("\r\n")
    if len(raw) < 78:
        return None
    gid = raw[:14].strip()
    name = raw[14:78].strip()
    if not _valid_gov_id(gid) or not name:
        return None
    return CensusGovernmentUnit(gid, name)


def _dict_columns(fieldnames: list[str]) -> dict[str, str]:
    return {re.sub(r"[^a-z0-9]", "", name.lower()): name for name in fieldnames}


def _find_column(columns: dict[str, str], *aliases: str) -> str | None:
    for alias in aliases:
        key = re.sub(r"[^a-z0-9]", "", alias.lower())
        if key in columns:
            return columns[key]
    return None


def _iter_delimited_finance(handle: io.TextIOBase):
    sample = handle.read(8192)
    handle.seek(0)
    reader = csv.DictReader(handle, delimiter="|" if sample.count("|") > sample.count(",") else ",")
    if not reader.fieldnames:
        return
    columns = _dict_columns(reader.fieldnames)
    gid_col = _find_column(columns, "governmentid", "governmentcode", "govid", "gid", "id")
    item_col = _find_column(columns, "itemcode", "item")
    amount_col = _find_column(columns, "amount", "value")
    if not gid_col or not item_col or not amount_col:
        return
    survey_col = _find_column(columns, "surveyyear", "year")
    data_col = _find_column(columns, "yearofdata")
    origin_col = _find_column(columns, "origin", "source")
    for row in reader:
        gid = str(row.get(gid_col, "")).strip()
        item = str(row.get(item_col, "")).strip().upper()
        amount = _money(str(row.get(amount_col, "")))
        if not _valid_gov_id(gid) or not re.fullmatch(r"[A-Z0-9]{3}", item) or amount is None:
            continue
        yield CensusFinanceRecord(
            gid,
            item,
            amount,
            str(row.get(survey_col, "")).strip() if survey_col else None,
            str(row.get(data_col, "")).strip() if data_col else None,
            str(row.get(origin_col, "")).strip() if origin_col else None,
        )


def iter_finance_records(zip_path: Path):
    """Stream finance records from an official Census ZIP without loading the archive into RAM."""
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir() or Path(member.filename).suffix.lower() in {".pdf", ".xlsx", ".xls", ".doc", ".docx"}:
                continue
            with archive.open(member) as binary:
                handle = io.TextIOWrapper(binary, encoding="utf-8-sig", errors="replace", newline="")
                first = list(islice(handle, 50))
                if not first:
                    continue
                header = first[0].lower()
                if ("," in header or "|" in header) and "item" in header and ("amount" in header or "value" in header):
                    handle.seek(0)
                    yield from _iter_delimited_finance(handle)
                    continue
                parsed_first = [parse_finance_line(line) for line in first]
                if sum(record is not None for record in parsed_first) < max(1, len(first) // 2):
                    continue
                for record in parsed_first:
                    if record is not None:
                        yield record
                for line in handle:
                    record = parse_finance_line(line)
                    if record is not None:
                        yield record


def _iter_delimited_units(handle: io.TextIOBase):
    sample = handle.read(8192)
    handle.seek(0)
    reader = csv.DictReader(handle, delimiter="|" if sample.count("|") > sample.count(",") else ",")
    if not reader.fieldnames:
        return
    columns = _dict_columns(reader.fieldnames)
    gid_col = _find_column(columns, "governmentunitcode", "governmentunitid", "governmentcode", "governmentid", "govid", "gid")
    name_col = _find_column(columns, "governmentname", "governmentunitname", "govname", "unitname", "name")
    if not gid_col or not name_col:
        return
    for row in reader:
        gid = str(row.get(gid_col, "")).strip().removesuffix(".0")
        name = str(row.get(name_col, "")).strip()
        if _valid_gov_id(gid) and name:
            yield CensusGovernmentUnit(gid, name)


def iter_government_units(zip_path: Path):
    """Read the GMAF/Government Units archive in fixed-width, delimited, or workbook form."""
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            suffix = Path(member.filename).suffix.lower()
            if suffix in {".xlsx", ".xls"}:
                workbook = pd.ExcelFile(io.BytesIO(archive.read(member)), engine="openpyxl")
                for sheet in workbook.sheet_names:
                    frame = pd.read_excel(workbook, sheet_name=sheet, dtype=object)
                    if frame.empty:
                        continue
                    columns = _dict_columns([str(column) for column in frame.columns])
                    gid_col = _find_column(columns, "governmentunitcode", "governmentunitid", "governmentcode", "governmentid", "govid", "gid")
                    name_col = _find_column(columns, "governmentname", "governmentunitname", "govname", "unitname", "name")
                    if not gid_col or not name_col:
                        continue
                    for _, row in frame.iterrows():
                        gid_value = row.get(gid_col)
                        name_value = row.get(name_col)
                        if pd.isna(gid_value) or pd.isna(name_value):
                            continue
                        gid = str(int(gid_value)) if isinstance(gid_value, float) and gid_value.is_integer() else str(gid_value).strip().removesuffix(".0")
                        name = str(name_value).strip()
                        if _valid_gov_id(gid) and name:
                            yield CensusGovernmentUnit(gid, name)
                continue
            if suffix in {".pdf", ".doc", ".docx", ".png", ".jpg"}:
                continue
            with archive.open(member) as binary:
                handle = io.TextIOWrapper(binary, encoding="utf-8-sig", errors="replace", newline="")
                first = list(islice(handle, 25))
                if not first:
                    continue
                header = first[0].lower()
                if ("," in header or "|" in header) and ("government" in header or "gov" in header) and "name" in header:
                    handle.seek(0)
                    yield from _iter_delimited_units(handle)
                    continue
                parsed = [parse_government_unit_line(line) for line in first]
                if sum(row is not None for row in parsed) < max(1, len(first) // 2):
                    continue
                for row in parsed:
                    if row is not None:
                        yield row
                for line in handle:
                    row = parse_government_unit_line(line)
                    if row is not None:
                        yield row


def _state(gid: str) -> tuple[str | None, str | None]:
    return STATE_AREA.get(gid[:2], (None, None))


def _level(gid: str) -> JurisdictionLevel:
    return JurisdictionLevel(GOV_TYPE.get(gid[2:3], "SPECIAL_DISTRICT"))


def _states(session: Session) -> dict[str, Jurisdiction]:
    result: dict[str, Jurisdiction] = {}
    for _, (abbreviation, name) in STATE_AREA.items():
        row = session.scalar(select(Jurisdiction).where(Jurisdiction.code == abbreviation))
        if row is None:
            row = Jurisdiction(code=abbreviation, name=name, level=JurisdictionLevel.STATE)
            session.add(row)
    session.flush()
    for row in session.scalars(select(Jurisdiction).where(Jurisdiction.level == JurisdictionLevel.STATE)):
        result[row.code] = row
    return result


def _dataset(session: Session, key: str) -> DatasetDefinition:
    seed_catalog(session)
    row = session.scalar(select(DatasetDefinition).where(DatasetDefinition.key == key))
    if row is None:
        raise RuntimeError(f"Dataset {key} is not in the source catalog")
    return row


def _release(session: Session, definition: DatasetDefinition, key: str, year: int, coverage: str) -> DatasetRelease:
    row = session.scalar(select(DatasetRelease).where(DatasetRelease.dataset_id == definition.id, DatasetRelease.release_key == key))
    if row is None:
        row = DatasetRelease(
            dataset_id=definition.id,
            release_key=key,
            reference_year=year,
            reference_period=str(year),
            status="INGESTING",
            coverage_type=coverage,
        )
        session.add(row)
        session.flush()
    else:
        row.status = "INGESTING"
    return row


def ingest_government_units_zip(session: Session, zip_path: Path) -> dict[str, int]:
    definition = _dataset(session, "census-government-units-2022")
    release = _release(session, definition, "2022", 2022, "CENSUS")
    state_rows = _states(session)
    existing = {
        value: jurisdiction_id
        for value, jurisdiction_id in session.execute(
            select(GovernmentIdentifier.value, GovernmentIdentifier.jurisdiction_id).where(GovernmentIdentifier.scheme == "CENSUS_GOV_ID")
        )
    }
    seen: set[str] = set()
    created = 0
    batch: list[tuple[CensusGovernmentUnit, Jurisdiction]] = []

    def flush_batch() -> None:
        nonlocal created
        if not batch:
            return
        session.add_all([jurisdiction for _, jurisdiction in batch])
        session.flush()
        session.add_all([
            GovernmentIdentifier(
                jurisdiction_id=jurisdiction.id,
                scheme="CENSUS_GOV_ID",
                value=unit.government_id,
                metadata_json={"state_area_code": unit.government_id[:2]},
            )
            for unit, jurisdiction in batch
        ])
        for unit, jurisdiction in batch:
            existing[unit.government_id] = jurisdiction.id
        created += len(batch)
        session.commit()
        batch.clear()

    for unit in iter_government_units(zip_path):
        if unit.government_id in seen:
            continue
        seen.add(unit.government_id)
        if unit.government_id in existing:
            jurisdiction = session.get(Jurisdiction, existing[unit.government_id])
            if jurisdiction is not None and jurisdiction.name.startswith("Census government "):
                jurisdiction.name = unit.name
            continue
        abbreviation, _ = _state(unit.government_id)
        level = _level(unit.government_id)
        if level == JurisdictionLevel.STATE and abbreviation in state_rows:
            jurisdiction = state_rows[abbreviation]
            jurisdiction.name = unit.name
            session.add(GovernmentIdentifier(jurisdiction_id=jurisdiction.id, scheme="CENSUS_GOV_ID", value=unit.government_id, metadata_json={"state_area_code": unit.government_id[:2]}))
            existing[unit.government_id] = jurisdiction.id
            continue
        jurisdiction = Jurisdiction(
            code=f"CENSUS-GOV-{unit.government_id}",
            name=unit.name,
            level=level,
            parent_id=state_rows.get(abbreviation).id if abbreviation in state_rows else None,
        )
        batch.append((unit, jurisdiction))
        if len(batch) >= 5000:
            flush_batch()
    flush_batch()
    session.commit()
    release.status = "READY"
    release.row_count = len(seen)
    release.government_count = len(seen)
    release.raw_bytes = zip_path.stat().st_size
    release.ingested_at = datetime.now(timezone.utc)
    release.metadata_json = {"source_file": zip_path.name, "new_jurisdictions": created}
    session.commit()
    LakeStore().register_file(session, dataset_release_id=release.id, path=zip_path, layer="raw", storage_format="ZIP", row_count=len(seen), metadata={"official_bulk_file": True})
    return {"rows": len(seen), "governments": len(seen), "created": created}


def _classification(session: Session, code: str, cache: dict[str, int]) -> int:
    if code in cache:
        return cache[code]
    row = session.scalar(select(FinanceClassification).where(FinanceClassification.scheme == "CENSUS_GOV_FINANCE", FinanceClassification.code == code))
    if row is None:
        parsed = classify_item_code(code)
        row = FinanceClassification(
            scheme="CENSUS_GOV_FINANCE",
            code=parsed.code,
            name=parsed.name,
            flow_type=parsed.flow_type,
            object_type=parsed.object_type,
            function_code=parsed.function_code,
            function_name=parsed.function_name,
            additive_partition=None,
            description="Native Census government-finance item code; non-additive until official summary formulas are loaded.",
            metadata_json={"native": True, "raw_rows_additive": False},
        )
        session.add(row)
        session.flush()
    cache[code] = row.id
    return row.id


def _unknown_government(session: Session, gid: str, states: dict[str, Jurisdiction]) -> int:
    identifier = session.scalar(select(GovernmentIdentifier).where(GovernmentIdentifier.scheme == "CENSUS_GOV_ID", GovernmentIdentifier.value == gid))
    if identifier is not None:
        return identifier.jurisdiction_id
    abbreviation, _ = _state(gid)
    row = Jurisdiction(
        code=f"CENSUS-GOV-{gid}",
        name=f"Census government {gid}",
        level=_level(gid),
        parent_id=states.get(abbreviation).id if abbreviation in states else None,
    )
    session.add(row)
    session.flush()
    session.add(GovernmentIdentifier(jurisdiction_id=row.id, scheme="CENSUS_GOV_ID", value=gid, metadata_json={"placeholder_name": True}))
    session.flush()
    return row.id


def _imputed(record: CensusFinanceRecord) -> bool | None:
    value = (record.year_of_data or "").upper()
    origin = (record.origin_code or "").upper()
    if value.endswith("R") or origin.startswith("R"):
        return False
    if any(character.isalpha() for character in value):
        return True
    return None


def inspect_finance_zip(zip_path: Path, *, max_records: int | None = None) -> dict[str, int]:
    count = 0
    governments: set[str] = set()
    codes: set[str] = set()
    for record in iter_finance_records(zip_path):
        count += 1
        governments.add(record.government_id)
        codes.add(record.item_code)
        if max_records and count >= max_records:
            break
    return {"records": count, "governments": len(governments), "item_codes": len(codes)}


def ingest_finance_zip(
    session: Session,
    zip_path: Path,
    *,
    year: int,
    coverage_type: str,
    dataset_key: str | None = None,
    batch_size: int = 10000,
) -> dict[str, int]:
    dataset_key = dataset_key or f"census-gov-finance-{year}"
    definition = _dataset(session, dataset_key)
    release = _release(session, definition, f"FY{year}", year, coverage_type)
    release.raw_bytes = zip_path.stat().st_size
    session.execute(delete(GovernmentFinanceFact).where(GovernmentFinanceFact.dataset_release_id == release.id))
    session.execute(delete(CoverageRecord).where(CoverageRecord.dataset_release_id == release.id))
    session.commit()

    identifiers = {
        value: jurisdiction_id
        for value, jurisdiction_id in session.execute(
            select(GovernmentIdentifier.value, GovernmentIdentifier.jurisdiction_id).where(
                GovernmentIdentifier.scheme == "CENSUS_GOV_ID"
            )
        )
    }
    states = _states(session)
    classes = {
        code: classification_id
        for code, classification_id in session.execute(
            select(FinanceClassification.code, FinanceClassification.id).where(
                FinanceClassification.scheme == "CENSUS_GOV_FINANCE"
            )
        )
    }
    pending: list[dict] = []
    count = 0

    def flush() -> None:
        if pending:
            session.execute(insert(GovernmentFinanceFact), pending)
            session.commit()
            pending.clear()

    for record in iter_finance_records(zip_path):
        jurisdiction_id = identifiers.get(record.government_id)
        if jurisdiction_id is None:
            jurisdiction_id = _unknown_government(session, record.government_id, states)
            identifiers[record.government_id] = jurisdiction_id
        classification_id = _classification(session, record.item_code, classes)
        pending.append({
            "jurisdiction_id": jurisdiction_id,
            "dataset_release_id": release.id,
            "classification_id": classification_id,
            "fiscal_year": year,
            "amount": record.amount_dollars,
            "status": "ACTUAL",
            "metric": "REPORTED_AMOUNT",
            "native_key": record.item_code,
            "is_imputed": _imputed(record),
            "origin_code": record.origin_code,
            "metadata_json": {"amount_unit_source": "thousands_of_dollars", "survey_year": record.survey_year, "year_of_data": record.year_of_data},
        })
        count += 1
        if len(pending) >= batch_size:
            flush()
    flush()

    grouped = session.execute(
        select(GovernmentFinanceFact.jurisdiction_id, func.count(GovernmentFinanceFact.id), func.count(func.distinct(GovernmentFinanceFact.classification_id)))
        .where(GovernmentFinanceFact.dataset_release_id == release.id)
        .group_by(GovernmentFinanceFact.jurisdiction_id)
    ).all()
    session.add_all([
        CoverageRecord(
            jurisdiction_id=jurisdiction_id,
            dataset_release_id=release.id,
            fiscal_year=year,
            grain="government_unit_item_code",
            completeness=coverage_type,
            record_count=record_count,
            classification_count=classification_count,
            quality_grade="A" if coverage_type == "CENSUS" else "B",
            notes="Raw Census item codes are preserved but are not summed across overlapping native rollups.",
        )
        for jurisdiction_id, record_count, classification_count in grouped
    ])
    release.status = "READY"
    release.row_count = count
    release.government_count = len(grouped)
    release.classification_count = len(classes)
    release.ingested_at = datetime.now(timezone.utc)
    release.metadata_json = {"source_file": zip_path.name, "amount_normalization": "thousands multiplied by 1000", "raw_rows_additive": False}
    session.commit()
    LakeStore().register_file(session, dataset_release_id=release.id, path=zip_path, layer="raw", storage_format="ZIP", row_count=count, metadata={"official_bulk_file": True, "coverage_type": coverage_type})
    return {"rows": count, "governments": len(grouped), "classifications": len(classes)}


def bootstrap_national_census(
    session: Session,
    *,
    include_2024_sample: bool = True,
    overwrite_downloads: bool = False,
) -> dict[str, dict[str, int]]:
    settings = get_settings()
    seed_catalog(session)
    result: dict[str, dict[str, int]] = {}

    units = get_source("census-government-units-2022")
    units_path = settings.raw_data_dir / "census" / "government_units" / "govt_units_2022.ZIP"
    stream_download(units.source_url or "", units_path, overwrite=overwrite_downloads)
    result["government_units_2022"] = ingest_government_units_zip(session, units_path)

    finance = get_source("census-gov-finance-2022")
    finance_path = settings.raw_data_dir / "census" / "gov_finance" / "2022_Individual_Unit_File.zip"
    stream_download(finance.source_url or "", finance_path, overwrite=overwrite_downloads)
    result["government_finance_2022"] = ingest_finance_zip(session, finance_path, year=2022, coverage_type="CENSUS", dataset_key="census-gov-finance-2022")

    if include_2024_sample:
        finance = get_source("census-gov-finance-2024")
        finance_path = settings.raw_data_dir / "census" / "gov_finance" / "2024_Individual_Unit_Files.zip"
        stream_download(finance.source_url or "", finance_path, overwrite=overwrite_downloads)
        result["government_finance_2024"] = ingest_finance_zip(session, finance_path, year=2024, coverage_type="SAMPLE", dataset_key="census-gov-finance-2024")
    return result
