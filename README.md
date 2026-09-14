# TaxTrace — runnable phases 0–9A

TaxTrace is an auditable **“where do my taxes go?”** application. It calculates supported federal personal taxes, attributes them to actual federal outlays, adds a Florida/Alachua quick-mode sales-tax estimate, and exposes audited Florida and Gainesville public-finance data without pretending modeled or fungible dollars are literally traceable.

The core rule is simple: **CALCULATED is not MODELED, and DIRECT is not ALLOCATED.** Dedicated revenues stay restricted to their funding purpose. Fungible revenues are proportionally attributed across an eligible actual-spending partition. Every additive personalized receipt reconciles exactly after cent rounding.

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
- **Phase 9A:** first statistical tax-estimation layer. Quick mode uses 2024 BLS Consumer Expenditure income-quintile data plus an explicit Florida taxability matrix to estimate sales tax. It does **not** use `income × sales-tax rate`.

Methodology version: **1.2.0**. Application version: **0.3.0**.

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

The backend launcher runs Alembic migrations, seeds financing rules, loads/repairs the deterministic federal + Florida + Gainesville fixture layer when needed, rebuilds search, checks federal reconciliation, and then starts FastAPI on internal port 8000.

Leave it running. In another terminal:

```bash
cd apps/web
npm install
npm run dev
```

In GitHub Codespaces, open port **3000** from the Ports tab. The frontend uses a same-origin `/api` proxy to the backend inside the Codespace, so the browser does not need to know the forwarded port-8000 URL.

Useful routes:

- `/` — federal receipt, explorer, and search
- `/florida` — Florida + Alachua + Gainesville phases 7, 8, and 9A
- backend `/docs` — FastAPI documentation
- backend `/health` — API health/version

For a truly local run, the website is normally `http://localhost:3000` and API docs are `http://127.0.0.1:8000/docs`.

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

Federal explorer:

`POST /v1/explorer/federal`

Search:

- `GET /v1/search?q=food%20stamps`
- `POST /v1/search/federal` for receipt-aware federal search

Warehouse status:

`GET /v1/warehouse/status`

The status response distinguishes federal `spend_facts` from state/local `jurisdiction_spend_facts`.

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

```bash
taxtrace tax federal --income 50000 --filing-status single
taxtrace receipt federal --income 50000 --filing-status single --spending-fiscal-year 2025
taxtrace search query "food stamps"
taxtrace warehouse status
```

`taxtrace warehouse ingest-fixtures` now loads the deterministic federal and state/local fixture bundle.

## Live federal data ingestion

The project remains fixture-runnable, but live federal commands are available:

```bash
taxtrace warehouse ingest-treasury --fiscal-year 2025
taxtrace warehouse ingest-omb --fiscal-year 2025
taxtrace warehouse ingest-usaspending --fiscal-year 2025 --agency 012 --include-awards
```

A single agency is the recommended live USAspending smoke test because whole-government ingestion can make many requests.

## Tests

```bash
pytest
ruff check src apps tests
python -m compileall -q src apps alembic
```

GitHub Actions also runs a no-Docker end-to-end job that creates a fresh SQLite database, runs all migrations, bootstraps federal + state/local data, starts FastAPI, exercises the federal and Florida/Gainesville receipts, verifies conservation, builds and starts Next.js, loads `/florida`, and sends the Florida receipt request through the same-origin frontend API proxy.

## Repository map

```text
apps/
  api/                         FastAPI application
  web/                         Next.js UI, including /florida
src/taxtrace/
  tax/                         federal tax engine
  finance/                     federal snapshots and ingestion
  allocation/                  federal receipt engine
  jurisdictional/              phases 7, 8 and 9A
  explorer.py                  federal drill-down engine
  search.py                    federal portable search index
  methodology/                 machine-enforced invariants
  data/statistical/            versioned 9A model data
data/
  fixtures/florida/            audited Florida source transcription
  fixtures/gainesville/        audited Gainesville source transcription
  fixtures/                    federal deterministic fixtures
docs/
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
