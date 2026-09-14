# Federal data sources and ingestion contracts

## U.S. Treasury — Combined Statement of Receipts, Outlays, and Balances

Purpose: completed-year federal aggregate control totals and summary classifications.  
Landing page: https://fiscal.treasury.gov/reports-statements/combined-statement/  
FY2025 file pattern used by the importer:

- `https://fiscal.treasury.gov/system/files/files/reports-statements/combined-statement/cs2025/receipt.xlsx`
- `https://fiscal.treasury.gov/system/files/files/reports-statements/combined-statement/cs2025/outlay.xlsx`

`TreasuryCombinedStatementSource` archives the original workbook bytes, detects the workbook's stated monetary unit, locates the requested fiscal-year column, and fails rather than guessing if units/year cannot be established.

The checked-in Treasury fixture is a compact transcription of FY2025 summary values in dollars. It exists so the project runs offline; live ingestion remains the production path.

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

Purpose: granular federal classification dimensions.  
API root: https://api.usaspending.gov/api/v2  
Documentation: https://api.usaspending.gov/docs/endpoints

The ingestion path currently retrieves:

- top-tier agencies;
- federal accounts and child Treasury accounts;
- object classes;
- program activities;
- budget functions and subfunctions.

For each returned row, obligations and gross outlays are stored as separate facts. Dimension scopes remain separate to prevent accidental summation of overlapping classifications.

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

TaxTrace 0.2.0 additionally uses current USAspending v2 endpoints for deeper, non-additive views:

- agency federal-account, program-activity, object-class, and budget-function endpoints;
- `/api/v2/agency/treasury_account/<TAS>/program_activity/` for Treasury-account→program-activity detail, linked back to its parent federal account;
- `/api/v2/search/spending_by_award/` for optional account-filtered award/recipient detail.

Award ingestion is opt-in for live USAspending runs (`--include-awards`) because it adds requests and award data is a detail classification rather than the authoritative top-level outlay control. The deterministic fixture bundle enables award/recipient tests offline.

OMB actual account outlays remain the primary receipt allocation base. USAspending dimensions subdivide a defensibly crosswalked OMB parent scope and never increase the parent receipt amount.
