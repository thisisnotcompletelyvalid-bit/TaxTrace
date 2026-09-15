# TaxTrace Data Warehouse V2

## Why this exists

The original TaxTrace implementation proved tax calculation, financing-pool attribution, conservation, provenance, drilldown, and search. It did not contain enough public-finance data to support the intended nationwide product. Warehouse V2 is the national data foundation that separates authoritative source grains from the personalized accounting views built on top of them.

## Design doctrine

TaxTrace preserves source grain instead of forcing every government into one tree. A dollar can have multiple classifications: function, department, fund, program, object, project, vendor, recipient, award, account, and geography. Those classifications can overlap and are not automatically additive children.

Coverage is also data. A government/year/grain can report whether TaxTrace has a full census, sample, audited statement, native ledger, federal submission, or fallback source. Missing coverage is exposed rather than silently replaced with invented detail.

## Storage architecture

### Relational hot store

SQLite remains supported for development and validation; PostgreSQL is the production target. Warehouse V2 includes:

- `dataset_definition` for the authoritative source catalog;
- `dataset_release` for immutable vintages and ingestion state;
- `government_identifier` for Census and future external-ID crosswalks;
- `finance_classification` for native and standardized codes without assuming one hierarchy;
- `government_finance_fact` for standardized state/local finance facts;
- `detailed_spend_fact` for frequently queried native/federal detail;
- `coverage_record` for completeness, grain, and quality;
- `bulk_object` for raw or normalized lake objects outside the relational hot path.

### Raw + columnar lake

`data/raw/` holds downloaded source archives. `data/warehouse/lake/` holds normalized high-cardinality data, normally Parquet with Zstandard compression. Both are git-ignored. Git stores parsers, source manifests, mappings, tests, documentation, and small deterministic fixtures rather than gigabytes of government records.

Interactive government-level lookups can use SQL while national scans, award-scale search, historical comparisons, and future analytics operate over compressed columnar data.

## Nationwide state/local backbone

### Government registry

The 2022 Census Government Units file provides the national government universe and Census government identifiers. The real source archive has been exercised in CI and full-import validation.

The validated full registry import read **92,114 government-unit source records** and produced **92,078 jurisdictions from the registry**.

### Finance baseline

The first nationwide finance layer is:

1. the **2022 Census of Governments Finance Individual Unit File**, the complete five-year census baseline;
2. the **2024 Annual State & Local Government Finance Individual Unit Files**, a fresher annual-survey sample overlay.

The individual-unit format supplies a Census government ID, native finance item code, and amount. Source amounts reported in thousands are normalized to dollars while retaining native code, vintage, provenance, and release metadata.

Annual survey coverage is never presented as complete local-government coverage. `coverage_record.completeness` distinguishes census and sample sources.

### Full 2022 scale validation

A clean GitHub Actions import of the official 2022 registry + finance census validated the current architecture at national scale:

- **92,114** government-unit source records;
- **88,819** governments with 2022 finance facts;
- **1,337,594** normalized finance facts;
- **211** distinct finance item codes;
- **1,337,594** matching Parquet rows;
- **88,819** distinct governments in the Parquet mirror;
- **211** distinct item codes in the Parquet mirror;
- about **495 MB** for the validation SQLite database;
- about **4.4 MB** for the compressed normalized Census-finance Parquet file.

SQL and Parquet row counts are required to agree. The full national validation remains a manual release gate rather than a cost paid on every commit.

### Census additivity status

Native Census finance item-code rows are preserved as native classifications and remain non-additive until TaxTrace establishes an official defensible mapping into mutually exclusive receipt categories. Components and rollups can coexist in the source, so raw item-code totals must not be summed naively.

The next major state/local milestone is the **official Census additive taxonomy**. That taxonomy must identify which codes form a complete mutually exclusive expenditure partition, how intergovernmental and enterprise flows are treated, and which rows remain context-only.

## Federal backbone

Treasury and OMB remain authoritative controls for federal totals and account structure. Warehouse V2 ingests official USAspending DATA Act and Custom Award Data Download grains:

- **File A:** Treasury-account balances;
- **File B:** Treasury account × program activity × object class;
- **File C:** Treasury account × award-financial linkage;
- **File D1:** contract prime-award transactions and attributes;
- **File D2:** assistance prime-award transactions and attributes;
- **File F:** contract and assistance subawards.

All six families are implemented. They are not six additive piles of spending.

### Asynchronous USAspending downloads

USAspending returns generated-download metadata before the eventual object is necessarily downloadable. TaxTrace polls the official status endpoint and waits for the terminal `finished` state before attempting to retrieve the archive. Real validation observed `ready` before the generated file was reliably accessible.

Request provenance is stored with the release. Manual award ingestion therefore requires the exact request JSON used to generate the archive.

### Real File A/B/C validation

A populated FY2022 account validation successfully materialized:

- **172 File A rows**;
- **2,557 File B rows**;
- **828,069 File C rows** across assistance, contract, and unlinked award-financial files.

The real files were classified from schema rather than filename assumptions and materialized into separate normalized Parquet datasets.

### Real D1/D2/File F validation

The prime/subaward release gate was validated against the official Custom Award Data Download endpoint on September 14, 2026. The bounded request used all federal agencies and a one-day FY2022 action-date window of **March 1, 2022**.

The generated ZIP contained:

- D1 contract prime transactions: **29,507 rows**, **297 columns**;
- D2 assistance prime transactions: **16,111 rows**, **112 columns**;
- File F contract subawards: **2,327 rows**, **118 columns**;
- File F assistance subawards: **4,402 rows**, **113 columns**.

TaxTrace materialized **45,618 D1/D2 rows** and **6,729 File F rows** into four separate Parquet parts. Every required part was nonzero and every generated Parquet object existed.

The live filenames identify D1/D2 as `PrimeTransactions`, so the source catalog records their grain as `prime_award_transaction`, not one-row-per-award summaries.

### Award identity crosswalk

The real archive and upstream USAspending mappings validate:

```text
File C: award_unique_key
D1:     contract_award_unique_key
D2:     assistance_award_unique_key
File F: prime_award_unique_key
```

These correspond to USAspending's generated award identity and support:

```text
File C financial linkage
→ collapsed prime-award identity
→ D1/D2 transaction + recipient attributes
→ File F subaward/subrecipient detail
```

This is an **identity crosswalk, not an additive join**. File C and D1/D2 can both repeat the same identity. Raw row-to-row joins can therefore create many-to-many fan-out and multiply monetary values. File F is downstream of the prime award and must never be added beside the prime award as another federal expenditure.

The machine-readable relationship specification is in `src/taxtrace/warehouse_v2/usaspending_award_crosswalk.py`.

## Federal Product V2

Application 0.6.0 connected Warehouse V2 to the personalized federal receipt.

- OMB actual account outlays remain the controlling additive parent.
- Full-year File B partitions an already-attributed account across program activity × object class.
- File C can receive personalized award attribution only for the defensible share of the File B account represented by full-year File C award-financial outlays.
- Repeated File C rows collapse to canonical award identity before allocation.
- Uncovered account activity remains an explicit residual.
- D1/D2 and File F are non-additive descriptive drilldown grains.

See `docs/FEDERAL_PRODUCT_V2.md` and methodology 1.3.0.

## Federal Search V2

Application 0.6.5 adds award-scale search directly over normalized full-year D1/D2 and File F Parquet with DuckDB.

Prime transaction matches collapse to canonical award identity before display. Recipient results group distinct prime identities by recipient name/UEI. File F remains downstream subaward context. Search results are discovery/navigation objects and are always non-additive.

Receipt-aware search does not derive personalized amounts from D1/D2 or File F. It may annotate a prime award or recipient only with already-conserved File C personalized allocations. File F never receives an independent personalized amount.

Annual search requires an exact READY `FY{year}` federal-award release. Validation slices remain source-validation evidence only.

See `docs/FEDERAL_SEARCH_V2.md`.

## Native state/local enrichment

Census is the comparable national floor, not the ceiling. Warehouse V2 includes a generic native-ledger mapper that can retain department, fund, account, program, activity, object class, project, vendor, recipient, award/contract identifier, description, and native source key.

For large official checkbooks, raw + Parquet is the default. Frequently queried slices can be materialized into `detailed_spend_fact`. Richer local portals can therefore add depth without breaking the national schema.

## Commands

Core warehouse inspection:

```bash
taxtrace data catalog
taxtrace data seed
taxtrace data stats
```

Census national baseline:

```bash
taxtrace data bootstrap-national
taxtrace data bootstrap-national --no-2024-sample
```

Existing Census files:

```bash
taxtrace data inspect-census-finance --file /path/to/2022_Individual_Unit_File.zip
taxtrace data ingest-government-units --file /path/to/govt_units_2022.ZIP
taxtrace data ingest-census-finance --file /path/to/2022_Individual_Unit_File.zip --year 2022
taxtrace data materialize-census-finance --file /path/to/2022_Individual_Unit_File.zip --year 2022
```

USAspending account data:

```bash
taxtrace data bootstrap-federal-accounts --fiscal-year 2025 --period 12
taxtrace data inspect-usaspending-accounts --file /path/to/accounts.zip
taxtrace data ingest-usaspending-accounts --file /path/to/accounts.zip --fiscal-year 2025
```

USAspending prime/subaward data:

```bash
taxtrace data bootstrap-federal-awards --fiscal-year 2025

taxtrace data bootstrap-federal-awards \
  --fiscal-year 2025 \
  --start-date 2025-03-01 \
  --end-date 2025-03-01

taxtrace data inspect-usaspending-awards --file /path/to/awards.zip
taxtrace data ingest-usaspending-awards \
  --file /path/to/awards.zip \
  --fiscal-year 2025 \
  --request-json /path/to/exact-request.json
```

## API

Federal Product/Search V2:

- `POST /v2/receipt/federal`
- `POST /v2/explorer/federal/awards`
- `POST /v2/explorer/federal/award-detail`
- `GET /v2/search/federal`
- `POST /v2/search/federal`

Warehouse V2 data:

- `GET /v2/data/catalog`
- `GET /v2/data/stats`
- `GET /v2/data/governments/search?q=Gainesville`
- `GET /v2/data/governments/{id}/coverage`
- `GET /v2/data/governments/{id}/finance`
- `GET /v2/data/governments/{id}/detail`

Census native finance results are explicitly marked non-additive until the additive taxonomy is available.

## Data-quality and release gates

A source is not promoted merely because a parser exists. Release gates include:

1. source provenance and release/vintage identification;
2. native record-count sanity checks;
3. identifier and classification validation;
4. unit normalization tests;
5. coverage/completeness labeling;
6. duplicate-key checks;
7. reconciliation to an authoritative parent where one exists;
8. explicit additive/non-additive semantics;
9. synthetic regression tests;
10. real-source smoke tests;
11. full-scale import validation for unusually large foundational datasets.

Normal CI runs Python tests, Ruff/compile checks, Alembic migrations, a standalone Next.js production build, and no-Docker API/browser E2E.

Validated manual gates currently include:

- complete 2022 Census government registry + finance import;
- populated USAspending File A/B/C archive validation;
- USAspending D1/D2/File F validation with real canonical identity-key checks.

## Next ingestion/product order

The national registry, Census finance baseline/sample framework, all six federal USAspending source families, Federal Product V2, and Federal Search V2 are implemented.

The highest-value next work is now state/local product breadth:

1. **Official Census additive taxonomy (0.7.0):** build a defensible mutually exclusive expenditure partition from Census finance item codes, with explicit transfer/enterprise/rollup treatment and conservation tests;
2. **Geographic/jurisdiction resolution (0.7.5):** resolve user-selected locations to applicable state, county, municipal, school, and later special-district governments with explicit coverage;
3. **Nationwide state/local receipt V2 bridge (0.8.0):** connect supported tax liabilities and Census additive spending partitions for resolved jurisdictions;
4. **Tax Model V2 / Phase 9B (0.8.5):** richer optional inputs and improved modeled consumption where actual taxable bases are unknown;
5. **native-ledger platform adapters:** deeper state/local transaction, vendor, contract, grant, and project detail after the comparable national floor is operational;
6. Census public employment/payroll and public pensions as contextual enrichment rather than 1.0 blockers.

The governing rule remains breadth first through authoritative standardized data, then depth through native sources, without sacrificing provenance, additive semantics, or conservation.
