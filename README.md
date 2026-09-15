# TaxTrace — auditable tax attribution + national public-finance warehouse

TaxTrace is an auditable **“where do my taxes go?”** application. It calculates supported personal taxes, attributes them to government spending without pretending fungible dollars are literally traceable, and connects that receipt to a national multi-jurisdiction public-finance warehouse.

The core rules are simple: **CALCULATED is not MODELED, DIRECT is not ALLOCATED, and overlapping accounting views are not additive.** Dedicated revenues stay restricted to their financing purpose. Fungible revenues are proportionally attributed across eligible actual spending. Additive personalized receipts reconcile exactly after cent rounding.

**Application version: 0.6.5. Methodology version: 1.3.0.**

## What is implemented

- **Phase 0:** Python package, FastAPI, Next.js, SQLite/PostgreSQL, Alembic, CI, immutable source snapshots.
- **Phase 1:** methodology/invariants for DIRECT vs ALLOCATED, transfers, deficits, non-additive classifications, provenance, and refusal behavior.
- **Phase 2:** versioned 2026 federal W-2 personal tax engine.
- **Phase 3:** Treasury/OMB/USAspending finance warehouse and reconciliation.
- **Phase 4:** tax → revenue type → financing pool → eligible actual outlays → complete conserved federal receipt.
- **Phase 5:** purpose, agency, account, program-activity, object-class, and award explorer.
- **Phase 6:** portable legacy search over normalized finance entities.
- **Phase 7:** modeled Florida state sales tax attributed across FY2025 audited Florida governmental-activity expenses.
- **Phase 8:** Alachua County surtax routed through dedicated legal-purpose pools; Gainesville FY2025 audited spending retained as a non-additive actual reference.
- **Phase 9A:** statistical quick-mode sales-tax estimation using 2024 BLS Consumer Expenditure income-quintile data and an explicit Florida taxability matrix.
- **Warehouse V2:** nationwide Census government/finance backbone plus raw + Parquet lake storage, coverage metadata, native-ledger schema, USAspending File A/B/C account ingestion, and D1/D2/File F award/subaward ingestion.
- **Federal Product V2:** OMB-controlled personalized federal accounts, File B program/object partitioning, conservative File C award projection, D1/D2 prime-recipient enrichment, and non-additive File F subaward drilldown.
- **Federal Search V2:** direct full-year D1/D2/File F Parquet search for prime awards, recipients, subawards, and subrecipients, with optional receipt-aware annotation from the existing File C personalized projection.

## Accounting model

The personalized federal receipt is controlled by OMB actual account outlays. Warehouse V2 adds deeper classifications without turning alternate source grains into new piles of spending.

### File B

A full-year USAspending File B release may partition an already-attributed OMB federal-account amount across program activity × object class using File B outlay shares. OMB and File B government totals are shown independently and are never added together.

The current account-download path accepts File B as full-year personalization evidence only when stored request provenance proves reporting period `12`.

### File C

File C is award-financial activity, not proof that an entire federal account consists of awards. TaxTrace therefore uses the matching full-year File B account outlay as the denominator and File C outlay as the numerator.

Only the defensible File C fraction of the personalized OMB account may enter the award view. Remaining dollars stay an explicit non-award/unreconciled residual. If File C cannot be conservatively bounded by File B, TaxTrace refuses award personalization for that account rather than normalizing File C to 100%.

Repeated File C rows are collapsed to canonical award identity before personalized shares are calculated. Blank identities remain explicit unlinked activity.

### D1 / D2 / File F

D1 and D2 are prime-award **transaction** grains. File F is downstream subaward detail. Their transaction, award, obligation, and subaward monetary fields do not create additional personalized dollars.

The validated canonical relationship is:

```text
File C award_unique_key
↔ D1 contract_award_unique_key
↔ D2 assistance_award_unique_key
↔ File F prime_award_unique_key
```

This is an identity crosswalk, not permission to raw-join or sum the grains. File C and D1/D2 can repeat an award identity, so identity collapse is required before enrichment. File F remains downstream of the prime award.

See `docs/FEDERAL_PRODUCT_V2.md` and `docs/METHODOLOGY.md` for the complete accounting rules.

## Federal Search V2

Federal Search V2 searches normalized full-year D1/D2 and File F Parquet directly with DuckDB instead of copying award-scale rows into the legacy relational search table.

D1/D2 matches collapse to canonical prime-award identity before display. Recipient results group distinct prime identities by name/UEI. File F subawards remain downstream search/navigation results. All results expose non-additive semantics.

Public-data search:

```text
GET /v2/search/federal?q=Acme&fiscal_year=2025&limit=20
```

Receipt-aware search:

```text
POST /v2/search/federal
```

Receipt-aware search may annotate a prime award or recipient only with personalized amounts already produced by the conserved File C projection. **File F never receives its own personalized amount.** A subaward may show the prime award's personalized amount as explicitly labeled context, but that amount is not allocated to the subaward.

Only exact READY full-year award releases back annual Search V2 results. Missing releases or missing local Parquet produce explicit coverage states instead of fabricated completeness.

The dedicated web route is `/search`. See `docs/FEDERAL_SEARCH_V2.md` for the detailed search contract.

## National warehouse status

Warehouse V2 preserves source grain rather than forcing every government into one additive tree. Function, department, fund, program, object class, project, recipient, vendor, award, account, and geography can be overlapping dimensions.

The complete real-source 2022 Census validation loaded:

- **92,114** government-unit source records;
- **88,819** governments with finance facts;
- **1,337,594** normalized finance facts;
- **211** finance classifications/item codes;
- **1,337,594** matching compressed Parquet rows.

A populated official USAspending FY2022 account validation materialized:

- **172 File A rows**;
- **2,557 File B rows**;
- **828,069 File C rows**.

A separate federal-wide March 1, 2022 Custom Award Data Download validation materialized:

- **29,507 D1 contract prime-transaction rows**;
- **16,111 D2 assistance prime-transaction rows**;
- **2,327 contract File F subaward rows**;
- **4,402 assistance File F subaward rows**.

That bounded live validation contains **45,618 D1/D2 prime-transaction rows** and **6,729 File F subaward rows**. The bounded slice validates schemas, classification, identity keys, and materialization; it is not represented as complete annual product coverage.

See `docs/DATA_WAREHOUSE_V2.md` for source architecture and release gates.

## Web routes

- `/` — Federal Product V2 receipt and explorer.
- `/search` — Federal Search V2 over Warehouse V2 awards/recipients/subawards.
- `/florida` — Florida + Alachua + Gainesville phases 7, 8, and 9A.
- backend `/docs` — FastAPI/OpenAPI documentation.
- backend `/health` — API health and application version.

## API highlights

Federal Product V2:

```text
POST /v2/receipt/federal
POST /v2/explorer/federal/awards
POST /v2/explorer/federal/award-detail
GET  /v2/search/federal
POST /v2/search/federal
```

Warehouse V2 data:

```text
GET /v2/data/catalog
GET /v2/data/stats
GET /v2/data/governments/search?q=Gainesville
GET /v2/data/governments/{id}/coverage
GET /v2/data/governments/{id}/finance
GET /v2/data/governments/{id}/detail
```

Stable V1 compatibility surfaces remain available during staged migration:

```text
POST /v1/receipt/federal
POST /v1/explorer/federal
GET  /v1/search?q=food%20stamps
POST /v1/search/federal
GET  /v1/warehouse/status
POST /v1/receipt/florida-gainesville
```

Example federal receipt body:

```json
{
  "tax_year": 2026,
  "spending_fiscal_year": 2025,
  "filing_status": "single",
  "wage_income": "50000",
  "spouse_wage_income": "0",
  "qualifying_children_under_17": 0,
  "other_dependents": 0
}
```

## Deterministic quick-mode example

For a 2026 single filer with `$50,000` of W-2 wages, the deterministic fixture stack currently produces:

- supported federal personal tax liability: **$7,645.00**;
- Phase 9A modeled Florida state sales tax: **$791.35**;
- modeled Alachua discretionary surtax: **$197.84**;
- total supported calculated + modeled tax: **$8,634.19**.

The sales-tax estimate is labeled `MODELED`, confidence `C`. Property tax, fuel tax, utility taxes, communications taxes, fees, employer-side incidence, landlord property-tax incidence, corporate incidence, tariffs, and other unsupported incidence are not inferred from wages.

## Codespaces / no-Docker run

Requirements: Python 3.11+, Node.js 22+ recommended, npm, Git.

```bash
git pull origin main
python3 -m venv .venv        # first run only
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'
python -m taxtrace.dev_server --reload
```

In another terminal:

```bash
cd apps/web
npm install
npm run dev
```

In GitHub Codespaces, open port **3000**. The frontend uses a same-origin `/api` proxy to the internal backend.

## Warehouse CLI

```bash
taxtrace data catalog
taxtrace data seed
taxtrace data stats
taxtrace data bootstrap-national --no-2024-sample
taxtrace data bootstrap-federal-accounts --fiscal-year 2025 --period 12
taxtrace data bootstrap-federal-awards --fiscal-year 2025
```

Inspect or ingest existing archives:

```bash
taxtrace data inspect-census-finance --file /path/to/2022_Individual_Unit_File.zip
taxtrace data ingest-census-finance --file /path/to/2022_Individual_Unit_File.zip --year 2022
taxtrace data inspect-usaspending-accounts --file /path/to/accounts.zip
taxtrace data ingest-usaspending-accounts --file /path/to/accounts.zip --fiscal-year 2025
taxtrace data inspect-usaspending-awards --file /path/to/awards.zip
taxtrace data ingest-usaspending-awards --file /path/to/awards.zip --fiscal-year 2025 --request-json /path/to/request.json
```

Manual award ingestion requires the exact request JSON used to generate the archive so release provenance cannot be silently invented after the fact.

## State/local scope

Florida quick mode does not invent a state individual wage-income tax liability. The modeled 6% general sales-tax component is attributed across FY2025 audited State of Florida governmental-activity expenses.

The current 1.5% Alachua discretionary surtax is kept in separate legal-purpose pools for school capital, Wild Spaces & Public Places, and local-government infrastructure. Gainesville FY2025 audited governmental spending is available as an ACTUAL reference but is not assigned to the user unless a defensible personal city liability is known.

The national Census Warehouse V2 backbone is already implemented. The next state/local product phase is an official additive Census finance taxonomy, followed by jurisdiction resolution and a nationwide receipt bridge.

See `docs/PHASE_7_8_9A.md` and `docs/PRODUCT_SCOPE.md`.

## Tests and release validation

```bash
pytest
ruff check src apps tests
python -m compileall -q src apps alembic
```

Normal CI also runs Alembic migrations, a standalone Next.js production build, and a no-Docker end-to-end API/browser smoke. Search V2 CI checks identity collapse, full-year release gating, File F non-additivity, receipt-context reuse of File C amounts, no-lake fallback behavior, both V2 search routes, and the production `/search` page.

Expensive real-source release gates remain manual:

- **Warehouse Full Import Validation** — complete real 2022 Census government registry and finance import;
- **USAspending Live Archive Validation** — real populated File A/B/C archive classification/materialization;
- **USAspending Prime/Subaward Live Validation** — real D1/D2/File F archive validation with canonical crosswalk-key checks.

## Repository map

```text
apps/
  api/                         FastAPI, including /v2/data, /v2/receipt, /v2/explorer, /v2/search
  web/                         Next.js Federal Product V2, /search, and /florida
src/taxtrace/
  tax/                         federal tax engine
  finance/                     federal snapshots and legacy ingestion
  allocation/                  controlling federal receipt engine
  jurisdictional/              phases 7, 8, and 9A
  warehouse_v2/                national warehouse + V2 receipt/award/search services
  data/source_catalog_v2.json  authoritative warehouse source manifest
  explorer.py                  mature V1 core-classification explorer
  search.py                    legacy portable search index
  methodology/                 invariants + centralized methodology version
data/
  fixtures/                    deterministic test fixtures
  raw/                         downloaded source archives, git-ignored
  warehouse/lake/              normalized Parquet lake, git-ignored
docs/
  DATA_WAREHOUSE_V2.md
  FEDERAL_PRODUCT_V2.md
  FEDERAL_SEARCH_V2.md
  PHASE_7_8_9A.md
  PRODUCT_SCOPE.md
  METHODOLOGY.md
```

## Scope note

TaxTrace is public-finance/research software, not tax-return preparation, tax advice, or legal advice. The personalized receipt reflects supported inputs and explicit methodology. It does not claim fungible government dollars can be literally followed from one taxpayer to one check.

## License

MIT.
