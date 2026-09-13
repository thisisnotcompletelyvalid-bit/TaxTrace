# TaxTrace — runnable phases 0–3

TaxTrace is the foundation for an auditable **"where do my taxes go?"** website. This repository fully implements the first four foundation phases defined in the project plan:

- **Phase 0 — engineering/data foundation:** Python package, FastAPI API, Next.js shell, PostgreSQL/SQLite support, Alembic migration, Docker Compose, CI, immutable raw-data snapshots, source registry, and reproducible fixtures.
- **Phase 1 — methodology repository:** versioned operational definitions, funding-pool rules, deficit/transfer rules, source roles, non-additive classification rules, conservation invariants, and ADRs.
- **Phase 2 — federal tax engine:** versioned 2026 W-2 federal income-tax and employee payroll-tax calculation with filing status, standard deduction, CTC/ODC, the common ACTC formula, Social Security, Medicare, Additional Medicare Tax, calculation explanations, and tests.
- **Phase 3 — federal finance warehouse:** Treasury Combined Statement, OMB Public Budget Database, and USAspending ingestion; normalized federal dimensions; immutable source snapshots; actual/proposed status; funding pools; and reconciliation infrastructure.

**Phase 4 is intentionally not implemented.** The repository does not yet tell a user that `$X went to program Y`; that allocation should only be added after the finance foundation is trusted.

## Fastest local run: Python + SQLite

Python 3.11+ is required.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
python -m pip install -U pip
pip install -e '.[dev]'

alembic upgrade head
taxtrace warehouse seed
taxtrace warehouse ingest-fixtures
taxtrace warehouse status
pytest
uvicorn apps.api.app.main:app --reload
```

After installation you can also run `make bootstrap` to perform the migration, seed the methodology entities, and load the offline fixtures in one command.

Then open:

- API docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`
- Warehouse status: `http://localhost:8000/v1/warehouse/status`

Run a tax calculation from the CLI:

```bash
taxtrace tax federal --income 50000 --filing-status single
```

Or from the API:

```bash
curl -X POST http://localhost:8000/v1/tax/federal \
  -H 'content-type: application/json' \
  -d '{
    "tax_year": 2026,
    "filing_status": "single",
    "wage_income": "50000",
    "spouse_wage_income": "0",
    "qualifying_children_under_17": 0,
    "other_dependents": 0
  }'
```

For a $50,000 single W-2 filer with no dependents, the supported-scope 2026 result is:

- taxable income: `$33,900.00`
- federal income tax: `$3,820.00`
- employee Social Security: `$3,100.00`
- employee Medicare: `$725.00`
- supported-scope personal tax liability: `$7,645.00`

## Run the web shell

With the API already running:

```bash
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000`.

The checked-in frontend uses Next.js `16.3.5` and React `19.3.0`, pinned to current stable releases at the time this repository was generated. The shell exercises the Phase 2 tax API and deliberately does not fabricate a Phase 4 spending receipt.

## Docker Compose

If Docker is installed:

```bash
cp .env.example .env
docker compose up --build -d

docker compose exec api taxtrace warehouse seed
docker compose exec api taxtrace warehouse ingest-fixtures
```

Services:

- web: `http://localhost:3000`
- API: `http://localhost:8000`
- PostgreSQL: `localhost:5432`

The Docker image runs Alembic migrations before starting the API.

## Live federal data ingestion

The repository ships small deterministic fixtures so it remains runnable offline. Research/production values should be loaded from official live sources.

### Treasury Combined Statement

```bash
taxtrace warehouse ingest-treasury --fiscal-year 2025
```

Downloads the FY2025 receipts/outlays workbooks using the official Treasury Combined Statement URL pattern, snapshots the original bytes, parses monetary units, and loads aggregate records.

### OMB Public Budget Database

```bash
taxtrace warehouse ingest-omb --fiscal-year 2025
```

Downloads the current FY2027-edition outlay and receipt workbooks. The parser follows the documented PBD positional schema, converts thousands of dollars to dollars, and marks 2025 and earlier `ACTUAL` while later years are `PROPOSED` under that edition's guide.

### USAspending

Start with a single agency:

```bash
taxtrace warehouse ingest-usaspending --fiscal-year 2025 --agency 012
```

Repeat `--agency` to request multiple top-tier codes, or intentionally request everything:

```bash
taxtrace warehouse ingest-usaspending --fiscal-year 2025 --all-agencies
```

Whole-government USAspending ingestion can make many API requests. A single-agency run is the recommended first live smoke test.

### Reconciliation

After Treasury and OMB are loaded:

```bash
taxtrace warehouse reconcile --fiscal-year 2025
```

This stores the comparison rather than hiding any discrepancy. See `docs/METHODOLOGY.md` for the current PASS/REVIEW/FAIL policy.

## Repository map

```text
apps/
  api/                       FastAPI application
  web/                       Next.js Phase-0/2 shell
src/taxtrace/
  tax/                       federal tax engine and versioned-rule loader
  finance/                   snapshots, sources, seed data, reconciliation
  methodology/               machine-enforced invariants
src/taxtrace/data/
  tax_rules/federal/         packaged runtime tax-year configurations
data/
  tax_rules/federal/         auditable mirror of packaged tax rules
  fixtures/                  deterministic offline ingestion fixtures
  raw/                       immutable downloaded snapshots (gitignored)
docs/
  METHODOLOGY.md             governing methodology v1.0.0
  DATA_SOURCES.md            source/ingestion contracts
  TAX_ENGINE.md              supported tax semantics
  ALLOCATION_ENGINE.md       fixed Phase-4 input/output contract
  architecture/              ADRs
alembic/                     database migration
tests/                       unit, parser, integration, reconciliation tests
```

## Important finance design choice

Federal finance is **not one tree**. The same spending can be described by agency, budget function, account, program activity, object class, award, and recipient. TaxTrace stores these as different scopes so values from overlapping classifications are not accidentally added together.

## Data provenance

Every live download receives a `SourceSnapshot` with:

- source and URL;
- reference period;
- retrieval time;
- SHA-256 digest;
- immutable local archive path;
- parser version.

Government revisions therefore create new snapshots instead of silently rewriting old calculations.

## Tests and quality checks

```bash
pytest
ruff check src apps tests
python -m compileall -q src apps alembic
```

The test suite covers tax boundaries, methodology invariants, OMB and Treasury parser behavior, offline USAspending normalization, API behavior, source snapshot hashing, warehouse fixtures, and reconciliation.

## Scope / legal note

This is public-finance software, not tax-return preparation or tax/legal advice. The tax engine is intentionally narrower than the Internal Revenue Code. See `docs/PRODUCT_SCOPE.md` and `docs/TAX_ENGINE.md` before using results beyond demonstration/research.

## Primary documentation

- `docs/METHODOLOGY.md`
- `docs/DATA_SOURCES.md`
- `docs/TAX_ENGINE.md`
- `docs/ALLOCATION_ENGINE.md`
- `docs/PRODUCT_SCOPE.md`

## License

MIT.
