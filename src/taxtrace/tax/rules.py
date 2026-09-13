import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from taxtrace.enums import FilingStatus


@dataclass(frozen=True)
class FederalRules:
    tax_year: int
    raw: dict

    def standard_deduction(self, filing_status: FilingStatus) -> Decimal:
        return Decimal(self.raw["standard_deduction"][filing_status.value])

    def brackets(self, filing_status: FilingStatus) -> list[tuple[Decimal | None, Decimal]]:
        return [
            (Decimal(upper) if upper is not None else None, Decimal(rate))
            for upper, rate in self.raw["ordinary_income_brackets"][filing_status.value]
        ]

    def fica(self, key: str) -> Decimal:
        return Decimal(self.raw["fica"][key])

    def additional_medicare_threshold(self, filing_status: FilingStatus) -> Decimal:
        return Decimal(self.raw["fica"]["additional_medicare_threshold"][filing_status.value])

    def credit(self, key: str) -> Decimal:
        return Decimal(self.raw["dependent_credits"][key])

    def credit_phaseout_threshold(self, filing_status: FilingStatus) -> Decimal:
        return Decimal(self.raw["dependent_credits"]["phaseout_threshold"][filing_status.value])


class RuleRepository:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parents[1] / "data" / "tax_rules" / "federal"

    def load(self, tax_year: int) -> FederalRules:
        path = self.root / f"{tax_year}.json"
        if not path.exists():
            raise ValueError(f"Unsupported federal tax year: {tax_year}")
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if raw["tax_year"] != tax_year:
            raise ValueError(f"Rule file year mismatch: {path}")
        return FederalRules(tax_year=tax_year, raw=raw)
