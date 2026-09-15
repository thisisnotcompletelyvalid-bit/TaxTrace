# TaxTrace Data Warehouse V2

## Why this exists

The Phase 0–9A repository proved tax calculation, financing-pool attribution, conservation, provenance, and a drill-down/search interface. It did **not** contain enough public-finance data for the intended product. A few federal fixture accounts and a handful of Florida/Gainesville ACFR categories are useful tests, not a serious answer to “where do my taxes go?”

Warehouse V2 changes the data strategy before TaxTrace expands to more jurisdictions. It is now the national public-finance foundation for the project.

## Design doctrine

TaxTrace preserves source grain instead of forcing every government into one tree. A dollar can have multiple classifications: function, department, fund, program, object, project, vendor, recipient, award, account, and geography. Those are alternate dimensions, not automatically additive children.

Raw Census item-code rows are therefore stored as native classifications and exposed as non-additive until an official summary-tabulation mapping defines a defensible partition. Federal File A/B/C/D1/D2/F grains are also kept distinct. They are related views of federal activity and must not be added together.

Coverage is also data. Every government/year/grain can report whether TaxTrace has a full census, annual sample, audited statement, native transaction ledger, federal submission, or fallback source.

## Storage architecture

### Relational hot store

SQLite remains supported for development and validation; PostgreSQL is the production target. Warehouse V2 adds:

- `dataset_definition` for the authoritative source catalog;
- `dataset_release` for immutable source vintages and ingestion status;
- `government_identifier` for Census and future external-ID crosswalks;
- `finance_classification` for native/standardized codes without assuming one hierarchy;
- `government_finance_fact` for standardized state/local finance facts;
- `detailed_spend_fact` for frequently used native/federal detail;
- `coverage_record` for completeness, grain, and quality by government/release;
- `bulk_object` for raw or normalized lake objects outside the relational hot path.

### Raw + columnar lake

`data/raw/` holds downloaded source files. `data/warehouse/lake/` holds normalized high-cardinality data, normally Parquet with Zstandard compression. Both are git-ignored. Git stores parsers, source manifests, tests, mappings, and tiny fixtures rather than gigabytes of government records.

This split is deliberate. Interactive government-level lookups can use SQL while national scans, historical comparisons, award-scale data, and future analytics can operate on compressed columnar files.

## Nationwide state/local backbone

### Government registry

The 2022 Census Government Units file provides the national government universe and Census government identifiers. The official archive currently contains an XLSX government-unit workbook; TaxTrace also retains parser fallbacks for delimited/fixed-width variants.

The real 2022 archive has been exercised in CI rather than only through synthetic fixtures. The validated full import read **92,114 government-unit records** and produced **92,078 jurisdictions from the registry**.

### Finance baseline

The first nationwide finance layer is:

1. **2022 Census of Governments Finance Individual Unit File**, the full five-year census baseline;
2. **2024 Annual State & Local Government Finance Individual Unit Files**, a fresher annual-survey sample overlay.

The individual-unit format supplies a Census government ID, native finance item code, and amount. Source amounts reported in thousands are normalized to whole dollars while retaining source code, vintage, provenance, and release metadata.

The annual sample is never presented as complete local-government coverage. `coverage_record.completeness` distinguishes `CENSUS` from `SAMPLE`.

### Full 2022 scale validation

A clean GitHub Actions import of the complete official 2022 registry + finance census validated the current architecture at national scale:

- **92,114** government-unit source records;
- **88,819** governments with 2022 finance facts;
- **1,337,594** normalized finance facts;
- **211** distinct finance classifications/item codes;
- **1,337,594** matching Parquet rows;
- **88,819** distinct governments in the Parquet mirror;
- **211** distinct item codes in the Parquet mirror;
- about **495 MB** for the validation SQLite database;
- about **4.4 MB** for the compressed normalized Census-finance Parquet file.

The SQL and Parquet row counts are required to agree. The full national validation is intentionally a manual release gate rather than a cost paid on every commit.

### What the Census layer adds

Instead of a few broad ACFR headings, one government can expose native finance lines for areas such as police, fire protection, corrections, judicial/legal activity, highways, health, hospitals, housing/community development, parks/recreation, natural resources, sewerage, solid waste, utilities, transit, taxes, charges, intergovernmental flows, debt, and assets.

The native code is preserved even where TaxTrace has not yet attached a friendlier display label.

## Federal backbone

Treasury and OMB remain authoritative controls for federal totals and account structure. Warehouse V2 expands detailed federal ingestion around official USAspending DATA Act and Custom Award Data Download grains:

- **File A:** Treasury-account balances;
- **File B:** Treasury account × program activity × object class;
- **File C:** Treasury account × award financial linkage;
- **File D1:** contract prime-award transactions and attributes;
- **File D2:** assistance prime-award transactions and attributes;
- **File F:** contract and assistance subawards.

All six source families are implemented in the Warehouse V2 ingestion framework. They are not six additive piles of spending.

### Asynchronous download semantics

USAspending returns an eventual `file_url` at submission time, before that object is necessarily downloadable. TaxTrace therefore polls the official status endpoint and does **not** treat `ready` as terminal. Real-source validation observed `ready` before the generated file host was accessible and `finished` once the archive was actually retrievable.

The client refuses an early download from a nonterminal status. This avoids interpreting transient generated-file 403 responses as a permanent network restriction.

### Real A/B/C validation

The manual A/B/C live validation uses FY2022 budget function 250, General Science, Space, and Technology, because it is a compact slice with account data and real contract/assistance awards. The successful official archive contained:

- **172 File A rows**;
- **2,557 File B rows**;
- **828,069 File C rows** across assistance, contracts, and unlinked award files.

TaxTrace classified the real files from their schemas rather than filename assumptions, materialized each grain into separate Parquet objects, and verified each resulting object existed and contained data.

### Real D1/D2/File F validation

The prime/subaward release gate was validated against the real USAspending Custom Award Data Download endpoint on September 14, 2026. The bounded request used all federal agencies, FY2022, and a one-day action-date window of **March 1, 2022**.

The generated ZIP contained four schema families:

- D1 contract prime transactions: **29,507 rows**, **297 columns**;
- D2 assistance prime transactions: **16,111 rows**, **112 columns**;
- File F contract subawards: **2,327 rows**, **118 columns**;
- File F assistance subawards: **4,402 rows**, **113 columns**.

TaxTrace materialized **45,618 D1/D2 rows** and **6,729 File F rows** into four separate Parquet parts. Every required part was nonzero and every generated Parquet object existed.

The live filenames identify the D1/D2 export as `PrimeTransactions`. The source catalog therefore records the D1/D2 grain as `prime_award_transaction`, not one-row-per-award summary data.

### Award identity and cross-grain relationships

The real archive and USAspending's upstream field mappings validate these identity aliases:

```text
File C: award_unique_key
D1:     contract_award_unique_key
D2:     assistance_award_unique_key
File F: prime_award_unique_key
```

They correspond to USAspending's canonical generated award identity (`generated_unique_award_id`, derived from the Broker unique award key). This supports the conceptual path:

```text
File C financial linkage
→ prime award identity
→ D1/D2 transaction/recipient attributes
→ File F subaward/subrecipient detail
```

But this is an **identity crosswalk, not an additive join**. File C can contain repeated rows for an award identity and D1/D2 are transaction grains with repeated award identities. A raw row-to-row join can therefore become many-to-many and multiply both rows and monetary values. Cross-grain views must first collapse, deduplicate, aggregate, or otherwise constrain each side to the intended award-identity grain.

File F is downstream of a prime award. Its amount must never be added beside the prime award as if it were another federal expenditure. It is a drill-down relationship.

The machine-readable relationship specification lives in `src/taxtrace/warehouse_v2/usaspending_award_crosswalk.py` and marks every C↔D↔F crosswalk non-additive with identity-collapse required.

### Federal Product V2 bridge

TaxTrace 0.6.0 connects these warehouse grains to the personalized federal product without changing the controlling accounting base.

- OMB actual account outlays remain the controlling additive federal-account parent.
- File B can partition an already-attributed account into program activity × object class children when a safe full-year release is available.
- File C is not normalized to the whole account. Its full-year account outlay is divided by the matching File B account outlay to determine the maximum personalized award-financial share.
- Repeated File C rows are collapsed by canonical award identity before personalized award shares are assigned.
- Unlinked File C activity is preserved explicitly.
- If File C is negative at the account-total level, exceeds the File B denominator, or otherwise cannot be bounded conservatively, personalized award allocation is refused for that account.
- D1/D2 are queried independently by the already-collapsed identity to provide prime-award transaction and recipient context. They do not add personalized dollars.
- File F subawards are downstream, `additive=false` detail and do not add personalized dollars.
- The product requires full-year File B/File C provenance for annual personalized allocation and a READY full-fiscal-year D1/D2/File F release for annual descriptive award coverage. Bounded validation slices remain validation evidence only.

See `docs/FEDERAL_PRODUCT_V2.md` and methodology 1.3.0 in `docs/METHODOLOGY.md` for the complete formulas, gates, residual behavior, and additivity matrix.

Large federal downloads belong in the lake. Application tables should materialize the dimensions and aggregates needed for interactive use, not blindly duplicate every federal row into one relational table.

## Native state and local enrichment

Census is the comparable national floor, not the ceiling. Warehouse V2 includes a generic native-ledger mapper that can retain department, fund, account, program, activity, object class, project, vendor, recipient, award/contract identifier, description, and native source key.

For large official checkbooks, the default is raw + Parquet storage. Frequently queried slices can be materialized into `detailed_spend_fact`. Jurisdictions with richer portals can therefore become more detailed without breaking the national schema.

## Commands

Warehouse V2 is integrated into the normal `taxtrace` CLI under `data`.

```bash
taxtrace data catalog
taxtrace data seed
taxtrace data stats
```

Download and ingest the Census national baseline, including the 2024 sample overlay:

```bash
taxtrace data bootstrap-national
```

Use only the complete 2022 census baseline:

```bash
taxtrace data bootstrap-national --no-2024-sample
```

Inspect or ingest already-downloaded Census data:

```bash
taxtrace data inspect-census-finance --file /path/to/2022_Individual_Unit_File.zip
taxtrace data ingest-government-units --file /path/to/govt_units_2022.ZIP
taxtrace data ingest-census-finance --file /path/to/2022_Individual_Unit_File.zip --year 2022
taxtrace data materialize-census-finance --file /path/to/2022_Individual_Unit_File.zip --year 2022
```

Request the official USAspending File A/B/C account archive and normalize it after completion:

```bash
taxtrace data bootstrap-federal-accounts --fiscal-year 2025 --period 12
```

Inspect or ingest an existing USAspending account archive:

```bash
taxtrace data inspect-usaspending-accounts --file /path/to/accounts.zip
taxtrace data ingest-usaspending-accounts --file /path/to/accounts.zip --fiscal-year 2025
```

Request and materialize D1/D2 prime transactions and File F subawards:

```bash
taxtrace data bootstrap-federal-awards --fiscal-year 2025
```

A bounded date slice can be requested explicitly:

```bash
taxtrace data bootstrap-federal-awards \
  --fiscal-year 2025 \
  --start-date 2025-03-01 \
  --end-date 2025-03-01
```

Inspect or ingest an existing Custom Award Data Download archive:

```bash
taxtrace data inspect-usaspending-awards --file /path/to/awards.zip
taxtrace data ingest-usaspending-awards \
  --file /path/to/awards.zip \
  --fiscal-year 2025 \
  --request-json /path/to/exact-request.json
```

Manual award ingestion requires the exact request JSON used to generate the source archive. Request provenance is part of the release record, not an optional after-the-fact guess.

The generic `usaspending-submit` command remains available for exact official USAspending payloads. `bulk_awards` maps specifically to `/api/v2/bulk_download/awards/`; the older `awards` kind remains the separate `/api/v2/download/awards/` surface.

## API

Warehouse V2 data is exposed under `/v2/data`; Federal Product V2 adds personalized receipt/explorer endpoints:

- `POST /v2/receipt/federal`
- `POST /v2/explorer/federal/awards`
- `POST /v2/explorer/federal/award-detail`
- `GET /v2/data/catalog`
- `GET /v2/data/stats`
- `GET /v2/data/governments/search?q=Gainesville`
- `GET /v2/data/governments/{id}/coverage`
- `GET /v2/data/governments/{id}/finance`
- `GET /v2/data/governments/{id}/detail`

The Census finance endpoint identifies the native result set as non-additive and returns a warning. Native files can contain components and rollups, so the UI must not sum them until a defensible additive partition is explicitly defined.

## Data-quality and release gates

A source is not promoted merely because a parser exists. The intended gates are:

1. source provenance and release/vintage identification;
2. native record-count sanity checks;
3. identifier and classification validation;
4. unit normalization tests;
5. coverage/completeness labeling;
6. duplicate-key checks;
7. reconciliation to an authoritative parent total where one exists;
8. explicit additive/non-additive semantics;
9. synthetic regression tests;
10. real-source smoke tests;
11. full-scale import validation for unusually large foundational datasets.

Normal CI continues to run Python tests, lint/compile checks, frontend build, no-Docker application E2E, and migrations. Expensive live/full-data workflows remain manual release gates.

The currently validated manual gates are:

- complete 2022 Census government registry + finance import;
- populated USAspending File A/B/C archive validation;
- USAspending D1/D2/File F prime/subaward validation with real crosswalk-key checks.

## Next ingestion/product order

The national registry, 2022 Census finance baseline, 2024 finance-sample framework, all six federal USAspending source families, and the Federal Product V2 receipt/account/award bridge are now implemented.

The next highest-value work is product breadth and discoverability rather than another federal source:

1. **Federal Search V2 (0.6.5):** index D1/D2/File F awards, recipients, subawards, and subrecipients while preserving non-additive search semantics;
2. **Official Census additive taxonomy (0.7.0):** create defensible mutually exclusive state/local receipt categories from native Census finance item codes;
3. **Geographic/jurisdiction resolution (0.7.5):** resolve user-selected locations to applicable state, county, municipal, school, and later special-district governments with explicit coverage;
4. **Nationwide state/local receipt V2 bridge (0.8.0):** connect supported tax liabilities and Census additive spending partitions for resolved jurisdictions;
5. **Tax Model V2 / Phase 9B (0.8.5):** richer optional inputs and improved modeled consumption where actual taxable bases are unknown;
6. **native-ledger platform adapters:** deeper state/local transaction, vendor, contract, grant, and project detail after the comparable national floor is operational;
7. Census public employment/payroll and public pensions as contextual enrichment rather than 1.0 blockers.

The governing rule remains breadth first through authoritative standardized data, then depth through native sources, without sacrificing provenance, additive semantics, or conservation.
