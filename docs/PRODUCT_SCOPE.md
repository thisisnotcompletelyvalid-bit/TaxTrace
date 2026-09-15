# TaxTrace product scope — phases 0–9A + Warehouse V2

Version: 0.7.0
Methodology version: 1.4.0
Census taxonomy revision: 1.2.0

## Purpose

TaxTrace answers: **given a supported personal tax liability, what government activities can those dollars defensibly be attributed to using public finance data?**

Implemented scope:

- Phase 0: engineering/data foundation;
- Phase 1: methodology/invariants;
- Phase 2: federal W-2 personal tax engine;
- Phase 3: federal finance warehouse;
- Phase 4: complete auditable federal receipt;
- Phase 5: drill-down explorer;
- Phase 6: indexed search;
- Phase 7: Florida state sales-tax attribution to audited state governmental-activity expenditures;
- Phase 8: Alachua/Gainesville dedicated surtax routing plus Gainesville actual-spending reference;
- Phase 9A: quick-mode statistical sales-tax estimation using BLS Consumer Expenditure data and a transparent Florida taxability matrix;
- Warehouse V2: national Census state/local backbone plus USAspending File A/B/C/D1/D2/F lake ingestion and coverage metadata;
- Federal Product V2: OMB-controlled personalized federal accounts with File B program/object detail, conservative File C award projection, D1/D2 prime-recipient enrichment, and non-additive File F subaward drilldown;
- Federal Search V2: direct full-year D1/D2/File F lake search for prime awards, recipients, subawards, and subrecipients with optional receipt-aware File C annotations;
- Census Additive Taxonomy: year-versioned combined state/local Direct General Expenditure parent, exact government-level conservation, and current-vintage aggregate reconciliation.

## Tax concept

The federal 2026 engine supports W-2 wage income, four common filing statuses, standard deduction, ordinary brackets, employee Social Security/Medicare/Additional Medicare tax, supplied dependent counts, CTC/ODC phaseout, and the common ACTC earned-income formula.

Florida has no supported individual wage-income tax liability in quick mode. Florida state sales tax and Alachua discretionary surtax are MODELED, not calculated, because wage income alone does not reveal actual taxable purchases.

Property tax, fuel tax, utility taxes, communications taxes, fees, employer-side tax incidence, landlord property-tax incidence, corporate-tax incidence, tariff incidence, and general-equilibrium incidence are not inferred from quick-mode wages.

## Federal Product V2

The federal receipt uses calculated supported personal liabilities, effective tax-to-pool mappings, actual OMB account outlays, explicit financing-pool eligibility rules, and exact cent conservation.

OMB remains the controlling additive account attribution. Warehouse V2 exposes deeper alternate views without replacing or adding to that parent:

- File B can partition an OMB-controlled account into program activity × object class using a proven full-year File B denominator;
- File C can receive personalized award-financial attribution only for the fraction of the account defensibly represented by full-year File C outlays relative to that File B denominator;
- repeated File C rows collapse to canonical award identity before personalized shares are assigned;
- unlinked File C rows remain explicit;
- D1/D2 enrich a collapsed prime-award identity with recipient and transaction context but create no additional personalized dollars;
- File F subawards are downstream, non-additive detail and create no additional personalized dollars.

Cross-view addition is prohibited because purpose, agency, account, File B, File C, D1/D2, and File F can describe the same underlying spending simultaneously.

## Federal Search V2

Federal Search V2 searches normalized full-year D1/D2 and File F Parquet data directly with DuckDB. Prime-award results collapse repeated transaction rows to canonical identity. Recipient results group distinct prime identities. File F subaward/subrecipient results remain downstream and non-additive.

Receipt-aware search may annotate prime awards and recipients only with personalized amounts already produced by the conserved File C award projection. File F never receives an independent personalized amount.

## Census state/local spending scope

Release 0.7.0 completes the first official nationwide additive spending taxonomy over Warehouse V2.

The controlling parent is Census **Direct General Expenditure** for the supported post-2022 code system. The combined State and Local Government Finances formula is encoded as a literal 72-code set. TaxTrace does not infer parent membership from native-code shape.

The presentation layer partitions only codes already admitted to that parent. Every admitted code must map to exactly one TaxTrace presentation category. Government-level children plus residual must equal the government-level parent exactly.

Census aggregate controls remain a separate source grain. The current revised 2022 validation proves the national aggregate public-use control and current `GS00LOCALFIN` both equal `$4,082,022,589,000`, while the literal individual-government sum is `$4,081,976,281,000`. The resulting `$46,308,000` aggregate-stage adjustment is retained as reconciliation metadata and is not redistributed to governments.

See `docs/CENSUS_ADDITIVE_TAXONOMY.md`.

## State/local receipt scope

The Florida and Alachua quick-mode receipt layers each enforce independent cent-level conservation. Gainesville's spending reference is non-additive to the quick-mode personalized receipt.

The national Census spending taxonomy is now implemented, but nationwide jurisdiction resolution and nationwide personal state/local tax liability are not yet complete. 0.7.5 is dedicated to determining the correct applicable governments and constructing a non-duplicative jurisdiction graph. 0.8.0 will use that graph to bridge supported state/local tax liabilities into the Census additive spending parent.

## Privacy posture

No account, SSN, name, tax document, or street address is required for the current federal product. Tax inputs are sent in POST bodies. Public-data Federal Search V2 requires no personal tax inputs.

Jurisdiction resolution should use the least precise location sufficient for the tax/jurisdiction decision. A street address should not become a product requirement unless a government boundary or tax rule truly depends on it.
