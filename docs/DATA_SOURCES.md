# Federal data sources and ingestion contracts

## U.S. Treasury — Monthly Treasury Statement Table 9

Purpose: completed-year federal aggregate control totals and summary classifications.  
Fiscal Data API: https://fiscaldata.treasury.gov/api/fiscal_service/v1/accounting/mts/mts_table_9

For current live ingestion, `TreasuryCombinedStatementSource` uses the machine-readable Fiscal Data representation of **Monthly Treasury Statement Table 9** rather than trying to infer structure from Treasury's presentation-oriented Combined Statement Excel workbooks.

For the requested fiscal year, TaxTrace reads the final September fiscal-year records and stores:

- receipt-source detail rows;
- outlay-function detail rows;
- the official total receipts row as a non-additive reconciliation control;
- the official total outlays row as a non-additive reconciliation control.

Amounts are ingested in exact dollars from the API. The parser fails closed unless receipt detail sums exactly to Treasury's receipt control and outlay-function detail sums exactly to Treasury's outlay control. The total rows are never added to their own detail rows.

The historical Combined Statement workbook parser remains in the codebase for compatibility and deterministic parser tests, but it is no longer the live FY2025 aggregate ingestion path. Current Treasury summary workbooks are presentation artifacts whose relevant sheets no longer expose a stable machine-readable cell table.

The checked-in Treasury fixture is a compact transcription of federal summary values in dollars. It exists so the project runs offline; live ingestion remains the production path.

## OMB — Public Budget Database

Purpose: account/bureau/subfunction outlay detail and federal receipts detail.  
Supplemental materials: https://www.whitehouse.gov/omb/information-resources/budget/supplemental-materials/

Current FY2027-edition workbooks used by the importer:

- https://www.whitehouse.gov/wp-content/uploads/2026/04/outlays_fy2027.xlsx
- https://www.whitehouse.gov/wp-content/uploads/2026/04/receipts_fy2027.xlsx

The FY2027 PBD user's guide documents:

- amounts in thousands of dollars;
- the first 13 identifying columns for the outlays and receipts files;
- 2025 and earlier as actual, 2026–2031 as estimates.

TaxTrace converts thousands to dollars and labels historical versus estimated values accordingly.

The checked-in OMB workbooks are deliberately small **schema fixtures**. Their numeric rows are constructed for deterministic reconciliation tests and are not claimed to be the complete official account-level database.

## USAspending API v2

Purpose: granular federal account, program/activity, object-class, award, recipient, and subaward dimensions.  
API root: https://api.usaspending.gov/api/v2  
Documentation: https://api.usaspending.gov/docs/endpoints

### DATA Act account files A/B/C

The production account-data path uses `/api/v2/download/accounts/`, but not at one universal account level. Files A and B are requested at Treasury-account level. File C is requested separately at Federal Account × award grain because the TaxTrace award projection is controlled at federal-account scope. Every completed-year release must preserve its exact request proving fiscal year, reporting period `12`, and account level before it can be used as full-year Federal Product V2 detail.

TaxTrace materializes the three DATA Act account grains separately:

- **File A** — account balances;
- **File B** — program activity × object class account detail;
- **File C** — Federal Account × award financial detail, with Treasury-account monetary activity rolled up by USAspending upstream.

These files are not additive to one another. File B may partition an already-attributed OMB account amount. File C may support only the conservative award projection defined by Federal Product V2. Neither creates a new top-level pool of spending.

TaxTrace activates A/B and C as separate logical requests so their distinct source grains remain explicit. File C may then be transport-sharded across the exact FY/period reporting-agency universe when the all-agency generator is unreliable. Every agency shard is required; TaxTrace refuses incomplete federal coverage. The parent File C release retains the Federal Account-level FY/period request provenance, while the source catalog records that USAspending performed the TAS-to-federal-account rollup upstream.

If USAspending reports an intermediate `ready` state, TaxTrace continues polling. It downloads only after a terminal success such as `finished`, because the generated object is not guaranteed to be retrievable earlier.

### Other USAspending dimensions

The ingestion path also supports:

- top-tier agencies;
- federal accounts and child Treasury accounts;
- object classes;
- program activities;
- budget functions and subfunctions;
- D1/D2 prime-award transaction data;
- File F subaward data.

For normalized dimensional rows, obligations and gross outlays remain separate facts. Source scopes remain separate to prevent accidental summation of overlapping classifications.

The checked-in USDA fixture is a compact USAspending-shaped test bundle. It exists to exercise the production normalizer and pagination behavior offline; use live ingestion for research values.

## IRS — federal tax parameters

2026 rule configuration is stored at `data/tax_rules/federal/2026.json` rather than hard-coded in the engine.

Primary IRS references include:

- 2026 inflation adjustments: https://www.irs.gov/newsroom/irs-releases-tax-inflation-adjustments-for-tax-year-2026-including-amendments-from-the-one-big-beautiful-bill
- Internal Revenue Bulletin / annual inflation material: https://www.irs.gov/irb/2025-45_IRB
- FICA overview: https://www.irs.gov/taxtopics/tc751
- Child Tax Credit: https://www.irs.gov/credits-deductions/individuals/child-tax-credit

## Source snapshot contract

Every live download is archived under `data/raw/<source>/<period>/` with a content-addressed filename. Database metadata records:

- source kind/name/URL;
- reference period;
- retrieval timestamp;
- SHA-256;
- original filename;
- local archive path;
- parser version;
- optional metadata.

Do not edit files inside `data/raw` in place. Re-ingest to create a new snapshot.

## Phase 5–6 USAspending detail

TaxTrace also uses current USAspending v2 endpoints for deeper, non-additive views:

- agency federal-account, program-activity, object-class, and budget-function endpoints;
- `/api/v2/agency/treasury_account/<TAS>/program_activity/` for Treasury-account→program-activity detail, linked back to its parent federal account;
- `/api/v2/search/spending_by_award/` for optional account-filtered award/recipient detail.

Award ingestion is opt-in for legacy live USAspending runs (`--include-awards`) because it adds requests and award data is a detail classification rather than the authoritative top-level outlay control. Warehouse V2 has separate bounded/full-year award-lake workflows for D1/D2/File F.

OMB actual account outlays remain the primary receipt allocation base. USAspending dimensions subdivide a defensibly crosswalked OMB parent scope and never increase the parent receipt amount.
