# Verification record

Generated: 2026-09-13

## Executed successfully in the generation environment

- `python -m compileall -q src apps alembic`
- `pytest -q` -> **27 passed**
- fresh SQLite `alembic upgrade head`
- `taxtrace warehouse seed`
- `taxtrace warehouse ingest-fixtures`
  - Treasury rows: 32
  - OMB rows: 8
  - USAspending facts created by fixture ingestion: 14 load events / 18 total warehouse spend facts after OMB + USAspending
- `taxtrace warehouse reconcile --fiscal-year 2025`
  - OMB fixture outlay total: $7,009,992,000,000
  - Treasury FY2025 fixture total outlays: $7,009,992,000,000
  - status: PASS
- `taxtrace tax federal --income 50000 --filing-status single`
  - federal income tax: $3,820.00
  - employee Social Security: $3,100.00
  - employee Medicare: $725.00
  - supported-scope total personal tax liability: $7,645.00
- built a Python wheel with `pip wheel --no-deps --no-build-isolation`
- inspected the wheel and confirmed the packaged `taxtrace/data/tax_rules/federal/2026.json` is present
- installed the wheel into an isolated target and successfully calculated the same $7,645.00 result from outside the repository
- parsed `docker-compose.yml` and `.github/workflows/ci.yml` as YAML

## Connected-chat verification

The GitHub-connected chat re-extracted the Phase 0–3 archive and reran the repository from a clean SQLite database on 2026-09-13:

- `python -m pytest` -> **27 passed**
- fresh `alembic upgrade head` -> PASS
- `taxtrace warehouse seed` -> PASS
- `taxtrace warehouse ingest-fixtures` -> Treasury 32 / OMB 8 / USAspending 14
- `taxtrace warehouse reconcile --fiscal-year 2025` -> **PASS**, zero difference between the OMB fixture total and Treasury FY2025 fixture total of $7,009,992,000,000
- `taxtrace tax federal --income 50000 --filing-status single --tax-year 2026` -> supported-scope total personal tax liability **$7,645.00**
- started FastAPI locally and verified:
  - `GET /health` -> HTTP 200
  - `GET /v1/warehouse/status` -> HTTP 200, with 8 source snapshots / 18 spend facts / 5 agencies / 32 Treasury aggregate rows
  - `POST /v1/tax/federal` for a $50,000 single filer -> HTTP 200 and the same $7,645.00 result

This connected-chat verification also confirmed that the GitHub repository contains the Phase 0–3 source tree and deterministic binary fixtures; representative Git blob SHAs match the extracted archive exactly.

## Not executable in the generation environment

Outbound package/file downloads and Docker are disabled in the execution container. Therefore the following were not executed locally here:

- `npm install` / `npm run build`;
- `docker compose up --build`;
- live downloads of the Treasury and OMB XLSX files from inside the container;
- live USAspending HTTP ingestion from inside the container.

The official live URLs/endpoints were independently checked through web access, and the project contains deterministic offline fixtures that exercise the production parsing/normalization paths. GitHub Actions is configured to install dependencies and build the web application on push/PR. Live-source commands fail loudly if the source cannot be downloaded or parsed rather than silently substituting fixture data.
