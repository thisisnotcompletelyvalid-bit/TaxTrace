from enum import StrEnum


class FilingStatus(StrEnum):
    SINGLE = "single"
    MARRIED_FILING_JOINTLY = "married_filing_jointly"
    MARRIED_FILING_SEPARATELY = "married_filing_separately"
    HEAD_OF_HOUSEHOLD = "head_of_household"


class CalculationBasis(StrEnum):
    CALCULATED = "CALCULATED"
    MODELED = "MODELED"


class AllocationRelation(StrEnum):
    DIRECT = "DIRECT"
    ALLOCATED = "ALLOCATED"
    TRACED = "TRACED"


class DataStatus(StrEnum):
    ACTUAL = "ACTUAL"
    ENACTED = "ENACTED"
    PROPOSED = "PROPOSED"


class FinancialMetric(StrEnum):
    OUTLAY = "OUTLAY"
    EXPENDITURE = "EXPENDITURE"
    OBLIGATION = "OBLIGATION"
    APPROPRIATION = "APPROPRIATION"
    RECEIPT = "RECEIPT"
    BUDGET_AUTHORITY = "BUDGET_AUTHORITY"


class ConfidenceGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    NA = "N/A"


class SourceKind(StrEnum):
    IRS = "IRS"
    TREASURY = "TREASURY"
    OMB = "OMB"
    USASPENDING = "USASPENDING"
    FIXTURE = "FIXTURE"


class JurisdictionLevel(StrEnum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"
    COUNTY = "COUNTY"
    MUNICIPAL = "MUNICIPAL"
    SCHOOL = "SCHOOL"
    SPECIAL_DISTRICT = "SPECIAL_DISTRICT"


class DimensionKind(StrEnum):
    AGENCY = "AGENCY"
    FEDERAL_ACCOUNT = "FEDERAL_ACCOUNT"
    TREASURY_ACCOUNT = "TREASURY_ACCOUNT"
    PROGRAM_ACTIVITY = "PROGRAM_ACTIVITY"
    OBJECT_CLASS = "OBJECT_CLASS"
    BUDGET_FUNCTION = "BUDGET_FUNCTION"
    BUDGET_SUBFUNCTION = "BUDGET_SUBFUNCTION"


class PoolType(StrEnum):
    GENERAL = "GENERAL"
    TRUST = "TRUST"
    SPECIAL = "SPECIAL"
