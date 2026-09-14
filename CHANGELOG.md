# Changelog

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

Methodology remains **1.2.0**. File B government outlays are never added to OMB outlays, and File B children are additive only within the account-detail partition in which they are shown.

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
- no-Docker end-to-end CI that starts the API and website and exercises phases 4–6.
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
