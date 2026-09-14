# TaxTrace Data Warehouse V2

## Why this exists

The Phase 0–9A repository proved tax calculation, financing-pool attribution, conservation, provenance, and a drill-down/search interface. It did **not** contain enough public-finance data for the intended product. A few federal fixture accounts and a handful of Florida/Gainesville ACFR categories are useful tests, not a serious answer to “where do my taxes go?”

Warehouse V2 changes the data strategy before TaxTrace expands to more jurisdictions.

## Design doctrine

TaxTrace must preserve the source grain instead of forcing every government into one tree. A dollar can have multiple classifications: function, department, fund, program, object, project, vendor, recipient, award, account, and geography. Those are alternate dimensions, not automatically additive children.

Raw Census item-code rows are therefore stored as native classifications and exposed as non-additive until the official Census summary-tabulation formulas define a defensible partition. Federal File A/B/C/D/F grains are likewise kept distinct. Native checkbooks retain their own dimensions.

Coverage is also data. Every government/year/grain can report whether TaxTrace has a full census, an annual sample, an audited statement, a native transaction ledger, a federal submission, or only a fallback source.

## Storage architecture

### Relational hot store

SQLite remains supported for development; PostgreSQL is the production target. Warehouse V2 adds:

- `dataset_definition` — authoritative source catalog;
- `dataset_release` — immutable source vintages and ingestion status;
- `government_identifier` — Census and future external-ID crosswalks;
- `finance_classification` — native/standardized codes without assuming one hierarchy;
- `government_finance_fact` — standardized state/local finance facts;
- `detailed_spend_fact` — materialized native/federal detail used frequently by the application;
- `coverage_record` — completeness/grain/quality for each government and release;
- `bulk_object` — raw or normalized files stored outside the relational hot path.

### Raw + columnar lake

`data/raw/` holds immutable downloaded source files. `data/warehouse/lake/` holds normalized high-cardinality data, normally Parquet with Zstandard compression. Both directories are git-ignored. Git stores parsers, source manifests, hashes/metadata, tests, and tiny fixtures, not gigabytes of government data.

This is deliberate. Award transactions, subawards, and large municipal checkbooks can grow far beyond what should be committed to Git or eagerly materialized into one application table.

## Nationwide state/local backbone

### Government registry

The 2022 Census Government Units/GMAF file provides the national government universe and Census government identifiers. The parser accepts the documented 206-character government-ID record and delimited/workbook fallbacks.

### Finance baseline

The first nationwide finance layer is:

1. **2022 Census of Governments Finance Individual Unit File** — full five-year census baseline;
2. **2024 Annual State & Local Government Finance Individual Unit Files** — fresher annual survey sample overlay.

The individual-unit format supplies a government ID, native three-character finance item code, and amount. Source amounts reported in thousands are normalized to whole dollars while retaining the original code and release metadata.

The annual sample is not presented as complete local-government coverage. `coverage_record.completeness` distinguishes `CENSUS` from `SAMPLE`.

### What the Census layer adds

Instead of eight broad ACFR categories, one government can expose many native lines such as:

- police current operations, construction, land/structures, and equipment;
- fire protection;
- correctional institutions and other corrections;
- judicial/legal activity;
- highways;
- health and hospitals;
- housing/community development;
- parks/recreation;
- natural resources;
- sewerage and solid waste;
- water/electric/gas/transit utilities;
- intergovernmental revenue/expenditure;
- taxes, charges, debt, and assets.

The full native code is preserved even when TaxTrace has not yet loaded a friendly label.

## Federal backbone

TaxTrace retains Treasury and OMB for authoritative aggregate/account controls and expands USAspending ingestion around the DATA Act grains:

- File A — account balances;
- File B — Treasury account × program activity × object class;
- File C — account × award financial linkage;
- File D1/D2 — prime procurement/assistance award attributes;
- File F — subawards.

`taxtrace-data bootstrap-federal-accounts --fiscal-year 2025` requests all-agency File A/B/C account data from the official USAspending asynchronous download endpoint. `taxtrace-data usaspending-submit` accepts exact official download JSON for larger award/subaward jobs without hiding the upstream schema.

Large federal downloads belong in the lake. Materialized application tables should contain the dimensions and aggregates needed for interactive use, not blindly duplicate a 100+ GB federal database.

## Native state and local enrichment

Census provides a comparable national floor; it is not the ceiling. Warehouse V2 includes a generic native-ledger mapper that can retain:

- department;
- fund;
- account;
- program;
- activity;
- object class;
- project;
- vendor;
- recipient;
- award/contract identifier;
- description;
- native source key.

For very large official checkbooks, the default is raw + Parquet storage. Frequently queried slices can be materialized into `detailed_spend_fact`. Jurisdictions with richer portals therefore become more detailed without breaking the national schema.

## Commands

After installation and migration:

```bash
taxtrace-data seed
taxtrace-data stats
```

National Census baseline:

```bash
taxtrace-data bootstrap-national
```

2022 census only:

```bash
taxtrace-data bootstrap-national --no-2024-sample
```

Inspect a Census finance ZIP without loading it:

```bash
taxtrace-data inspect-census-finance --file /path/to/2022_Individual_Unit_File.zip
```

Federal account bulk request:

```bash
taxtrace-data bootstrap-federal-accounts --fiscal-year 2025
```

## API

Warehouse V2 is intentionally separate from the existing tax-receipt API while data coverage is being rebuilt:

- `GET /v2/data/catalog`
- `GET /v2/data/stats`
- `GET /v2/data/governments/search?q=Gainesville`
- `GET /v2/data/governments/{id}/coverage`
- `GET /v2/data/governments/{id}/finance`
- `GET /v2/data/governments/{id}/detail`

The raw Census finance endpoint returns `additive: false` and a warning. This is not cosmetic: the native files contain components and rollups, so the website must not sum them until an explicit additive partition is constructed from official summary-tabulation rules.

## Data-quality gates

The overhaul is not complete merely because tables exist. Before a source is promoted into receipt allocation it must pass:

1. source provenance and release/vintage identification;
2. native record-count sanity checks;
3. government-ID and classification-code validation;
4. amount-unit normalization tests;
5. coverage/completeness labeling;
6. duplicate-key checks;
7. reconciliation to an authoritative parent total where one exists;
8. explicit additive/non-additive semantics;
9. real-source smoke tests in addition to synthetic fixtures.

## Next ingestion order

1. Full 2022 Census government registry and finance census.
2. 2024 annual finance sample overlay.
3. Full FY2025 USAspending File A/B/C account data.
4. Prime awards and subawards into partitioned lake storage.
5. 2022 Census public employment/payroll and current public pensions.
6. State native checkbooks/ledgers, beginning with states that publish machine-readable bulk data.
7. Large-city/county/school/special-district native ledgers.
8. Official Census summary-tabulation formulas to create defensible additive state/local expenditure partitions.
9. Crosswalk the richer warehouse back into the personalized tax-allocation engine.

The guiding rule is breadth first through standardized authoritative sources, then depth through native sources, without sacrificing auditability or conservation.
