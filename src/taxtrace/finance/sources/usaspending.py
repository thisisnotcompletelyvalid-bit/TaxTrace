from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlencode

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from taxtrace.db_models import (
    Agency,
    Award,
    AwardAccountLink,
    BudgetFunction,
    BudgetSubfunction,
    FederalAccount,
    ObjectClass,
    ProgramActivity,
    Recipient,
    SpendFact,
    TreasuryAccount,
)
from taxtrace.enums import DataStatus, FinancialMetric, SourceKind
from taxtrace.finance.snapshot import SnapshotStore
from taxtrace.finance.sources.base import HttpFetcher

API_BASE = "https://api.usaspending.gov/api/v2"
PARSER_VERSION = "usaspending-v2-agency-dimensions-v2"


class USASpendingSource:
    """Ingest overlapping USAspending dimensions without treating them as one additive tree."""

    def __init__(self, fetcher: HttpFetcher | None = None, snapshots: SnapshotStore | None = None):
        self.fetcher = fetcher or HttpFetcher()
        self.snapshots = snapshots or SnapshotStore()

    def ingest(
        self,
        session: Session,
        fiscal_year: int,
        agency_codes: list[str] | None = None,
        *,
        include_awards: bool = False,
    ) -> int:
        payload, _ = self._fetch_one(
            session,
            "/references/toptier_agencies/",
            params={},
            label="toptier-agencies",
            reference_period=f"FY{fiscal_year}",
        )
        agencies = self._upsert_agencies(session, payload)
        wanted = set(agency_codes or [])
        selected = [a for a in agencies if not wanted or a.native_code in wanted]
        count = sum(
            self._ingest_agency(session, agency, fiscal_year, include_awards=include_awards)
            for agency in selected
        )
        session.commit()
        return count

    def _ingest_agency(
        self, session: Session, agency: Agency, fiscal_year: int, *, include_awards: bool
    ) -> int:
        scopes = [
            "usaspending_federal_account",
            "usaspending_treasury_account",
            "usaspending_object_class",
            "usaspending_program_activity",
            "usaspending_budget_function",
            "usaspending_budget_subfunction",
            "usaspending_account_program_activity",
        ]
        session.execute(
            delete(SpendFact).where(
                SpendFact.fiscal_year == fiscal_year,
                SpendFact.agency_id == agency.id,
                SpendFact.record_scope.in_(scopes),
            )
        )
        return (
            self._ingest_accounts(session, agency, fiscal_year, include_awards)
            + self._ingest_named_dimension(
                session,
                agency,
                fiscal_year,
                endpoint="object_class",
                model=ObjectClass,
                id_field="object_class_id",
                scope="usaspending_object_class",
            )
            + self._ingest_named_dimension(
                session,
                agency,
                fiscal_year,
                endpoint="program_activity",
                model=ProgramActivity,
                id_field="program_activity_id",
                scope="usaspending_program_activity",
            )
            + self._ingest_budget_functions(session, agency, fiscal_year)
        )

    def _ingest_accounts(
        self, session: Session, agency: Agency, fiscal_year: int, include_awards: bool
    ) -> int:
        count = 0
        endpoint = f"/agency/{agency.native_code}/federal_account/"
        for payload, snapshot_id in self._fetch_paginated(
            session, endpoint, fiscal_year, "federal-account"
        ):
            for row in payload.get("results", []):
                code = str(row.get("code") or "").strip()
                if not code:
                    continue
                name = str(row.get("name") or code).strip()
                account = self._account(session, agency.id, code, name)
                count += self._facts(
                    session,
                    fiscal_year,
                    snapshot_id,
                    row,
                    "usaspending_federal_account",
                    code,
                    agency_id=agency.id,
                    federal_account_id=account.id,
                )
                for child in row.get("children") or []:
                    tas = str(child.get("code") or "").strip()
                    if not tas:
                        continue
                    treasury = self._treasury_account(
                        session, account.id, tas, str(child.get("name") or name)
                    )
                    count += self._facts(
                        session,
                        fiscal_year,
                        snapshot_id,
                        child,
                        "usaspending_treasury_account",
                        tas,
                        agency_id=agency.id,
                        federal_account_id=account.id,
                        treasury_account_id=treasury.id,
                    )
                count += self._account_programs(session, agency, account, fiscal_year)
                if include_awards:
                    count += self._account_awards(session, agency, account, fiscal_year)
        return count

    def _account_programs(
        self, session: Session, agency: Agency, account: FederalAccount, fiscal_year: int
    ) -> int:
        """Ingest program activities at Treasury-account grain and retain the federal-account link.

        USAspending exposes program activities for a Treasury Account Symbol (TAS), not directly
        for a federal account. Linking the TAS fact back to its parent federal account is what makes
        account -> program-activity drilldown defensible instead of a name-based guess.
        """
        treasury_accounts = session.scalars(
            select(TreasuryAccount).where(TreasuryAccount.federal_account_id == account.id)
        ).all()
        count = 0
        for treasury in treasury_accounts:
            payload, snapshot_id = self._fetch_one(
                session,
                f"/agency/treasury_account/{treasury.tas}/program_activity/",
                params={"fiscal_year": fiscal_year},
                label=f"tas-{treasury.tas}-program-activity",
                reference_period=f"FY{fiscal_year}",
            )
            for row in payload.get("results", []):
                code = row.get("program_activity_code", row.get("code"))
                name = str(row.get("program_activity_name", row.get("name", ""))).strip()
                if not name:
                    continue
                program = self._named_dimension(ProgramActivity, session, agency.id, name, code)
                normalized = dict(row)
                normalized.setdefault(
                    "obligated_amount", normalized.get("obligation") or normalized.get("obligations")
                )
                normalized.setdefault(
                    "gross_outlay_amount", normalized.get("outlay") or normalized.get("outlays")
                )
                count += self._facts(
                    session,
                    fiscal_year,
                    snapshot_id,
                    normalized,
                    "usaspending_account_program_activity",
                    f"{treasury.tas}:{code or name}",
                    agency_id=agency.id,
                    federal_account_id=account.id,
                    treasury_account_id=treasury.id,
                    program_activity_id=program.id,
                )
        return count

    def _account_awards(
        self, session: Session, agency: Agency, account: FederalAccount, fiscal_year: int
    ) -> int:
        count = 0
        page = 1
        while True:
            body = {
                "subawards": False,
                "limit": 100,
                "page": page,
                "filters": {
                    "award_type_codes": [
                        "02", "03", "04", "05", "06", "07", "08", "09", "10", "11",
                        "A", "B", "C", "D",
                    ],
                    "time_period": [
                        {
                            "start_date": f"{fiscal_year - 1}-10-01",
                            "end_date": f"{fiscal_year}-09-30",
                        }
                    ],
                    "tas_codes": {"require": [[agency.native_code, account.native_code]]},
                },
                "fields": [
                    "Award ID", "Recipient Name", "Recipient UEI", "recipient_id",
                    "Award Amount", "Total Outlays", "Award Type", "Contract Award Type",
                    "Funding Agency", "Funding Agency Code", "Awarding Agency",
                    "Awarding Agency Code", "Description", "generated_internal_id",
                ],
                "sort": "Award Amount",
                "order": "desc",
            }
            url = API_BASE + "/search/spending_by_award/"
            payload = self.fetcher.post_json(url, body)
            snapshot = self.snapshots.save_json(
                session,
                source_kind=SourceKind.USASPENDING,
                source_name=f"USAspending awards {account.native_code} page {page}",
                source_url=url,
                data={"request": body, "response": payload},
                filename=f"awards-{account.native_code}-page-{page}.json",
                reference_period=f"FY{fiscal_year}",
                parser_version=PARSER_VERSION,
            )
            for row in payload.get("results", []):
                award_id = str(
                    row.get("Award ID")
                    or row.get("generated_internal_id")
                    or row.get("internal_id")
                    or ""
                ).strip()
                if not award_id:
                    continue
                recipient = self._recipient(session, row)
                award = session.scalar(
                    select(Award).where(
                        Award.source_kind == SourceKind.USASPENDING,
                        Award.native_id == award_id,
                        Award.fiscal_year == fiscal_year,
                    )
                )
                if award is None:
                    award = Award(
                        source_kind=SourceKind.USASPENDING,
                        native_id=award_id,
                        fiscal_year=fiscal_year,
                        source_snapshot_id=snapshot.id,
                    )
                    session.add(award)
                    session.flush()
                award.generated_internal_id = row.get("generated_internal_id")
                award.description = str(row.get("Description") or "")
                award.award_type = str(
                    row.get("Award Type") or row.get("Contract Award Type") or ""
                ) or None
                award.amount = _decimal_or_none(row.get("Award Amount"))
                award.outlay_amount = _decimal_or_none(row.get("Total Outlays"))
                award.agency_id = agency.id
                award.recipient_id = recipient.id if recipient else None
                award.source_snapshot_id = snapshot.id
                award.metadata_json = {
                    "funding_agency": row.get("Funding Agency"),
                    "awarding_agency": row.get("Awarding Agency"),
                }
                link = session.scalar(
                    select(AwardAccountLink).where(
                        AwardAccountLink.award_id == award.id,
                        AwardAccountLink.federal_account_id == account.id,
                    )
                )
                if link is None:
                    session.add(
                        AwardAccountLink(
                            award_id=award.id,
                            federal_account_id=account.id,
                            amount=(award.outlay_amount if award.outlay_amount is not None else None),
                        )
                    )
                count += 1
            if not (payload.get("page_metadata") or {}).get("hasNext"):
                break
            page += 1
        return count

    def _ingest_named_dimension(
        self,
        session: Session,
        agency: Agency,
        fiscal_year: int,
        *,
        endpoint: str,
        model,
        id_field: str,
        scope: str,
    ) -> int:
        count = 0
        for payload, snapshot_id in self._fetch_paginated(
            session, f"/agency/{agency.native_code}/{endpoint}/", fiscal_year, endpoint
        ):
            for row in payload.get("results", []):
                name = str(row.get("name") or "").strip()
                if not name:
                    continue
                obj = self._named_dimension(model, session, agency.id, name, row.get("code"))
                kwargs = {id_field: obj.id}
                count += self._facts(
                    session,
                    fiscal_year,
                    snapshot_id,
                    row,
                    scope,
                    str(row.get("code") or name),
                    agency_id=agency.id,
                    **kwargs,
                )
        return count

    def _ingest_budget_functions(self, session: Session, agency: Agency, fiscal_year: int) -> int:
        count = 0
        for payload, snapshot_id in self._fetch_paginated(
            session,
            f"/agency/{agency.native_code}/budget_function/",
            fiscal_year,
            "budget-function",
        ):
            for row in payload.get("results", []):
                name = str(row.get("name") or "").strip()
                if not name:
                    continue
                function = self._budget_function(session, name, row.get("code"))
                count += self._facts(
                    session,
                    fiscal_year,
                    snapshot_id,
                    row,
                    "usaspending_budget_function",
                    str(row.get("code") or name),
                    agency_id=agency.id,
                    budget_function_id=function.id,
                )
                for child in row.get("children") or []:
                    child_name = str(child.get("name") or "").strip()
                    if not child_name:
                        continue
                    sub = self._budget_subfunction(
                        session, function.id, child_name, child.get("code")
                    )
                    count += self._facts(
                        session,
                        fiscal_year,
                        snapshot_id,
                        child,
                        "usaspending_budget_subfunction",
                        str(child.get("code") or child_name),
                        agency_id=agency.id,
                        budget_function_id=function.id,
                        budget_subfunction_id=sub.id,
                    )
        return count

    def _facts(
        self,
        session: Session,
        fiscal_year: int,
        snapshot_id: int,
        row: dict,
        scope: str,
        native_key: str,
        **dimensions,
    ) -> int:
        count = 0
        for metric, field in (
            (FinancialMetric.OBLIGATION, "obligated_amount"),
            (FinancialMetric.OUTLAY, "gross_outlay_amount"),
        ):
            value = row.get(field)
            if value is None:
                continue
            session.add(
                SpendFact(
                    fiscal_year=fiscal_year,
                    metric=metric,
                    status=DataStatus.ACTUAL,
                    amount=Decimal(str(value)),
                    source_snapshot_id=snapshot_id,
                    record_scope=scope,
                    native_key=native_key,
                    metadata_json={"source_field": field},
                    **dimensions,
                )
            )
            count += 1
        return count

    def _fetch_paginated(self, session: Session, endpoint: str, fiscal_year: int, label: str):
        page = 1
        while True:
            payload, snapshot_id = self._fetch_one(
                session,
                endpoint,
                params={"fiscal_year": fiscal_year, "page": page, "limit": 100},
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
        rendered = url + ("?" + urlencode(params) if params else "")
        snapshot = self.snapshots.save_json(
            session,
            source_kind=SourceKind.USASPENDING,
            source_name=f"USAspending {label}",
            source_url=rendered,
            data=payload,
            filename=f"{label}.json",
            reference_period=reference_period,
            parser_version=PARSER_VERSION,
        )
        return payload, snapshot.id

    def _upsert_agencies(self, session: Session, payload: dict) -> list[Agency]:
        result = []
        for row in payload.get("results", []):
            code = str(row.get("toptier_code") or "").strip()
            name = str(row.get("agency_name") or "").strip()
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
            result.append(obj)
        return result

    @staticmethod
    def _account(session: Session, agency_id: int, code: str, name: str) -> FederalAccount:
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
    def _treasury_account(
        session: Session, federal_account_id: int, tas: str, name: str
    ) -> TreasuryAccount:
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
        return obj

    @staticmethod
    def _named_dimension(model, session: Session, agency_id: int, name: str, code):
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
        return obj

    @staticmethod
    def _budget_function(session: Session, name: str, code) -> BudgetFunction:
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
    def _budget_subfunction(
        session: Session, function_id: int, name: str, code
    ) -> BudgetSubfunction:
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

    @staticmethod
    def _recipient(session: Session, row: dict) -> Recipient | None:
        name = str(row.get("Recipient Name") or "").strip()
        native = str(row.get("recipient_id") or row.get("Recipient UEI") or name).strip()
        if not native or not name:
            return None
        obj = session.scalar(
            select(Recipient).where(
                Recipient.source_kind == SourceKind.USASPENDING,
                Recipient.native_id == native,
            )
        )
        if obj is None:
            obj = Recipient(
                source_kind=SourceKind.USASPENDING,
                native_id=native,
                name=name,
                uei=row.get("Recipient UEI"),
            )
            session.add(obj)
            session.flush()
        else:
            obj.name = name
            obj.uei = row.get("Recipient UEI") or obj.uei
        return obj


def _decimal_or_none(value):
    if value is None or value == "":
        return None
    return Decimal(str(value))
