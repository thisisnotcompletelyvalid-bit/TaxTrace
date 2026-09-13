from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from taxtrace.db_models import (
    Agency,
    BudgetSubfunction,
    FederalAccount,
    OMBAccountRecord,
    OMBReceiptRecord,
    SpendFact,
)
from taxtrace.enums import DataStatus, FinancialMetric, SourceKind
from taxtrace.finance.snapshot import SnapshotStore
from taxtrace.finance.sources.base import HttpFetcher, filename_from_url

PARSER_VERSION = "omb-pbd-fy2027-v1"
DEFAULT_OUTLAYS_URL = "https://www.whitehouse.gov/wp-content/uploads/2026/04/outlays_fy2027.xlsx"
DEFAULT_RECEIPTS_URL = "https://www.whitehouse.gov/wp-content/uploads/2026/04/receipts_fy2027.xlsx"
# FY2027 PBD User's Guide states 2025 and earlier are actual; 2026-2031 are estimates.
DEFAULT_ACTUAL_THROUGH_YEAR = 2025
THOUSANDS_TO_DOLLARS = Decimal("1000")


class OMBPublicBudgetDatabaseSource:
    def __init__(self, fetcher: HttpFetcher | None = None, snapshots: SnapshotStore | None = None):
        self.fetcher = fetcher or HttpFetcher()
        self.snapshots = snapshots or SnapshotStore()

    def ingest(
        self,
        session: Session,
        fiscal_year: int,
        *,
        outlays_url: str = DEFAULT_OUTLAYS_URL,
        receipts_url: str = DEFAULT_RECEIPTS_URL,
        actual_through_year: int = DEFAULT_ACTUAL_THROUGH_YEAR,
    ) -> int:
        outlay_content = self.fetcher.get_bytes(outlays_url)
        outlay_snapshot = self.snapshots.save_bytes(
            session,
            source_kind=SourceKind.OMB,
            source_name="OMB Public Budget Database Outlays FY2027 edition",
            source_url=outlays_url,
            content=outlay_content,
            filename=filename_from_url(outlays_url, "outlays.xlsx"),
            reference_period="FY2027 Budget edition",
            parser_version=PARSER_VERSION,
        )
        receipt_content = self.fetcher.get_bytes(receipts_url)
        receipt_snapshot = self.snapshots.save_bytes(
            session,
            source_kind=SourceKind.OMB,
            source_name="OMB Public Budget Database Receipts FY2027 edition",
            source_url=receipts_url,
            content=receipt_content,
            filename=filename_from_url(receipts_url, "receipts.xlsx"),
            reference_period="FY2027 Budget edition",
            parser_version=PARSER_VERSION,
        )

        outlays = parse_omb_outlays(Path(outlay_snapshot.local_path), fiscal_year, actual_through_year)
        receipts = parse_omb_receipts(Path(receipt_snapshot.local_path), fiscal_year, actual_through_year)
        self._replace_outlays(session, fiscal_year, outlays, outlay_snapshot.id)
        self._replace_receipts(session, fiscal_year, receipts, receipt_snapshot.id)
        session.commit()
        return len(outlays) + len(receipts)

    def ingest_local(
        self,
        session: Session,
        fiscal_year: int,
        *,
        outlays_path: Path,
        receipts_path: Path,
        actual_through_year: int = DEFAULT_ACTUAL_THROUGH_YEAR,
        fixture: bool = False,
    ) -> int:
        """Ingest local OMB-format workbooks through the same parser used for live files."""
        source_kind = SourceKind.FIXTURE if fixture else SourceKind.OMB
        outlay_snapshot = self.snapshots.register_local_file(
            session,
            source_kind=source_kind,
            source_name=("OMB PBD outlays fixture" if fixture else "OMB PBD local outlays"),
            source_url=DEFAULT_OUTLAYS_URL,
            path=outlays_path,
            reference_period=f"FY{fiscal_year}",
            parser_version=PARSER_VERSION,
            metadata={"fixture": fixture},
        )
        receipt_snapshot = self.snapshots.register_local_file(
            session,
            source_kind=source_kind,
            source_name=("OMB PBD receipts fixture" if fixture else "OMB PBD local receipts"),
            source_url=DEFAULT_RECEIPTS_URL,
            path=receipts_path,
            reference_period=f"FY{fiscal_year}",
            parser_version=PARSER_VERSION,
            metadata={"fixture": fixture},
        )
        outlays = parse_omb_outlays(Path(outlay_snapshot.local_path), fiscal_year, actual_through_year)
        receipts = parse_omb_receipts(Path(receipt_snapshot.local_path), fiscal_year, actual_through_year)
        self._replace_outlays(session, fiscal_year, outlays, outlay_snapshot.id)
        self._replace_receipts(session, fiscal_year, receipts, receipt_snapshot.id)
        session.commit()
        return len(outlays) + len(receipts)

    def _replace_outlays(self, session: Session, fiscal_year: int, rows: list[dict], snapshot_id: int) -> None:
        session.execute(delete(OMBAccountRecord).where(OMBAccountRecord.fiscal_year == fiscal_year))
        session.execute(
            delete(SpendFact).where(
                SpendFact.fiscal_year == fiscal_year,
                SpendFact.record_scope == "omb_account_outlay",
            )
        )
        for row in rows:
            agency = _get_or_create_agency(session, row["agency_code"], row["agency_name"])
            account = _get_or_create_account(
                session, agency.id, row["federal_account_code"], row["account_name"]
            )
            subfunction = _get_or_create_subfunction(
                session, row.get("subfunction_code"), row.get("subfunction_title")
            )
            record = OMBAccountRecord(
                fiscal_year=fiscal_year,
                status=row["status"],
                agency_code=row["agency_code"],
                agency_name=row["agency_name"],
                bureau_code=row["bureau_code"],
                bureau_name=row["bureau_name"],
                account_code=row["account_code"],
                account_name=row["account_name"],
                treasury_agency_code=row.get("treasury_agency_code"),
                cgac_agency_code=row.get("cgac_agency_code"),
                subfunction_code=row.get("subfunction_code"),
                subfunction_title=row.get("subfunction_title"),
                bea_category=row.get("bea_category"),
                grant_split=row.get("grant_split"),
                on_off_budget=row.get("on_off_budget"),
                amount=row["amount"],
                source_snapshot_id=snapshot_id,
            )
            session.add(record)
            session.add(
                SpendFact(
                    fiscal_year=fiscal_year,
                    metric=FinancialMetric.OUTLAY,
                    status=row["status"],
                    amount=row["amount"],
                    source_snapshot_id=snapshot_id,
                    agency_id=agency.id,
                    federal_account_id=account.id,
                    budget_subfunction_id=subfunction.id if subfunction else None,
                    record_scope="omb_account_outlay",
                    native_key=f"{row['agency_code']}:{row['bureau_code']}:{row['account_code']}:{row.get('subfunction_code')}",
                    metadata_json={
                        "bea_category": row.get("bea_category"),
                        "grant_split": row.get("grant_split"),
                        "on_off_budget": row.get("on_off_budget"),
                    },
                )
            )

    def _replace_receipts(self, session: Session, fiscal_year: int, rows: list[dict], snapshot_id: int) -> None:
        session.execute(delete(OMBReceiptRecord).where(OMBReceiptRecord.fiscal_year == fiscal_year))
        for row in rows:
            session.add(OMBReceiptRecord(source_snapshot_id=snapshot_id, fiscal_year=fiscal_year, **row))


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(c).strip() for c in frame.columns]
    return frame


def _find_year_column(frame: pd.DataFrame, fiscal_year: int) -> str:
    target = str(fiscal_year)
    for col in frame.columns:
        normalized = str(col).strip().replace("FY", "").strip()
        if normalized == target or normalized == f"{fiscal_year}.0":
            return col
    raise ValueError(f"OMB workbook does not contain a FY{fiscal_year} column")


def _text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _amount(value) -> Decimal:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return Decimal("0")
    return Decimal(str(value)) * THOUSANDS_TO_DOLLARS


def _load_first_nonempty_sheet(path: Path) -> pd.DataFrame:
    sheets = pd.read_excel(path, sheet_name=None, dtype=object)
    for frame in sheets.values():
        if not frame.empty:
            return _normalize_columns(frame)
    raise ValueError(f"No data in workbook {path}")


def parse_omb_outlays(path: Path, fiscal_year: int, actual_through_year: int) -> list[dict]:
    frame = _load_first_nonempty_sheet(path)
    if len(frame.columns) < 14:
        raise ValueError("OMB outlays workbook has fewer columns than documented in the FY2027 User's Guide")
    year_col = _find_year_column(frame, fiscal_year)
    status = DataStatus.ACTUAL if fiscal_year <= actual_through_year else DataStatus.PROPOSED
    rows: list[dict] = []
    for _, r in frame.iterrows():
        amount = _amount(r[year_col])
        if amount == 0:
            continue
        agency_code = _text(r.iloc[0]).zfill(3)
        agency_name = _text(r.iloc[1])
        bureau_code = _text(r.iloc[2]).zfill(2)
        bureau_name = _text(r.iloc[3])
        account_code = _text(r.iloc[4])
        account_name = _text(r.iloc[5])
        if not agency_name or not account_name:
            continue
        treasury_agency_code = _text(r.iloc[6]) or None
        cgac_agency_code = _text(r.iloc[7]) or None
        federal_account_code = f"{(cgac_agency_code or treasury_agency_code or agency_code).zfill(3)}-{account_code[-4:]}"
        rows.append(
            {
                "status": status,
                "agency_code": agency_code,
                "agency_name": agency_name,
                "bureau_code": bureau_code,
                "bureau_name": bureau_name,
                "account_code": account_code,
                "federal_account_code": federal_account_code,
                "account_name": account_name,
                "treasury_agency_code": treasury_agency_code,
                "cgac_agency_code": cgac_agency_code,
                "subfunction_code": _text(r.iloc[8]) or None,
                "subfunction_title": _text(r.iloc[9]) or None,
                "bea_category": _text(r.iloc[10]) or None,
                "grant_split": _text(r.iloc[11]) or None,
                "on_off_budget": _text(r.iloc[12]) or None,
                "amount": amount,
            }
        )
    return rows


def parse_omb_receipts(path: Path, fiscal_year: int, actual_through_year: int) -> list[dict]:
    frame = _load_first_nonempty_sheet(path)
    if len(frame.columns) < 14:
        raise ValueError("OMB receipts workbook has fewer columns than documented in the FY2027 User's Guide")
    year_col = _find_year_column(frame, fiscal_year)
    status = DataStatus.ACTUAL if fiscal_year <= actual_through_year else DataStatus.PROPOSED
    rows: list[dict] = []
    for _, r in frame.iterrows():
        amount = _amount(r[year_col])
        if amount == 0:
            continue
        category_name = _text(r.iloc[1])
        if not category_name:
            continue
        rows.append(
            {
                "status": status,
                "source_category_code": _text(r.iloc[0]),
                "source_category_name": category_name,
                "source_subcategory_code": _text(r.iloc[2]) or None,
                "source_subcategory_name": _text(r.iloc[3]) or None,
                "agency_code": _text(r.iloc[4]) or None,
                "agency_name": _text(r.iloc[5]) or None,
                "bureau_code": _text(r.iloc[6]) or None,
                "bureau_name": _text(r.iloc[7]) or None,
                "account_code": _text(r.iloc[8]) or None,
                "account_name": _text(r.iloc[9]) or None,
                "treasury_agency_code": _text(r.iloc[10]) or None,
                "cgac_agency_code": _text(r.iloc[11]) or None,
                "on_off_budget": _text(r.iloc[12]) or None,
                "amount": amount,
            }
        )
    return rows


def _get_or_create_agency(session: Session, code: str, name: str) -> Agency:
    obj = session.scalar(select(Agency).where(Agency.source_kind == SourceKind.OMB, Agency.native_code == code))
    if obj is None:
        obj = Agency(source_kind=SourceKind.OMB, native_code=code, name=name)
        session.add(obj)
        session.flush()
    else:
        obj.name = name
    return obj


def _get_or_create_account(session: Session, agency_id: int, code: str, name: str) -> FederalAccount:
    obj = session.scalar(
        select(FederalAccount).where(
            FederalAccount.source_kind == SourceKind.OMB, FederalAccount.native_code == code
        )
    )
    if obj is None:
        obj = FederalAccount(
            source_kind=SourceKind.OMB, agency_id=agency_id, native_code=code, name=name
        )
        session.add(obj)
        session.flush()
    else:
        obj.agency_id = agency_id
        obj.name = name
    return obj


def _get_or_create_subfunction(session: Session, code: str | None, title: str | None) -> BudgetSubfunction | None:
    if not code and not title:
        return None
    obj = session.scalar(
        select(BudgetSubfunction).where(
            BudgetSubfunction.source_kind == SourceKind.OMB,
            BudgetSubfunction.native_code == code,
            BudgetSubfunction.name == (title or code),
        )
    )
    if obj is None:
        obj = BudgetSubfunction(
            source_kind=SourceKind.OMB, native_code=code, name=title or code or "Unknown"
        )
        session.add(obj)
        session.flush()
    return obj
