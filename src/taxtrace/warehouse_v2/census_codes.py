from __future__ import annotations

from dataclasses import dataclass

# Census government-finance IDs use alphabetic-sequence state-area codes, not FIPS codes.
STATE_AREA = {
    "01": ("AL", "Alabama"), "02": ("AK", "Alaska"), "03": ("AZ", "Arizona"),
    "04": ("AR", "Arkansas"), "05": ("CA", "California"), "06": ("CO", "Colorado"),
    "07": ("CT", "Connecticut"), "08": ("DE", "Delaware"), "09": ("DC", "District of Columbia"),
    "10": ("FL", "Florida"), "11": ("GA", "Georgia"), "12": ("HI", "Hawaii"),
    "13": ("ID", "Idaho"), "14": ("IL", "Illinois"), "15": ("IN", "Indiana"),
    "16": ("IA", "Iowa"), "17": ("KS", "Kansas"), "18": ("KY", "Kentucky"),
    "19": ("LA", "Louisiana"), "20": ("ME", "Maine"), "21": ("MD", "Maryland"),
    "22": ("MA", "Massachusetts"), "23": ("MI", "Michigan"), "24": ("MN", "Minnesota"),
    "25": ("MS", "Mississippi"), "26": ("MO", "Missouri"), "27": ("MT", "Montana"),
    "28": ("NE", "Nebraska"), "29": ("NV", "Nevada"), "30": ("NH", "New Hampshire"),
    "31": ("NJ", "New Jersey"), "32": ("NM", "New Mexico"), "33": ("NY", "New York"),
    "34": ("NC", "North Carolina"), "35": ("ND", "North Dakota"), "36": ("OH", "Ohio"),
    "37": ("OK", "Oklahoma"), "38": ("OR", "Oregon"), "39": ("PA", "Pennsylvania"),
    "40": ("RI", "Rhode Island"), "41": ("SC", "South Carolina"), "42": ("SD", "South Dakota"),
    "43": ("TN", "Tennessee"), "44": ("TX", "Texas"), "45": ("UT", "Utah"),
    "46": ("VT", "Vermont"), "47": ("VA", "Virginia"), "48": ("WA", "Washington"),
    "49": ("WV", "West Virginia"), "50": ("WI", "Wisconsin"), "51": ("WY", "Wyoming"),
}

GOV_TYPE = {
    "0": "STATE", "1": "COUNTY", "2": "MUNICIPAL", "3": "MUNICIPAL",
    "4": "SPECIAL_DISTRICT", "5": "SCHOOL",
}

# Regular Census government-finance function codes. The native 3-character item code is always
# preserved even when TaxTrace does not yet have a label for a code.
FUNCTIONS = {
    "01": "Air transportation",
    "04": "Correctional institutions",
    "05": "Other corrections",
    "12": "Elementary and secondary education",
    "16": "Higher education - other",
    "18": "Higher education - instructional",
    "21": "Other education",
    "22": "Social insurance administration",
    "23": "Financial administration",
    "24": "Fire protection",
    "25": "Judicial and legal",
    "29": "Other government administration",
    "32": "Health",
    "36": "Hospitals",
    "44": "Highways",
    "50": "Housing and community development",
    "52": "Libraries",
    "59": "Natural resources",
    "60": "Parking facilities",
    "61": "Parks and recreation",
    "62": "Police protection",
    "66": "Protective inspection and regulation",
    "67": "Public welfare - categorical cash assistance",
    "68": "Public welfare - other cash assistance",
    "74": "Public welfare - medical vendor payments",
    "75": "Public welfare - other vendor payments",
    "77": "Public welfare institutions",
    "79": "Public welfare - other",
    "80": "Sewerage",
    "81": "Solid waste management",
    "87": "Water transport and terminals",
    "89": "Other and unallocable",
    "91": "Water utility",
    "92": "Electric utility",
    "93": "Gas utility",
    "94": "Transit utility",
}

# The Census manual gives some prefixes double meanings. Keep that complexity explicit instead of
# pretending the first character alone fully defines an item.
INTERGOV_PREFIXES = {"L", "M", "N", "O", "P", "R", "S"}
FUNCTIONAL_EXPENDITURE_PREFIXES = {"E", "F", "G", "I", "J", "K", *INTERGOV_PREFIXES}
FUNCTIONAL_REVENUE_PREFIXES = {"A", "B", "C", "D", "U"}
INTEREST_CODES = {"I89", "I91", "I92", "I93", "I94"}
ASSISTANCE_E_CODES = {"E19", "E67", "E68", "E84"}


def _meaning(code: str) -> tuple[str | None, str | None]:
    prefix = code[:1]
    if prefix == "E":
        return "EXPENDITURE", "Assistance and subsidies" if code in ASSISTANCE_E_CODES else "Current operations"
    if prefix == "I":
        return "EXPENDITURE", "Interest on debt" if code in INTEREST_CODES else "Assistance and subsidies"
    if prefix == "J":
        return "EXPENDITURE", "Assistance and subsidies"
    if prefix == "F":
        return "EXPENDITURE", "Construction"
    if prefix == "G":
        return "EXPENDITURE", "Land, existing structures, and locally reported capital equipment"
    if prefix == "K":
        return "EXPENDITURE", "Equipment"
    if prefix in INTERGOV_PREFIXES:
        return "EXPENDITURE", "Intergovernmental expenditure"
    if prefix == "A":
        return "REVENUE", "Current charges"
    if prefix in {"B", "C", "D"}:
        return "REVENUE", "Intergovernmental revenue"
    if prefix == "T":
        return "REVENUE", "Tax revenue"
    if prefix == "U":
        return "REVENUE", "Utility revenue"
    if prefix == "V":
        return "INSURANCE", "Insurance trust transaction"
    if prefix == "W":
        return "ASSET", "Cash and securities"
    if prefix in {"X", "Y"}:
        return "DEBT", "Debt"
    if prefix == "Z":
        return "ASSET", "Asset or insurance-trust balance"
    return None, None


@dataclass(frozen=True)
class CensusItemClassification:
    code: str
    name: str
    flow_type: str | None
    object_type: str | None
    function_code: str | None
    function_name: str | None
    additive_partition: str | None


def classify_item_code(code: str) -> CensusItemClassification:
    code = code.strip().upper()
    flow_type, object_type = _meaning(code)
    prefix = code[:1]
    function_code = code[1:3] if len(code) == 3 and code[1:3].isdigit() and (
        prefix in FUNCTIONAL_EXPENDITURE_PREFIXES or prefix in FUNCTIONAL_REVENUE_PREFIXES
    ) else None
    function_name = FUNCTIONS.get(function_code) if function_code else None
    if object_type and function_name:
        name = f"{object_type}: {function_name}"
    elif object_type:
        name = f"{object_type} ({code})"
    elif function_name:
        name = f"{function_name} ({code})"
    else:
        name = f"Census government-finance item {code}"

    # Raw item-code files contain both detailed and roll-up relationships that vary by function.
    # Until the official Census summary-tabulation formulas are loaded, raw rows are deliberately
    # non-additive. This prevents TaxTrace from summing overlapping native codes.
    return CensusItemClassification(
        code=code,
        name=name,
        flow_type=flow_type,
        object_type=object_type,
        function_code=function_code,
        function_name=function_name,
        additive_partition=None,
    )
