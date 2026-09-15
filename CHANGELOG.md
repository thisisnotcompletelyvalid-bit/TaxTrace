# Changelog

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
