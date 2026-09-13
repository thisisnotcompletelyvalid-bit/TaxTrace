from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from taxtrace.db_models import TreasuryAggregate
from taxtrace.enums import SourceKind
from taxtrace.finance.snapshot import SnapshotStore
from taxtrace.finance.sources.base import HttpFetcher, filename_from_url

PARSER_VERSION = "treasury-summary-v1"


class TreasuryCombinedStatementSource:
    BASE = "https://fiscal.treasury.gov/system/files/files/reports-statements/combined-statement"

    def __init__(self, fetcher: HttpFetcher | None = None, snapshots: SnapshotStore | None = None):
        self.fetcher = fetcher or HttpFetcher()
        self.snapshots = snapshots or SnapshotStore()

    @classmethod
    def urls(cls, fiscal_year: int) -> dict[str, str]:
        root = f"{cls.BASE}/cs{fiscal_year}"
        return {"receipts": f"{root}/receipt.xlsx", "outlays": f"{root}/outlay.xlsx"}

    def ingest(self, session: Session, fiscal_year: int) -> int:
        count = 0
        for aggregate_type, url in self.urls(fiscal_year).items():
            content = self.fetcher.get_bytes(url)
            snapshot = self.snapshots.save_bytes(
                session,
                source_kind=SourceKind.TREASURY,
                source_name=f"Treasury Combined Statement FY{fiscal_year} {aggregate_type}",
                source_url=url,
                content=content,
                filename=filename_from_url(url, f"{aggregate_type}.xlsx"),
                reference_period=f"FY{fiscal_year}",
                parser_version=PARSER_VERSION,
            )
            rows = parse_treasury_summary_xlsx(Path(snapshot.local_path), fiscal_year, aggregate_type)
            session.execute(
                delete(TreasuryAggregate).where(
                    TreasuryAggregate.fiscal_year == fiscal_year,
                    TreasuryAggregate.aggregate_type == aggregate_type,
                )
            )
            for row in rows:
                session.add(
                    TreasuryAggregate(
                        fiscal_year=fiscal_year,
                        aggregate_type=aggregate_type,
                        category_code=row.get("category_code"),
                        category_name=row["category_name"],
                        amount=row["amount"],
                        source_snapshot_id=snapshot.id,
                        metadata_json=row.get("metadata", {}),
                    )
                )
            count += len(rows)
        session.commit()
        return count


def _cell_text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _to_decimal(value) -> Decimal | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return Decimal(text)
    except Exception:
        return None


def parse_treasury_summary_xlsx(path: Path, fiscal_year: int, aggregate_type: str) -> list[dict]:
    """Parse the Treasury summary workbooks without depending on fragile column names.

    Treasury's summary tables state their unit explicitly (currently millions of dollars). We locate
    the fiscal-year column from the sheet's header, detect the stated unit, and read the first label
    column preceding that fiscal-year value. If the workbook layout changes enough that these
    conditions cannot be established, the parser fails instead of guessing monetary units.
    """
    sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    output: list[dict] = []
    for sheet_name, frame in sheets.items():
        if frame.empty:
            continue
        top_text = " ".join(_cell_text(v).lower() for v in frame.head(20).to_numpy().flatten())
        if "million" in top_text:
            multiplier = Decimal("1000000")
        elif "thousand" in top_text:
            multiplier = Decimal("1000")
        elif "dollar" in top_text:
            multiplier = Decimal("1")
        else:
            raise ValueError(f"Could not determine Treasury monetary units in {path} sheet {sheet_name}")

        year_col = None
        header_row = None
        for r_idx, row in frame.head(30).iterrows():
            for c_idx, value in enumerate(row.tolist()):
                text = _cell_text(value)
                if text in {str(fiscal_year), f"FY {fiscal_year}", f"FY{fiscal_year}"}:
                    year_col = c_idx
                    header_row = r_idx
                    break
            if year_col is not None:
                break
        if year_col is None:
            raise ValueError(f"Could not locate FY{fiscal_year} column in {path} sheet {sheet_name}")

        for r_idx in range(int(header_row) + 1, len(frame)):
            row = frame.iloc[r_idx].tolist()
            if year_col >= len(row):
                continue
            amount = _to_decimal(row[year_col])
            if amount is None:
                continue
            labels = [_cell_text(v) for v in row[:year_col] if _cell_text(v)]
            if not labels:
                continue
            label = labels[-1]
            lower = label.lower()
            if lower in {"amount", "percent", "change"} or re.fullmatch(r"fy\s*\d{4}", lower):
                continue
            output.append(
                {
                    "category_name": label,
                    "amount": amount * multiplier,
                    "metadata": {"sheet": sheet_name, "row": r_idx + 1, "unit_multiplier": str(multiplier)},
                }
            )
    if not output:
        raise ValueError(f"Treasury parser produced no records for {path}")
    return output
