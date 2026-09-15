# Changelog

## 0.7.0 — 2026-09-14

Completed the official Census additive expenditure taxonomy for the nationwide state/local Warehouse V2 backbone:

- added a year-versioned Census state/local Direct General Expenditure parent and TaxTrace presentation partition for supported post-2022 finance data;
- implemented the combined State and Local Government Finances post-2022 native-code formula as a literal 72-code set rather than inferring additive membership from code prefixes or suffixes;
- included fire-protection current/capital codes `E24`/`F24` in the combined state/local parent and excluded state-only `E54`/`F54`, utilities, liquor-store activity, obsolete G/K capital rows, transfers, and other nonmember native rows;
- preserved special native-code semantics for `I89` general-debt interest and `J19` education subsidies;
- added machine audits proving every official parent code maps to exactly one TaxTrace presentation category;
- added `GET /v2/data/census-taxonomy` and government-level Census expenditure partitioning with explicit excluded native codes, imputation flags, provenance, residuals, and exact conservation;
- kept raw Census finance rows non-additive outside an explicitly constructed taxonomy partition;
- added unit tests and API tests for formula membership, exclusions, duplicate row aggregation, unsupported-year refusal, source-release gating, and exact government-level conservation;
- added an independent live Census validation workflow bound directly to the production taxonomy constants;
- corrected an intermediate source-selection error discovered during validation: the static `programs-surveys/state` SF0176 workbook is State Government Finances methodology and is not the authoritative combined state-and-local formula for this product;
- validated the combined state/local methodology against the current revised 2022 individual-unit file, the bundled `22statetypepu` national aggregate controls, and the current `GS00LOCALFIN` aggregate release.

The live 2022 release gate now proves:

- literal individual-government Direct General Expenditure sum: **$4,081,976,281,000**;
- revised national aggregate public-use control: **$4,082,022,589,000**;
- current `GS00LOCALFIN` Direct General Expenditure control: **$4,082,022,589,000**;
- aggregate public-use vs published control difference: **$0**;
- Census aggregate-stage adjustment relative to the literal individual-government rows: **+$46,308,000**.

The $46.308 million adjustment is preserved as a Census aggregate-stage reconciliation fact. TaxTrace does not redistribute it across individual governments. Government-level partitions therefore conserve the government-level source rows exactly, while national aggregate validation uses Census's aggregate public-use control layer.

Methodology advanced to **1.4.0** because this release establishes a new operational state/local additive-spending rule that will control subsequent nationwide personalized state/local receipts. Application version advanced to **0.7.0**. Census taxonomy revision is **1.2.0**.

## 0.6.5 — 2026-09-14

Added Federal Search V2 over the validated Warehouse V2 award lake:

- added direct DuckDB/Parquet search over full-year USAspending D1/D2 prime transactions and File F subawards instead of copying award-scale rows into the legacy relational search index;
- collapsed repeated D1/D2 transaction rows to the canonical prime-award identity before returning prime-award search results;
- added recipient search grouped over distinct canonical prime-award identities;
- added File F subaward/subrecipient search while preserving File F as downstream, non-additive context;
- required an exact READY full-fiscal-year `FY{year}` award release for annual V2 search coverage; bounded validation slices do not masquerade as annual search data;
- added public `GET /v2/search/federal` and receipt-aware `POST /v2/search/federal` endpoints;
- allowed receipt-aware search to annotate prime awards and recipients only from the existing conserved File C personalized award projection;
- explicitly prevented File F subawards from receiving personalized amounts; a subaward may show its prime award's personalized amount only as labeled navigation context;
- added graceful coverage states when full-year release metadata or local Parquet objects are unavailable;
- added a dedicated `/search` Next.js surface with public-data and optional receipt-context modes plus canonical award-detail navigation;
- linked Federal Search V2 from the global website navigation;
- added regression tests for D1/D2 identity collapse, recipient grouping, full-year release gating, File F non-additivity, receipt-context reuse of File C amounts, and API fallback behavior;
- expanded no-Docker CI to smoke both V2 search routes and the `/search` production page.

Methodology remains **1.3.0**. Search V2 changes discovery, ranking, and navigation, not the tax calculation or personalized allocation rules. Prime-award and recipient receipt annotations reuse already-conserved File C allocations. D1/D2 and File F monetary fields never create additional personalized dollars, and every search result remains non-additive.

## 0.6.0 — 2026-09-14

Completed the first Federal Product V2 release over Warehouse V2:

- made `POST /v2/receipt/federal` the primary federal calculation path used by the Next.js homepage;
- added a conserved full-year File C award-financial projection behind OMB-controlled federal-account attribution;
- used the matching full-year File B account outlay as the denominator for File C award coverage rather than normalizing File C to 100% of an account;
- preserved non-award/unreconciled account activity as an explicit residual;
- collapsed repeated File C rows to the canonical USAspending award identity before personalized shares are calculated;
- preserved blank File C identities as an explicit unlinked bucket;
- refused personalized File C award allocation when File C cannot be conservatively bounded by the File B account denominator;
- added non-additive D1/D2 prime-award transaction/recipient enrichment by canonical identity;
- added non-additive File F subaward/subrecipient drilldown without creating additional personalized dollars;
- required full-fiscal-year D1/D2/File F releases for annual product coverage while keeping bounded source slices as validation evidence only;
- added `/v2/explorer/federal/awards` and `/v2/explorer/federal/award-detail`;
- migrated the federal homepage to show Warehouse V2 File B, File C, recipient, and subaward detail while retaining the mature V1 purpose/agency explorer and V1 search during the staged migration;
- added synthetic regression coverage for File C identity collapse, explicit unlinked activity, partial-period refusal, File C > File B refusal, D1/D2 transaction collapse, and File F non-additivity;
- centralized the machine-readable methodology version so federal and jurisdictional receipts cannot silently drift between hard-coded version strings.

Methodology advanced to **1.3.0** because the File B → File C personalized award projection is a new operational allocation rule. OMB remains the controlling additive federal-account parent. File B and File C are alternate detail views, and D1/D2/File F remain non-additive descriptive relationship grains.

This release also corrects a pre-existing version-reporting inconsistency: the Phase 7–9A documentation identified methodology 1.2.0 while the federal receipt model still emitted its older 1.1.0 default. New results now use the centralized 1.3.0 identifier.

## 0.5.1 — 2026-09-14

Connected the conserved federal personalized receipt to Warehouse V2 File B detail:

- added `POST /v2/receipt/federal`;
- kept OMB actual federal-account outlays as the controlling additive parent attribution;
- used USAspending File B only to partition an already-attributed federal-account amount across program activity × object class detail;
- required full-fiscal-year File B provenance (`period=12`) before using File B as a receipt partition;
- degraded safely to explicit detail-unavailable residual children when a READY full-year release or local Parquet objects are unavailable;
- enforced exact top-level and account-child cent conservation before publication;
- added synthetic File B regression coverage including 60/40 proportional allocation and partial-period rejection;
- added no-Docker API smoke coverage for the V2 receipt and its fixture-only fallback behavior.

The public methodology baseline at this stage included the 1.2.0 state/local rules. The machine-readable federal receipt version default was still stale at 1.1.0; 0.6.0 centralizes and corrects that version reporting.

## 0.2.0 — 2026-09-13

Completed TaxTrace phases 4–6:

- complete federal receipt allocation with exact tax-dollar conservation;
- explicit OASI, DI, Medicare HI, and general-financing pool rules;
- OMB function/subfunction parent classification and purpose receipt;
- audit provenance, confidence grades, and explicit residual nodes when detail is unavailable;
- additive drill-down explorer for purpose, agency, account, program activity, object class, and award views;
- exact federal-account crosswalks into USAspending program activities and award detail;
- award and recipient warehouse entities plus deterministic fixtures;
- portable search index over agencies, accounts, programs, object classes, awards, recipients, canonical categories, abbreviations, aliases, and curated synonyms;
- interactive Next.js receipt/explorer/search UI;
- no-Docker end-to-end CI that starts the API and website and exercises phases 4–6;
- deterministic largest-remainder cent reconciliation so source row ordering cannot move rounding cents;
- explicit `MIXED_FUNDING` handling for Medicare/general-revenue overlap and lower confidence where public spending data cannot separate dedicated financing cleanly;
- receipt-aware search that can return taxpayer-specific attributable amounts while preserving the non-additive search warning;
- source metadata propagated through explorer nodes for auditability.

Methodology version advanced to 1.1.0 because pool-to-spending eligibility rules are now operational rather than merely specified.

## 0.1.0 — 2026-09-13

Initial runnable implementation of TaxTrace phases 0–3:

- methodology v1.0.0;
- 2026 federal W-2 tax engine;
- Treasury/OMB/USAspending finance warehouse ingestion;
- source snapshotting and reconciliation;
- SQLite/PostgreSQL, Alembic, FastAPI, CLI, Next.js shell, Docker Compose, tests, and CI.
