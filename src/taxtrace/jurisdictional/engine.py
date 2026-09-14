from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from taxtrace.allocation.engine import FederalAllocationEngine
from taxtrace.allocation.models import FederalReceiptRequest, SourceReference
from taxtrace.db_models import Jurisdiction, SourceSnapshot
from taxtrace.enums import ConfidenceGrade, DataStatus, FinancialMetric
from taxtrace.jurisdictional.db_models import JurisdictionSpendFact
from taxtrace.jurisdictional.models import (
    FloridaGainesvilleReceiptRequest,
    FloridaGainesvilleReceiptResult,
    JurisdictionReceipt,
    JurisdictionReceiptNode,
    SpendingReference,
    SpendingReferenceNode,
)
from taxtrace.jurisdictional.sales_tax import FloridaSalesTaxModel9A

CENT = Decimal("0.01")
ZERO = Decimal("0")


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def reconcile_parts(total: Decimal, raw: list[Decimal], keys: list[str]) -> list[Decimal]:
    """Deterministic largest-remainder cent allocation."""
    total = money(total)
    if not raw:
        return []
    floors = [(value / CENT).to_integral_value(rounding=ROUND_FLOOR) * CENT for value in raw]
    pennies = int(((total - sum(floors, ZERO)) / CENT).to_integral_value())
    ranked = sorted(
        range(len(raw)),
        key=lambda i: (-(raw[i] - floors[i]), keys[i]),
    )
    result = list(floors)
    for i in ranked[: max(0, pennies)]:
        result[i] += CENT
    return [money(x) for x in result]


class FloridaGainesvilleEngine:
    def __init__(self):
        self.federal_engine = FederalAllocationEngine()
        self.sales_model = FloridaSalesTaxModel9A()

    def calculate(
        self, session: Session, request: FloridaGainesvilleReceiptRequest
    ) -> FloridaGainesvilleReceiptResult:
        federal_request = FederalReceiptRequest(
            **request.model_dump(exclude={"household_size"})
        )
        federal = self.federal_engine.calculate(session, federal_request)
        modeled = self.sales_model.estimate(request.wage_income, request.spouse_wage_income)
        state = self._state_receipt(
            session, request.spending_fiscal_year, modeled.florida_state_sales_tax
        )
        local = self._local_receipt(modeled.alachua_county_surtax, request.spending_fiscal_year)
        city = self._city_reference(session, request.spending_fiscal_year)
        total = money(federal.total_allocable_taxes + modeled.combined_sales_tax)
        return FloridaGainesvilleReceiptResult(
            federal=federal,
            sales_tax_model=modeled,
            florida_state=state,
            alachua_local=local,
            gainesville_spending_reference=city,
            total_supported_calculated_and_modeled_tax=total,
            warnings=[
                "Florida and Alachua sales taxes are MODELED from BLS household expenditure data; they are not calculated from the user's actual purchases.",
                "Property tax, fuel tax, utility taxes, communications taxes, fees, and landlord tax incidence are not inferred from wage income.",
                "Gainesville FY2025 expenditures are shown as an ACTUAL reference, not attributed to this user unless a supported local tax relationship exists.",
            ],
        )

    def _state_receipt(self, session: Session, fiscal_year: int, tax_amount: Decimal) -> JurisdictionReceipt:
        jurisdiction = session.scalar(select(Jurisdiction).where(Jurisdiction.code == "FL"))
        if jurisdiction is None:
            raise ValueError("Florida jurisdiction data are not loaded; run the fixture bootstrap.")
        rows = session.scalars(
            select(JurisdictionSpendFact)
            .where(
                JurisdictionSpendFact.jurisdiction_id == jurisdiction.id,
                JurisdictionSpendFact.fiscal_year == fiscal_year,
                JurisdictionSpendFact.metric == FinancialMetric.EXPENDITURE,
                JurisdictionSpendFact.status == DataStatus.ACTUAL,
                JurisdictionSpendFact.record_scope == "state_acfr_governmental_activities",
            )
            .order_by(JurisdictionSpendFact.category_code)
        ).all()
        if not rows:
            raise ValueError(f"No Florida actual expenditure facts are loaded for FY{fiscal_year}.")
        denominator = sum((Decimal(row.amount) for row in rows), ZERO)
        raw = [Decimal(tax_amount) * Decimal(row.amount) / denominator for row in rows]
        allocated = reconcile_parts(Decimal(tax_amount), raw, [row.category_code for row in rows])
        nodes = [
            JurisdictionReceiptNode(
                key=f"FL:{row.category_code}",
                label=row.category_name,
                allocated_amount=amount,
                government_spending_amount=money(Decimal(row.amount)),
                relation="ALLOCATED",
                confidence=ConfidenceGrade.C,
                notes=["Modeled Florida sales-tax liability allocated proportionally to FY2025 audited governmental-activity expenses."],
            )
            for row, amount in zip(rows, allocated, strict=True)
        ]
        sources = self._source_refs(session, sorted({row.source_snapshot_id for row in rows}))
        difference = money(Decimal(tax_amount) - sum((n.allocated_amount for n in nodes), ZERO))
        return JurisdictionReceipt(
            jurisdiction_code="FL",
            jurisdiction_name="Florida",
            fiscal_year=fiscal_year,
            tax_amount=money(tax_amount),
            nodes=nodes,
            conservation_difference=difference,
            warnings=[
                "The state sales-tax liability is MODELED. Its allocation uses audited actual governmental-activity expenses and is attribution, not literal tracing."
            ],
            sources=sources,
        )

    def _local_receipt(self, tax_amount: Decimal, fiscal_year: int) -> JurisdictionReceipt:
        thirds = reconcile_parts(Decimal(tax_amount), [Decimal(tax_amount) / 3] * 3, ["infrastructure", "school", "wspp"])
        values = dict(zip(["infrastructure", "school", "wspp"], thirds, strict=True))
        distribution = [
            ("alachua_county", "Alachua County", Decimal("0.5698")),
            ("gainesville", "City of Gainesville", Decimal("0.3545")),
            ("other_municipalities", "Other Alachua County municipalities", Decimal("0.0757")),
        ]

        def distributed_children(parent: str, amount: Decimal) -> list[JurisdictionReceiptNode]:
            raw = [amount * share for _, _, share in distribution]
            parts = reconcile_parts(amount, raw, [key for key, _, _ in distribution])
            return [
                JurisdictionReceiptNode(
                    key=f"FL-ALACHUA:{parent}:{key}",
                    label=label,
                    allocated_amount=part,
                    relation="DIRECT",
                    confidence=ConfidenceGrade.C,
                    notes=["Population-based interlocal distribution of this dedicated local surtax pool."],
                )
                for (key, label, _), part in zip(distribution, parts, strict=True)
            ]

        school = JurisdictionReceiptNode(
            key="FL-ALACHUA:school_capital",
            label="School capital outlay surtax",
            allocated_amount=values["school"],
            relation="DIRECT",
            confidence=ConfidenceGrade.C,
            notes=["One-half percentage point of the current 1.5% Alachua surtax is the school capital outlay surtax."],
        )
        wspp = JurisdictionReceiptNode(
            key="FL-ALACHUA:wspp",
            label="Wild Spaces & Public Places",
            allocated_amount=values["wspp"],
            relation="DIRECT",
            confidence=ConfidenceGrade.C,
            notes=["One-half percentage point funds conservation, parks, recreation, and related WSPP purposes."],
            children=distributed_children("wspp", values["wspp"]),
        )
        infrastructure = JurisdictionReceiptNode(
            key="FL-ALACHUA:infrastructure",
            label="Infrastructure / Streets, Stations & Strong Foundations",
            allocated_amount=values["infrastructure"],
            relation="DIRECT",
            confidence=ConfidenceGrade.C,
            notes=[
                "One-half percentage point is the infrastructure half of the voter-approved one-cent local-government surtax.",
                "Gainesville's infrastructure portion includes roads, public-safety facilities and affordable-housing land; the City reports a 10% affordable-housing set-aside for its infrastructure share.",
            ],
            children=distributed_children("infrastructure", values["infrastructure"]),
        )
        nodes = [school, wspp, infrastructure]
        difference = money(Decimal(tax_amount) - sum((n.allocated_amount for n in nodes), ZERO))
        return JurisdictionReceipt(
            jurisdiction_code="FL-ALACHUA",
            jurisdiction_name="Alachua County",
            fiscal_year=fiscal_year,
            tax_amount=money(tax_amount),
            nodes=nodes,
            conservation_difference=difference,
            warnings=[
                "The amount of surtax is MODELED from consumption. Once estimated, the three half-cent legal-purpose pools are kept separate rather than blended into general local spending."
            ],
            sources=[
                SourceReference(
                    id=0,
                    name="Florida Department of Revenue — Discretionary Sales Surtax",
                    url="https://floridarevenue.com/taxes/taxesfees/Pages/discretionary.aspx",
                    reference_period="Current",
                    parser_version="manual-authority-v1",
                ),
                SourceReference(
                    id=0,
                    name="City of Gainesville — Wild Spaces & Public Places",
                    url="https://www.gainesvillefl.gov/Government-Pages/Government/Departments/Wild-Spaces-Public-Places",
                    reference_period="2023–2032 program",
                    parser_version="manual-authority-v1",
                ),
            ],
        )

    def _city_reference(self, session: Session, fiscal_year: int) -> SpendingReference:
        jurisdiction = session.scalar(select(Jurisdiction).where(Jurisdiction.code == "FL-GAINESVILLE"))
        if jurisdiction is None:
            raise ValueError("Gainesville jurisdiction data are not loaded; run the fixture bootstrap.")
        rows = session.scalars(
            select(JurisdictionSpendFact)
            .where(
                JurisdictionSpendFact.jurisdiction_id == jurisdiction.id,
                JurisdictionSpendFact.fiscal_year == fiscal_year,
                JurisdictionSpendFact.record_scope == "city_acfr_governmental_activities",
            )
            .order_by(JurisdictionSpendFact.category_code)
        ).all()
        total = money(sum((Decimal(row.amount) for row in rows), ZERO))
        return SpendingReference(
            jurisdiction_code="FL-GAINESVILLE",
            jurisdiction_name="Gainesville",
            fiscal_year=fiscal_year,
            total_actual_expenditure=total,
            nodes=[
                SpendingReferenceNode(
                    key=f"FL-GAINESVILLE:{row.category_code}",
                    label=row.category_name,
                    actual_expenditure=money(Decimal(row.amount)),
                )
                for row in rows
            ],
            attributable_tax_amount=None,
            explanation=(
                "Actual FY2025 Gainesville governmental-activity expenses. Quick mode does not infer property tax, utility taxes, fees, or other city liabilities from wages, so these expenditures are not presented as the user's additive tax receipt."
            ),
            sources=self._source_refs(session, sorted({row.source_snapshot_id for row in rows})),
        )

    def _source_refs(self, session: Session, ids: list[int]) -> list[SourceReference]:
        refs: list[SourceReference] = []
        for source_id in ids:
            source = session.get(SourceSnapshot, source_id)
            if source is None:
                continue
            refs.append(
                SourceReference(
                    id=source.id,
                    name=source.source_name,
                    url=source.source_url,
                    reference_period=source.reference_period,
                    retrieved_at=source.retrieved_at.isoformat() if source.retrieved_at else None,
                    parser_version=source.parser_version,
                )
            )
        return refs
