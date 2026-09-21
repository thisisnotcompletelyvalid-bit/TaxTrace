# TaxTrace — auditable tax attribution + national public-finance warehouse

TaxTrace is an auditable **“where do my taxes go?”** application. It calculates supported personal taxes, attributes them to government spending without pretending fungible dollars are literally traceable, and connects that receipt to a national multi-jurisdiction public-finance warehouse.

The core rules are simple: **CALCULATED is not MODELED, DIRECT is not ALLOCATED, and overlapping accounting views are not additive.** Dedicated revenues stay restricted to their financing purpose. Fungible revenues are proportionally attributed across eligible actual spending. Additive personalized receipts reconcile exactly after cent rounding.

**Application version: 0.7.1. Methodology version: 1.4.0. Census taxonomy revision: 1.2.0.**

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
- **Census Additive Taxonomy:** official post-2022 state/local Direct General Expenditure parent, machine-audited presentation partition, exact unit-level conservation, and current-vintage national aggregate reconciliation.
- **Real Data Activation:** deployment readiness diagnostics, idempotent national-data initialization, a real government explorer, current machine-readable Treasury controls, and resilient full-year USAspending A/B/C transport.

## Accounting model

The personalized federal receipt is controlled by OMB actual account outlays. Warehouse V2 adds deeper classifications without turning alternate source grains into new piles of spending.

### File B

A full-year USAspending File B release may partition an already-attributed OMB federal-account amount across program activity × object class using File B outlay shares. OMB and File B government totals are shown independently and are never added together.

### File C

File C is award-financial activity, not proof that an entire federal account consists of awards. TaxTrace uses matching full-year File B account outlay as the denominator and File C outlay as the numerator. Only the defensible File C fraction of the personalized OMB account may enter the award view; remaining dollars stay an explicit residual.

Repeated File C rows are collapsed to canonical award identity before personalized shares are calculated. Blank identities remain explicit unlinked activity.

### D1 / D2 / File F

D1 and D2 are prime-award transaction grains. File F is downstream subaward detail. Their transaction, obligation, award, and subaward monetary fields do not create additional personalized dollars.

The validated identity relationship is:

```text
File C award_unique_key
↔ D1 contract_award_unique_key
↔ D2 assistance_award_unique_key
↔ File F prime_award_unique_key
```

This is an identity crosswalk, not permission to raw-join or sum the grains.

## Census state/local additive taxonomy

Warehouse V2 preserves the Census public-use source grain. Raw Census finance rows are not automatically additive.

Release 0.7.0 establishes **Direct General Expenditure** as the first nationwide additive state/local parent for the supported post-2022 code system. Parent membership is a literal 72-code combined State and Local Government Finances formula, not a generated E/F suffix rule.

Important membership rules include:

- fire protection `E24` / `F24` is included;
- state-only `E54` / `F54` is excluded;
- utilities 91–94 and liquor-store activity 90 are outside the parent;
- obsolete G/K capital families are not additive beside consolidated F;
- `I89` general-debt interest and `J19` education subsidies retain special semantics;
- transfers and nonmember rows remain excluded rather than being silently absorbed.

For one government, the TaxTrace presentation children plus any explicit residual equal that government's Direct General Expenditure exactly.

Census aggregate controls are treated as a distinct grain. The current revised 2022 live gate validates:

```text
individual-government DGE sum     $4,081,976,281,000
22statetypepu national DGE         $4,082,022,589,000
GS00LOCALFIN national DGE          $4,082,022,589,000
aggregate public-use vs GS gap     $0
aggregate-stage adjustment         +$46,308,000
```

The $46.308 million adjustment remains a Census aggregate-stage reconciliation fact and is **not** redistributed across individual governments.

See `docs/CENSUS_ADDITIVE_TAXONOMY.md` and `docs/METHODOLOGY.md` for the complete contract.

## Federal Search V2

Federal Search V2 searches normalized full-year D1/D2 and File F Parquet directly with DuckDB instead of copying award-scale rows into the legacy relational search table.

Public-data search:

```text
GET /v2/search/federal?q=Acme&fiscal_year=2025&limit=20
```

Receipt-aware search:

```text
POST /v2/search/federal
```

Receipt-aware search may annotate a prime award or recipient only with personalized amounts already produced by the conserved File C projection. File F never receives its own personalized amount.

## National warehouse status

The complete real-source 2022 Census activation validation loaded:

- **92,114** government-unit source records;
- **88,819** governments with finance facts;
- **1,337,594** normalized finance facts;
- **211** finance classifications/item codes;
- a normalized Parquet mirror of the real finance release.

The activation gate also requires a real government's supported 2022 Direct General Expenditure partition to conserve exactly.

A populated official USAspending FY2022 account validation materialized:

- **172 File A rows**;
- **2,557 File B rows**;
- **828,069 File C rows**.

A separate federal-wide March 1, 2022 Custom Award Data Download validation materialized:

- **29,507 D1 contract prime-transaction rows**;
- **16,111 D2 assistance prime-transaction rows**;
- **2,327 contract File F subaward rows**;
- **4,402 assistance File F subaward rows**.

The bounded award slice validates schemas, classification, identity keys, and materialization; it is not represented as complete annual product coverage.

## Real data activation

A running API is not evidence that the deployment contains the national warehouse. TaxTrace 0.7.1 exposes the distinction directly:

```text
GET /v2/data/product-readiness
```

or from the repository:

```bash
make data-status
```

A fresh or fixture-scale database reports `FIXTURE_OR_EMPTY`. National state/local readiness is only asserted after the deployed database reaches the validated Census scale and the required normalized data objects are physically available.

To populate missing product layers idempotently:

```bash
make activate-product
```

The initializer can populate the national Census registry/finance baseline, real Treasury and OMB federal controls, and full-year USAspending account detail. Already-ready expensive layers are skipped.

The standard Docker Compose stack includes the same one-shot initializer before the API. Database, raw-data, and warehouse-lake locations must use persistent storage if the populated deployment is expected to survive container recreation.

Full-year USAspending activation uses two explicit product source grains: File A/B remain Treasury Account-level, while File C is requested at Federal Account × award grain because TaxTrace's conservative award projection is controlled at the federal-account level. File C may be transport-sharded across the exact current reporting-agency universe, but every shard must succeed. Each logical release retains its own fiscal-year/period-12 request provenance, and A/B/C remain non-additive.

See `docs/REAL_DATA_ACTIVATION.md` and `docs/DATA_SOURCES.md` for the deployment and source contracts.

## Web routes

- `/` — Federal Product V2 receipt and explorer.
- `/search` — Federal Search V2 over Warehouse V2 awards/recipients/subawards.
- `/governments` — real Census government search, source coverage, and supported additive finance partition.
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
GET /v2/data/product-readiness
GET /v2/data/catalog
GET /v2/data/stats
GET /v2/data/census-taxonomy?fiscal_year=2022
GET /v2/data/governments/search?q=Gainesville
GET /v2/data/governments/{id}/coverage
GET /v2/data/governments/{id}/finance
GET /v2/data/governments/{id}/detail
GET /v2/data/governments/{id}/finance-partition?fiscal_year=2022
```

Stable V1 compatibility surfaces remain available during staged migration.

## Deterministic quick-mode example

For a 2026 single filer with `$50,000` of W-2 wages, the deterministic fixture stack currently produces:

- supported federal personal tax liability: **$7,645.00**;
- Phase 9A modeled Florida state sales tax: **$791.35**;
- modeled Alachua discretionary surtax: **$197.84**;
- total supported calculated + modeled tax: **$8,634.19**.

The sales-tax estimate is labeled `MODELED`, confidence `C`. Unsupported tax incidence is not inferred from wages.

## Codespaces / no-Docker run

Requirements: Python 3.11+, Node.js 22+ recommended, npm, Git.

```bash
git pull origin main
python3 -m venv .venv
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

The no-Docker development bootstrap may use fixtures. Run `make data-status` before interpreting an empty or small result set as national product coverage.

## Warehouse CLI

```bash
taxtrace data catalog
taxtrace data seed
taxtrace data stats
taxtrace data bootstrap-national --no-2024-sample
taxtrace data bootstrap-federal-accounts --fiscal-year 2025 --period 12
taxtrace data bootstrap-federal-awards --fiscal-year 2025
```

Product activation shortcuts:

```bash
make activate-product
make data-status
```

## State/local roadmap

0.7.0 completes the official additive Census expenditure taxonomy. Release 0.7.1 makes the real national data path deployable and visible without changing that taxonomy's accounting semantics. The next product phase is **0.7.5 jurisdiction resolution**: determine the applicable state, county, municipality, school district, and relevant special districts without treating overlapping geographies as additive spending.

After jurisdiction resolution, **0.8.0** can connect supported state/local personal tax liabilities to the Census additive spending parent for a nationwide receipt bridge.

## Tests and release validation

```bash
pytest
ruff check src apps tests
python -m compileall -q src apps alembic
```

Normal CI runs migrations, a standalone Next.js production build, and no-Docker API/browser E2E.

The dedicated Census taxonomy validation downloads current official controls and requires exact aggregate reconciliation while preserving the individual-government vs aggregate-stage distinction.

The **Product Data Activation Live Validation** gate starts from a clean PostgreSQL database, imports the real national Census sources, requires the validated national scale, and exercises a real government's additive partition.

The **Federal Product Data Live Validation** gate starts from a clean PostgreSQL database, ingests current real Treasury and OMB sources, materializes full-year USAspending account data, and requires a substantive File B-backed Federal Product V2 receipt with exact conservation.

These real-source gates are separate from fixture tests. A fixture-scale database cannot satisfy the product-readiness release contract.

## Repository map

```text
apps/
  api/                         FastAPI V1/V2 APIs
  web/                         Next.js federal, search, government, and Florida surfaces
src/taxtrace/
  tax/                         federal tax engine
  finance/                     federal snapshots and legacy ingestion
  allocation/                  controlling federal receipt engine
  jurisdictional/              phases 7, 8, and 9A
  warehouse_v2/                national warehouse + V2 receipt/award/search/Census taxonomy
  data/source_catalog_v2.json  authoritative warehouse source manifest
  methodology/                 invariants + centralized methodology version
data/
  fixtures/                    deterministic test fixtures
  raw/                         downloaded source archives, git-ignored
  warehouse/lake/              normalized Parquet lake, git-ignored
docs/
  CENSUS_ADDITIVE_TAXONOMY.md
  DATA_WAREHOUSE_V2.md
  FEDERAL_PRODUCT_V2.md
  FEDERAL_SEARCH_V2.md
  PHASE_7_8_9A.md
  PRODUCT_SCOPE.md
  REAL_DATA_ACTIVATION.md
  METHODOLOGY.md
```

## Scope note

TaxTrace is public-finance/research software, not tax-return preparation, tax advice, or legal advice. The personalized receipt reflects supported inputs and explicit methodology. It does not claim fungible government dollars can be literally followed from one taxpayer to one check.

## License

MIT.
