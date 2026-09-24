from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from taxtrace.db_models import TreasuryAggregate
from taxtrace.enums import SourceKind
from taxtrace.finance.snapshot import SnapshotStore
from taxtrace.finance.sources.base import HttpFetcher

PARSER_VERSION = "treasury-mts-table9-v2"
MTS_TABLE_9_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
    "v1/accounting/mts/mts_table_9"
)


class TreasuryCombinedStatementSource:
    """Treasury annual receipt/outlay controls from September Monthly Treasury Statement Table 9.

    Treasury's current Combined Statement Excel files are presentation workbooks whose visible
    summary tables are not exposed as normal workbook cells. Fiscal Data's MTS Table 9 is the
    machine-readable source for the same fiscal-year receipt-source and outlay-function summary.
    September FYTD values are the completed fiscal-year amounts.
    """

    BASE = "https://fiscal.treasury.gov/system/files/files/reports-statements/combined-statement"
    MTS_TABLE_9_URL = MTS_TABLE_9_URL

    def __init__(self, fetcher: HttpFetcher | None = None, snapshots: SnapshotStore | None = None):
        self.fetcher = fetcher or HttpFetcher()
        self.snapshots = snapshots or SnapshotStore()

    @classmethod
    def urls(cls, fiscal_year: int) -> dict[str, str]:
        """Historical presentation-workbook URLs retained for provenance/compatibility."""
        root = f"{cls.BASE}/cs{fiscal_year}"
        return {"receipts": f"{root}/receipt.xlsx", "outlays": f"{root}/outlay.xlsx"}

    @classmethod
    def mts_params(cls, fiscal_year: int) -> dict[str, object]:
        return {
            "filter": (
                f"record_fiscal_year:eq:{fiscal_year},"
                "record_calendar_month:eq:09"
            ),
            "sort": "sequence_number_cd",
            "page[size]": 1000,
        }

    def ingest(self, session: Session, fiscal_year: int) -> int:
        params = self.mts_params(fiscal_year)
        payload = self.fetcher.get_json(self.MTS_TABLE_9_URL, params=params)
        rows = parse_mts_table_9(payload, fiscal_year)
        snapshot = self.snapshots.save_json(
            session,
            source_kind=SourceKind.TREASURY,
            source_name=f"Treasury Monthly Treasury Statement Table 9 FY{fiscal_year}",
            source_url=self.MTS_TABLE_9_URL,
            data=payload,
            filename=f"mts_table_9_fy{fiscal_year}.json",
            reference_period=f"FY{fiscal_year}",
            parser_version=PARSER_VERSION,
            metadata={
                "request_params": params,
                "table": "MTS Table 9",
                "grain": "receipt_source_and_outlay_function_with_control_totals",
                "amount_unit": "dollars",
            },
        )

        session.execute(
            delete(TreasuryAggregate).where(
                TreasuryAggregate.fiscal_year == fiscal_year,
                TreasuryAggregate.aggregate_type.in_(["receipts", "outlays"]),
            )
        )
        for row in rows:
            session.add(
                TreasuryAggregate(
                    fiscal_year=fiscal_year,
                    aggregate_type=row["aggregate_type"],
                    category_code=row.get("category_code"),
                    category_name=row["category_name"],
                    amount=row["amount"],
                    source_snapshot_id=snapshot.id,
                    metadata_json=row.get("metadata", {}),
                )
            )
        session.commit()
        return len(rows)


def _mts_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text or text.lower() in {"null", "none", "nan"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_mts_table_9(payload: dict, fiscal_year: int) -> list[dict]:
    """Parse the final September MTS Table 9 into detail rows plus non-additive controls.

    `RSG/D` rows are receipt-source detail. `F/D` rows are outlay-function detail. The two
    `SL/T` rows are retained only as explicit control totals because existing reconciliation
    compares OMB account outlays to Treasury's named total; they must never be added beside the
    detail rows. Amounts from Fiscal Data are already dollars.
    """
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("Treasury MTS Table 9 response contains no data rows")

    expected_year = str(fiscal_year)
    filtered = [
        row
        for row in data
        if str(row.get("record_fiscal_year") or "") == expected_year
        and str(row.get("record_calendar_month") or "").zfill(2) == "09"
    ]
    if not filtered:
        raise ValueError(f"Treasury MTS Table 9 contains no September FY{fiscal_year} rows")

    output: list[dict] = []
    receipt_details: list[Decimal] = []
    outlay_details: list[Decimal] = []
    receipt_total: Decimal | None = None
    outlay_total: Decimal | None = None

    for row in filtered:
        record_type = str(row.get("record_type_cd") or "").strip().upper()
        data_type = str(row.get("data_type_cd") or "").strip().upper()
        amount = _mts_decimal(row.get("current_fytd_rcpt_outly_amt"))
        label = str(row.get("classification_desc") or "").strip()
        line_code = str(row.get("line_code_nbr") or "").strip() or None
        sequence = str(row.get("sequence_number_cd") or "").strip() or None
        level = str(row.get("sequence_level_nbr") or "").strip() or None

        if data_type == "D" and record_type in {"RSG", "F"}:
            if amount is None or not label:
                raise ValueError(
                    "Treasury MTS Table 9 detail row is missing a numeric FYTD amount or label: "
                    f"{row}"
                )
            aggregate_type = "receipts" if record_type == "RSG" else "outlays"
            if aggregate_type == "receipts":
                receipt_details.append(amount)
            else:
                outlay_details.append(amount)
            output.append(
                {
                    "aggregate_type": aggregate_type,
                    "category_code": line_code,
                    "category_name": label,
                    "amount": amount,
                    "metadata": {
                        "source_table": "MTS Table 9",
                        "record_date": row.get("record_date"),
                        "record_type_cd": record_type,
                        "data_type_cd": data_type,
                        "classification_id": row.get("classification_id"),
                        "line_code_nbr": line_code,
                        "sequence_level_nbr": level,
                        "sequence_number_cd": sequence,
                        "amount_unit": "dollars",
                        "additive_detail": True,
                        "control_total": False,
                    },
                }
            )
            continue

        if record_type == "SL" and data_type == "T" and amount is not None:
            # Sequence 1.* is the receipt section; sequence 2.* is the outlay section.
            aggregate_type = "receipts" if (sequence or "").startswith("1.") else "outlays"
            if aggregate_type == "receipts":
                if receipt_total is not None:
                    raise ValueError("Treasury MTS Table 9 has more than one receipt total control")
                receipt_total = amount
            else:
                if outlay_total is not None:
                    raise ValueError("Treasury MTS Table 9 has more than one outlay total control")
                outlay_total = amount
            output.append(
                {
                    "aggregate_type": aggregate_type,
                    "category_code": line_code,
                    "category_name": "Total",
                    "amount": amount,
                    "metadata": {
                        "source_table": "MTS Table 9",
                        "record_date": row.get("record_date"),
                        "record_type_cd": record_type,
                        "data_type_cd": data_type,
                        "classification_id": row.get("classification_id"),
                        "line_code_nbr": line_code,
                        "sequence_level_nbr": level,
                        "sequence_number_cd": sequence,
                        "amount_unit": "dollars",
                        "additive_detail": False,
                        "control_total": True,
                    },
                }
            )

    if not receipt_details or not outlay_details:
        raise ValueError(
            "Treasury MTS Table 9 did not contain both receipt-source and outlay-function detail"
        )
    if receipt_total is None or outlay_total is None:
        raise ValueError("Treasury MTS Table 9 is missing receipt or outlay total controls")

    receipt_sum = sum(receipt_details, Decimal("0"))
    outlay_sum = sum(outlay_details, Decimal("0"))
    if receipt_sum != receipt_total:
        raise ValueError(
            "Treasury receipt-source detail does not reconcile to Table 9 control: "
            f"detail={receipt_sum}, control={receipt_total}"
        )
    if outlay_sum != outlay_total:
        raise ValueError(
            "Treasury outlay-function detail does not reconcile to Table 9 control: "
            f"detail={outlay_sum}, control={outlay_total}"
        )

    return output


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
    """Historical compatibility parser for older Combined Statement workbooks.

    Current annual ingestion uses machine-readable MTS Table 9. This parser remains available for
    archived workbooks and regression fixtures that expose real worksheet cells and stated units.
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
                    "metadata": {
                        "sheet": sheet_name,
                        "row": r_idx + 1,
                        "unit_multiplier": str(multiplier),
                    },
                }
            )
    if not output:
        raise ValueError(f"Treasury parser produced no records for {path}")
    return output
