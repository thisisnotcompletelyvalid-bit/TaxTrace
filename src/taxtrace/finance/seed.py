from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from taxtrace.db_models import FundingPool, Jurisdiction, PoolSpendRule, RevenuePoolMapping, RevenueType
from taxtrace.enums import AllocationRelation, ConfidenceGrade, JurisdictionLevel, PoolType


def seed_federal_methodology_entities(session: Session) -> None:
    federal = session.scalar(select(Jurisdiction).where(Jurisdiction.code == "US"))
    if federal is None:
        federal = Jurisdiction(code="US", name="United States", level=JurisdictionLevel.FEDERAL)
        session.add(federal)
        session.flush()

    pools = {
        "FED_GENERAL": ("Federal general financing pool", PoolType.GENERAL, "Fungible federal general financing used for proportional allocation."),
        "OASI": ("Old-Age and Survivors Insurance Trust Fund", PoolType.TRUST, "Dedicated OASI financing pool."),
        "DI": ("Disability Insurance Trust Fund", PoolType.TRUST, "Dedicated DI financing pool."),
        "MEDICARE_HI": ("Medicare Hospital Insurance Trust Fund", PoolType.TRUST, "Dedicated Medicare Part A / Hospital Insurance financing pool."),
    }
    pool_objs: dict[str, FundingPool] = {}
    for code, (name, kind, description) in pools.items():
        obj = session.scalar(select(FundingPool).where(FundingPool.code == code))
        if obj is None:
            obj = FundingPool(code=code, name=name, pool_type=kind, jurisdiction_id=federal.id, description=description)
            session.add(obj)
            session.flush()
        pool_objs[code] = obj

    revenue_types = {
        "FED_INCOME_TAX": ("Federal individual income tax", "Personal federal income tax liability in TaxTrace's supported scope."),
        "SS_EMPLOYEE": ("Employee Social Security payroll tax", "Employee 6.2% OASDI payroll tax."),
        "MEDICARE_EMPLOYEE": ("Employee Medicare payroll tax", "Employee 1.45% Hospital Insurance payroll tax."),
        "ADDITIONAL_MEDICARE": ("Additional Medicare Tax", "Additional 0.9% HI tax on earnings over statutory thresholds."),
    }
    revenue_objs: dict[str, RevenueType] = {}
    for code, (name, description) in revenue_types.items():
        obj = session.scalar(select(RevenueType).where(RevenueType.code == code))
        if obj is None:
            obj = RevenueType(code=code, name=name, jurisdiction_id=federal.id, description=description)
            session.add(obj)
            session.flush()
        revenue_objs[code] = obj

    mappings = [
        ("FED_INCOME_TAX", "FED_GENERAL", Decimal("1"), "General-revenue attribution; fungible dollars are allocated proportionally rather than literally traced."),
        ("SS_EMPLOYEE", "OASI", Decimal("5.3") / Decimal("6.2"), "SSA current-law employee OASDI split: OASI 5.30 percentage points of the 6.20% employee rate."),
        ("SS_EMPLOYEE", "DI", Decimal("0.9") / Decimal("6.2"), "SSA current-law employee OASDI split: DI 0.90 percentage points of the 6.20% employee rate."),
        ("MEDICARE_EMPLOYEE", "MEDICARE_HI", Decimal("1"), "Medicare payroll tax finances Hospital Insurance (Part A)."),
        ("ADDITIONAL_MEDICARE", "MEDICARE_HI", Decimal("1"), "Medicare Trustees treat the additional 0.9% tax as HI payroll tax income."),
    ]

    spend_rules = [
        (
            "FED_GENERAL",
            [],
            ["650", "651"],
            AllocationRelation.ALLOCATED,
            ConfidenceGrade.B,
            "General-revenue attribution uses actual OMB account outlays and excludes the Social Security function/subfunction base because OASI/DI financing is separately restricted. Medicare remains eligible because Medicare is materially mixed-funded; the combined Medicare purpose is therefore marked mixed-funding when general and HI contributions meet at this reporting grain.",
        ),
        (
            "OASI",
            ["650", "651"],
            [],
            AllocationRelation.DIRECT,
            ConfidenceGrade.D,
            "OASI employee payroll-tax receipts are restricted to Social Security financing. OMB function/subfunction 650/651 is a broader public spending base that does not cleanly separate OASI from DI at this grain, so the direct relationship is retained but confidence is lowered for incomplete source separation.",
        ),
        (
            "DI",
            ["650", "651"],
            [],
            AllocationRelation.DIRECT,
            ConfidenceGrade.D,
            "DI employee payroll-tax receipts are restricted to Social Security financing. OMB function/subfunction 650/651 is a broader public spending base that does not cleanly separate DI from OASI at this grain, so the direct relationship is retained but confidence is lowered for incomplete source separation.",
        ),
        (
            "MEDICARE_HI",
            ["570", "571"],
            [],
            AllocationRelation.DIRECT,
            ConfidenceGrade.D,
            "Hospital Insurance payroll-tax receipts are restricted to Medicare HI financing. The OMB Medicare 570/571 reporting base also contains Medicare spending financed from other sources, so the direct revenue-to-pool relationship is retained while confidence is lowered for incomplete source separation.",
        ),
    ]
    for pool_code, includes, excludes, relation, confidence, description in spend_rules:
        pool = pool_objs[pool_code]
        rule = session.scalar(
            select(PoolSpendRule).where(
                PoolSpendRule.funding_pool_id == pool.id,
                PoolSpendRule.source_scope == "omb_account_outlay",
                PoolSpendRule.effective_start_year == 2025,
            )
        )
        if rule is None:
            rule = PoolSpendRule(
                funding_pool_id=pool.id,
                source_scope="omb_account_outlay",
                include_subfunction_codes=includes,
                exclude_subfunction_codes=excludes,
                relation=relation,
                confidence=confidence,
                effective_start_year=2025,
                effective_end_year=None,
                description=description,
            )
            session.add(rule)
        else:
            rule.include_subfunction_codes = includes
            rule.exclude_subfunction_codes = excludes
            rule.relation = relation
            rule.confidence = confidence
            rule.description = description

    for revenue_code, pool_code, share, authority in mappings:
        exists = session.scalar(
            select(RevenuePoolMapping).where(
                RevenuePoolMapping.revenue_type_id == revenue_objs[revenue_code].id,
                RevenuePoolMapping.funding_pool_id == pool_objs[pool_code].id,
                RevenuePoolMapping.effective_start_year == 2026,
            )
        )
        if exists is None:
            session.add(
                RevenuePoolMapping(
                    revenue_type_id=revenue_objs[revenue_code].id,
                    funding_pool_id=pool_objs[pool_code].id,
                    share=share,
                    effective_start_year=2026,
                    effective_end_year=None,
                    authority=authority,
                )
            )
    session.commit()
