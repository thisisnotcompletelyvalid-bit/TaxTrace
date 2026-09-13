from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlencode

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from taxtrace.db_models import (
    Agency,
    BudgetFunction,
    BudgetSubfunction,
    FederalAccount,
    ObjectClass,
    ProgramActivity,
    SpendFact,
    TreasuryAccount,
)
from taxtrace.enums import DataStatus, FinancialMetric, SourceKind
from taxtrace.finance.snapshot import SnapshotStore
from taxtrace.finance.sources.base import HttpFetcher

API_BASE = "https://api.usaspending.gov/api/v2"
PARSER_VERSION = "usaspending-v2-agency-dimensions-v1"


class USASpendingSource:
    """Ingest agency/account and File-B-derived dimensions from USAspending v2.

    The API presents several overlapping classifications of the same spending. TaxTrace stores
    them as separate record scopes so they are never accidentally added together.
    """

    def __init__(self, fetcher: HttpFetcher | None = None, snapshots: SnapshotStore | None = None):
        self.fetcher = fetcher or HttpFetcher()
        self.snapshots = snapshots or SnapshotStore()

    def ingest(self, session: Session, fiscal_year: int, agency_codes: list[str] | None = None) -> int:
        agencies_payload, _ = self._fetch_one(
            session,
            "/references/toptier_agencies/",
            params={},
            label="toptier-agencies",
            reference_period=f"FY{fiscal_year}",
        )
        agencies = self._upsert_agencies(session, agencies_payload)
        selected = [a for a in agencies if agency_codes is None or a.native_code in set(agency_codes)]
        total = 0
        for agency in selected:
            total += self._ingest_agency(session, agency, fiscal_year)
        session.commit()
        return total

    def _ingest_agency(self, session: Session, agency: Agency, fiscal_year: int) -> int:
        scopes = [
            "usaspending_federal_account",
            "usaspending_treasury_account",
            "usaspending_object_class",
            "usaspending_program_activity",
            "usaspending_budget_function",
            "usaspending_budget_subfunction",
        ]
        session.execute(
            delete(SpendFact).where(
                SpendFact.fiscal_year == fiscal_year,
                SpendFact.agency_id == agency.id,
                SpendFact.record_scope.in_(scopes),
            )
        )
        count = 0
        count += self._ingest_federal_accounts(session, agency, fiscal_year)
        count += self._ingest_object_classes(session, agency, fiscal_year)
        count += self._ingest_program_activities(session, agency, fiscal_year)
        count += self._ingest_budget_functions(session, agency, fiscal_year)
        session.flush()
        return count

    def _ingest_federal_accounts(self, session: Session, agency: Agency, fiscal_year: int) -> int:
        count = 0
        endpoint = f"/agency/{agency.native_code}/federal_account/"
        for payload, snapshot_id in self._fetch_paginated(session, endpoint, fiscal_year, "federal-account"):
            for row in payload.get("results", []):
                code = str(row.get("code", "")).strip()
                name = str(row.get("name", code)).strip()
                if not code:
                    continue
                account = self._get_or_create_federal_account(session, agency.id, code, name)
                count += self._add_amount_facts(
                    session,
                    fiscal_year,
                    snapshot_id,
                    agency_id=agency.id,
                    federal_account_id=account.id,
                    row=row,
                    scope="usaspending_federal_account",
                    native_key=code,
                )
                for child in row.get("children", []) or []:
                    tas = str(child.get("code", "")).strip()
                    if not tas:
                        continue
                    treasury_account = self._get_or_create_treasury_account(
                        session,
                        account.id,
                        tas,
                        str(child.get("name") or name),
                    )
                    count += self._add_amount_facts(
                        session,
                        fiscal_year,
                        snapshot_id,
                        agency_id=agency.id,
                        federal_account_id=account.id,
                        treasury_account_id=treasury_account.id,
                        row=child,
                        scope="usaspending_treasury_account",
                        native_key=tas,
                    )
        return count

    def _ingest_object_classes(self, session: Session, agency: Agency, fiscal_year: int) -> int:
        count = 0
        endpoint = f"/agency/{agency.native_code}/object_class/"
        for payload, snapshot_id in self._fetch_paginated(session, endpoint, fiscal_year, "object-class"):
            for row in payload.get("results", []):
                name = str(row.get("name", "")).strip()
                if not name:
                    continue
                obj = self._get_or_create_named_dimension(ObjectClass, session, agency.id, name, row.get("code"))
                count += self._add_amount_facts(
                    session,
                    fiscal_year,
                    snapshot_id,
                    agency_id=agency.id,
                    object_class_id=obj.id,
                    row=row,
                    scope="usaspending_object_class",
                    native_key=str(row.get("code") or name),
                )
        return count

    def _ingest_program_activities(self, session: Session, agency: Agency, fiscal_year: int) -> int:
        count = 0
        endpoint = f"/agency/{agency.native_code}/program_activity/"
        for payload, snapshot_id in self._fetch_paginated(session, endpoint, fiscal_year, "program-activity"):
            for row in payload.get("results", []):
                name = str(row.get("name", "")).strip()
                if not name:
                    continue
                obj = self._get_or_create_named_dimension(ProgramActivity, session, agency.id, name, row.get("code"))
                count += self._add_amount_facts(
                    session,
                    fiscal_year,
                    snapshot_id,
                    agency_id=agency.id,
                    program_activity_id=obj.id,
                    row=row,
                    scope="usaspending_program_activity",
                    native_key=str(row.get("code") or name),
                )
        return count

    def _ingest_budget_functions(self, session: Session, agency: Agency, fiscal_year: int) -> int:
        count = 0
        endpoint = f"/agency/{agency.native_code}/budget_function/"
        for payload, snapshot_id in self._fetch_paginated(session, endpoint, fiscal_year, "budget-function"):
            for row in payload.get("results", []):
                name = str(row.get("name", "")).strip()
                if not name:
                    continue
                function = self._get_or_create_budget_function(session, name, row.get("code"))
                count += self._add_amount_facts(
                    session,
                    fiscal_year,
                    snapshot_id,
                    agency_id=agency.id,
                    budget_function_id=function.id,
                    row=row,
                    scope="usaspending_budget_function",
                    native_key=str(row.get("code") or name),
                )
                for child in row.get("children", []) or []:
                    child_name = str(child.get("name", "")).strip()
                    if not child_name:
                        continue
                    sub = self._get_or_create_budget_subfunction(
                        session, function.id, child_name, child.get("code")
                    )
                    count += self._add_amount_facts(
                        session,
                        fiscal_year,
                        snapshot_id,
                        agency_id=agency.id,
                        budget_function_id=function.id,
                        budget_subfunction_id=sub.id,
                        row=child,
                        scope="usaspending_budget_subfunction",
                        native_key=str(child.get("code") or child_name),
                    )
        return count

    def _add_amount_facts(
        self,
        session: Session,
        fiscal_year: int,
        snapshot_id: int,
        *,
        row: dict,
        scope: str,
        native_key: str,
        agency_id: int | None = None,
        federal_account_id: int | None = None,
        treasury_account_id: int | None = None,
        program_activity_id: int | None = None,
        object_class_id: int | None = None,
        budget_function_id: int | None = None,
        budget_subfunction_id: int | None = None,
    ) -> int:
        count = 0
        pairs = [
            (FinancialMetric.OBLIGATION, row.get("obligated_amount"), False),
            (FinancialMetric.OUTLAY, row.get("gross_outlay_amount"), True),
        ]
        for metric, value, gross in pairs:
            if value is None:
                continue
            session.add(
                SpendFact(
                    fiscal_year=fiscal_year,
                    metric=metric,
                    status=DataStatus.ACTUAL,
                    amount=Decimal(str(value)),
                    source_snapshot_id=snapshot_id,
                    agency_id=agency_id,
                    federal_account_id=federal_account_id,
                    treasury_account_id=treasury_account_id,
                    program_activity_id=program_activity_id,
                    object_class_id=object_class_id,
                    budget_function_id=budget_function_id,
                    budget_subfunction_id=budget_subfunction_id,
                    record_scope=scope,
                    native_key=native_key,
                    metadata_json={"gross": gross, "source_field": "gross_outlay_amount" if gross else "obligated_amount"},
                )
            )
            count += 1
        return count

    def _fetch_paginated(self, session: Session, endpoint: str, fiscal_year: int, label: str):
        page = 1
        while True:
            params = {"fiscal_year": fiscal_year, "page": page, "limit": 100}
            payload, snapshot_id = self._fetch_one(
                session,
                endpoint,
                params=params,
                label=f"{label}-page-{page}",
                reference_period=f"FY{fiscal_year}",
            )
            yield payload, snapshot_id
            meta = payload.get("page_metadata") or {}
            if not meta.get("hasNext") and not meta.get("next"):
                break
            page = int(meta.get("next") or page + 1)

    def _fetch_one(
        self,
        session: Session,
        endpoint: str,
        *,
        params: dict,
        label: str,
        reference_period: str,
    ) -> tuple[dict, int]:
        url = API_BASE + endpoint
        payload = self.fetcher.get_json(url, params=params)
        rendered_url = url + ("?" + urlencode(params) if params else "")
        snapshot = self.snapshots.save_json(
            session,
            source_kind=SourceKind.USASPENDING,
            source_name=f"USAspending {label}",
            source_url=rendered_url,
            data=payload,
            filename=f"{label}.json",
            reference_period=reference_period,
            parser_version=PARSER_VERSION,
        )
        return payload, snapshot.id

    def _upsert_agencies(self, session: Session, payload: dict) -> list[Agency]:
        out: list[Agency] = []
        for row in payload.get("results", []):
            code = str(row.get("toptier_code", "")).strip()
            name = str(row.get("agency_name", "")).strip()
            if not code or not name:
                continue
            obj = session.scalar(
                select(Agency).where(
                    Agency.source_kind == SourceKind.USASPENDING,
                    Agency.native_code == code,
                )
            )
            if obj is None:
                obj = Agency(source_kind=SourceKind.USASPENDING, native_code=code, name=name)
                session.add(obj)
                session.flush()
            obj.name = name
            obj.abbreviation = row.get("abbreviation")
            obj.slug = row.get("agency_slug")
            obj.active = True
            out.append(obj)
        return out

    @staticmethod
    def _get_or_create_federal_account(session: Session, agency_id: int, code: str, name: str) -> FederalAccount:
        obj = session.scalar(
            select(FederalAccount).where(
                FederalAccount.source_kind == SourceKind.USASPENDING,
                FederalAccount.native_code == code,
            )
        )
        if obj is None:
            obj = FederalAccount(
                source_kind=SourceKind.USASPENDING,
                agency_id=agency_id,
                native_code=code,
                name=name,
            )
            session.add(obj)
            session.flush()
        else:
            obj.agency_id = agency_id
            obj.name = name
        return obj

    @staticmethod
    def _get_or_create_treasury_account(session: Session, federal_account_id: int, tas: str, name: str) -> TreasuryAccount:
        obj = session.scalar(
            select(TreasuryAccount).where(
                TreasuryAccount.source_kind == SourceKind.USASPENDING,
                TreasuryAccount.tas == tas,
            )
        )
        if obj is None:
            obj = TreasuryAccount(
                source_kind=SourceKind.USASPENDING,
                federal_account_id=federal_account_id,
                tas=tas,
                name=name,
            )
            session.add(obj)
            session.flush()
        else:
            obj.federal_account_id = federal_account_id
            obj.name = name
        return obj

    @staticmethod
    def _get_or_create_named_dimension(model, session: Session, agency_id: int, name: str, code) -> ObjectClass | ProgramActivity:
        obj = session.scalar(
            select(model).where(
                model.source_kind == SourceKind.USASPENDING,
                model.agency_id == agency_id,
                model.name == name,
            )
        )
        if obj is None:
            obj = model(
                source_kind=SourceKind.USASPENDING,
                agency_id=agency_id,
                native_code=str(code) if code else None,
                name=name,
            )
            session.add(obj)
            session.flush()
        elif code and not obj.native_code:
            obj.native_code = str(code)
        return obj

    @staticmethod
    def _get_or_create_budget_function(session: Session, name: str, code) -> BudgetFunction:
        obj = session.scalar(
            select(BudgetFunction).where(
                BudgetFunction.source_kind == SourceKind.USASPENDING,
                BudgetFunction.name == name,
            )
        )
        if obj is None:
            obj = BudgetFunction(
                source_kind=SourceKind.USASPENDING,
                native_code=str(code) if code else None,
                name=name,
            )
            session.add(obj)
            session.flush()
        return obj

    @staticmethod
    def _get_or_create_budget_subfunction(session: Session, function_id: int, name: str, code) -> BudgetSubfunction:
        obj = session.scalar(
            select(BudgetSubfunction).where(
                BudgetSubfunction.source_kind == SourceKind.USASPENDING,
                BudgetSubfunction.function_id == function_id,
                BudgetSubfunction.name == name,
            )
        )
        if obj is None:
            obj = BudgetSubfunction(
                source_kind=SourceKind.USASPENDING,
                function_id=function_id,
                native_code=str(code) if code else None,
                name=name,
            )
            session.add(obj)
            session.flush()
        return obj
