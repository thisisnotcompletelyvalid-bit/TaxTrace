# TaxTrace — auditable tax attribution + national public-finance warehouse

TaxTrace is an auditable **“where do my taxes go?”** application. It calculates supported personal taxes, attributes them to government spending without pretending fungible dollars are literally traceable, and is being expanded around a national multi-jurisdiction public-finance warehouse.

The core rule is simple: **CALCULATED is not MODELED, and DIRECT is not ALLOCATED.** Dedicated revenues stay restricted to their funding purpose. Fungible revenues are proportionally attributed across eligible actual spending. Additive personalized receipts reconcile exactly after cent rounding.

## What is implemented

- **Phase 0:** Python package, FastAPI, Next.js, SQLite/PostgreSQL, Alembic, CI, immutable source snapshots.
- **Phase 1:** methodology/invariants for DIRECT vs ALLOCATED, transfers, deficits, non-additive classifications, provenance.
- **Phase 2:** versioned 2026 federal W-2 personal tax engine.
- **Phase 3:** Treasury/OMB/USAspending warehouse and reconciliation.
- **Phase 4:** tax → revenue type → financing pool → eligible actual outlays → complete federal receipt.
- **Phase 5:** purpose, agency, account, program-activity, object-class, and award explorer.
- **Phase 6:** indexed search over agencies, accounts, programs, awards, recipients, aliases, abbreviations, and curated synonyms.
- **Phase 7:** modeled Florida state sales tax attributed across FY2025 audited State of Florida governmental-activity expenses.
- **Phase 8:** Alachua County surtax routed through its dedicated school-capital, Wild Spaces & Public Places, and infrastructure purposes; Gainesville FY2025 audited governmental spending is available as a non-additive actual reference.
- **Phase 9A:** statistical quick-mode sales-tax estimation using 2024 BLS Consumer Expenditure income-quintile data and an explicit Florida taxability matrix. It does **not** use `income × sales-tax rate`.
- **Warehouse V2:** national Census government registry and finance ingestion, SQL + Parquet lake storage, coverage metadata, native-ledger schema, and validated USAspending DATA Act File A/B/C bulk ingestion.

Methodology version: **1.2.0**. Application version: **0.4.0**.

## National warehouse status

Warehouse V2 is designed around source grain rather than forcing every government into one additive tree. Function, department, fund, program, object class, project, recipient, vendor, award, account, and geography are treated as dimensions that can overlap.

The complete real-source 2022 Census validation successfully loaded:

- **92,114** government-unit source records;
- **88,819** governments with finance facts;
- **1,337,594** normalized finance facts;
- **211** finance classifications/item codes;
- a matching **1,337,594-row** compressed Parquet mirror.

A populated official USAspending FY2022 validation also successfully materialized **172 File A rows, 2,557 File B rows, and 828,069 File C rows** into separate Parquet datasets. File A/B/C are distinct grains and are explicitly not additive to one another.

See `docs/DATA_WAREHOUSE_V2.md` for architecture, source semantics, commands, validation results, and release gates.

## Codespaces / no-Docker run

Requirements are Python 3.11+, Node.js 22+ recommended, npm, and Git.

```bash
git pull origin main

python3 -m venv .venv        # first run only
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[dev]'

python -m taxtrace.dev_server --reload
```

The backend launcher runs Alembic migrations, seeds financing rules, loads/repairs the deterministic federal + Florida + Gainesville fixture layer when needed, rebuilds search, checks federal reconciliation, and starts FastAPI on internal port 8000.

Leave it running. In another terminal:

```bash
cd apps/web
npm install
npm run dev
```

In GitHub Codespaces, open port **3000** from the Ports tab. The frontend uses a same-origin `/api` proxy to the backend inside the Codespace, so the browser does not need the forwarded port-8000 URL.

Useful routes:

- `/` — federal receipt, explorer, and search
- `/florida` — Florida + Alachua + Gainesville phases 7, 8, and 9A
- backend `/docs` — FastAPI documentation
- backend `/health` — API health/version

For a local run, the website is normally `http://localhost:3000` and API docs are `http://127.0.0.1:8000/docs`.

## Deterministic quick-mode example

For a 2026 single filer with `$50,000` of W-2 wages, the fixture-backed deterministic test currently produces:

- supported federal personal tax liability: **$7,645.00**;
- Phase 9A modeled Florida state sales tax: **$791.35**;
- modeled Alachua discretionary surtax: **$197.84**;
- total supported calculated + modeled tax: **$8,634.19**.

The sales-tax estimate selects the 2024 BLS **second income quintile** and is labeled `MODELED`, confidence `C`. Property tax, fuel tax, utility taxes, communications taxes, fees, employer-side incidence, landlord property-tax incidence, corporate incidence, and tariffs are not inferred from wage income.

## API

Federal receipt:

`POST /v1/receipt/federal`

Florida/Gainesville receipt:

`POST /v1/receipt/florida-gainesville`

Example body:

```json
{
  "tax_year": 2026,
  "spending_fiscal_year": 2025,
  "filing_status": "single",
  "wage_income": "50000",
  "spouse_wage_income": "0",
  "qualifying_children_under_17": 0,
  "other_dependents": 0,
  "household_size": 1
}
```

Other V1 endpoints include:

- `POST /v1/explorer/federal`
- `GET /v1/search?q=food%20stamps`
- `POST /v1/search/federal`
- `GET /v1/warehouse/status`

Warehouse V2 endpoints:

- `GET /v2/data/catalog`
- `GET /v2/data/stats`
- `GET /v2/data/governments/search?q=Gainesville`
- `GET /v2/data/governments/{id}/coverage`
- `GET /v2/data/governments/{id}/finance`
- `GET /v2/data/governments/{id}/detail`

Raw Census item-code results are marked non-additive. Native components and rollups must not be summed until an explicit additive partition has been constructed.

## Phase 7 — Florida

Florida quick mode does not invent a state individual income-tax liability. The modeled 6% general sales-tax component is attributed proportionally across FY2025 audited State of Florida governmental-activity expenses. That is `ALLOCATED` attribution, not literal tracing.

The additive state expenditure partition covers general government, education, human services, criminal justice and corrections, natural resources/environment, transportation, judicial branch, and indirect interest on long-term debt.

## Phase 8 — Alachua + Gainesville

The current 1.5% Alachua discretionary surtax is modeled from consumption and then kept in separate legal-purpose pools:

- 0.5 percentage point school capital outlay;
- 0.5 percentage point Wild Spaces & Public Places;
- 0.5 percentage point local-government infrastructure / Streets, Stations & Strong Foundations.

For WSPP and the local-government infrastructure layer, TaxTrace uses the official population-based distribution of **56.98% Alachua County, 35.45% Gainesville, and 7.57% other municipalities**.

Gainesville FY2025 audited governmental-activity expenditures total **$185,815,738** in the deterministic source transcription. They are displayed as `ACTUAL`, but quick mode does not assign that spending to the user because wages alone do not establish a defensible property-tax, utility-tax, fee, or other city liability.

## Phase 9A — statistical sales-tax estimate

The first estimator uses 2024 BLS Consumer Expenditure income-quintile expenditure totals. Quick-mode wages are an explicit proxy for BLS income before taxes. A versioned TaxTrace category-taxability matrix uses mutually exclusive expenditure components so parent/subcategory totals are not double-counted.

Florida's general state sales-tax rate is 6%. Alachua's current discretionary surtax is 1.5%. Florida law generally caps discretionary surtax to the first `$5,000` of many individual tangible-personal-property transactions. Because quick mode has no transaction history, 9A exposes a limited approximation only for the modeled vehicle-purchase component rather than representing the cap as an exact statutory calculation.

See `docs/PHASE_7_8_9A.md` and `docs/PRODUCT_SCOPE.md` for the source and methodology audit trail.

## CLI examples

Core application:

```bash
taxtrace tax federal --income 50000 --filing-status single
taxtrace receipt federal --income 50000 --filing-status single --spending-fiscal-year 2025
taxtrace search query "food stamps"
taxtrace warehouse status
```

National data warehouse:

```bash
taxtrace data catalog
taxtrace data seed
taxtrace data stats
taxtrace data bootstrap-national --no-2024-sample
taxtrace data bootstrap-federal-accounts --fiscal-year 2025 --period 12
```

Existing source files can be inspected or ingested directly:

```bash
taxtrace data inspect-census-finance --file /path/to/2022_Individual_Unit_File.zip
taxtrace data ingest-census-finance --file /path/to/2022_Individual_Unit_File.zip --year 2022
taxtrace data inspect-usaspending-accounts --file /path/to/accounts.zip
taxtrace data ingest-usaspending-accounts --file /path/to/accounts.zip --fiscal-year 2025
```

## Live federal data ingestion

The project remains fixture-runnable. Legacy API-oriented federal ingestion is still available:

```bash
taxtrace warehouse ingest-treasury --fiscal-year 2025
taxtrace warehouse ingest-omb --fiscal-year 2025
taxtrace warehouse ingest-usaspending --fiscal-year 2025 --agency 012 --include-awards
```

For large DATA Act account downloads, prefer the Warehouse V2 bulk path. USAspending bulk jobs are asynchronous: TaxTrace polls until a terminal `finished` state before attempting to download the generated archive.

## Tests and release validation

```bash
pytest
ruff check src apps tests
python -m compileall -q src apps alembic
```

Normal GitHub Actions CI also runs migrations, frontend build, no-Docker end-to-end application checks, and a real Census source smoke test.

Two expensive release gates are available as manual workflows:

- **Warehouse Full Import Validation** — imports the complete real 2022 Census government registry and finance census and verifies SQL/Parquet counts;
- **USAspending Live Archive Validation** — generates a real populated A/B/C archive, waits for `finished`, downloads it, classifies the real schemas, and materializes Parquet.

## Repository map

```text
apps/
  api/                         FastAPI application, including /v2/data
  web/                         Next.js UI, including /florida
src/taxtrace/
  tax/                         federal tax engine
  finance/                     federal snapshots and legacy ingestion
  allocation/                  federal receipt engine
  jurisdictional/              phases 7, 8 and 9A
  warehouse_v2/                national catalog, Census, lake, native, USAspending bulk
  data/source_catalog_v2.json  authoritative warehouse source manifest
  explorer.py                  federal drill-down engine
  search.py                    federal portable search index
  methodology/                 machine-enforced invariants
  data/statistical/            versioned 9A model data
data/
  fixtures/                    deterministic test fixtures
  raw/                         downloaded source archives, git-ignored
  warehouse/lake/              normalized Parquet lake, git-ignored
docs/
  DATA_WAREHOUSE_V2.md
  PHASE_7_8_9A.md
  PRODUCT_SCOPE.md
  METHODOLOGY.md
alembic/
tests/
```

## Scope note

TaxTrace is public-finance/research software, not tax-return preparation, tax advice, or legal advice. The personalized receipt reflects supported inputs and explicit methodology. It does not claim fungible government dollars can be literally followed from one taxpayer to one check.

## License

MIT.
