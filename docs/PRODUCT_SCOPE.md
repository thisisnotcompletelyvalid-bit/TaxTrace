# TaxTrace product scope — phases 0–9A + Federal Product V2

Version: 0.6.5
Methodology version: 1.3.0

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
- Federal Search V2: direct full-year D1/D2/File F lake search for prime awards, recipients, subawards, and subrecipients with optional receipt-aware File C annotations.

## Tax concept

The federal 2026 engine supports W-2 wage income, four common filing statuses, standard deduction, ordinary brackets, employee Social Security/Medicare/Additional Medicare tax, supplied dependent counts, CTC/ODC phaseout, and the common ACTC earned-income formula.

Florida has no supported individual wage-income tax liability in this quick-mode scope. Florida state sales tax and Alachua discretionary surtax are MODELED, not calculated, because wage income alone does not reveal actual taxable purchases.

Property tax, fuel tax, utility taxes, communications taxes, fees, employer-side tax incidence, landlord property-tax incidence, corporate-tax incidence, tariff incidence, and general-equilibrium incidence are not inferred from quick-mode wages.

## Phase 9A statistical sales-tax model

Phase 9A uses 2024 BLS Consumer Expenditure Survey income-quintile expenditure levels. Wage income is an explicit proxy for BLS income before taxes. A versioned TaxTrace category-taxability matrix maps selected mutually exclusive expenditure components into modeled Florida-taxable consumption.

The model does **not** use `income × sales-tax rate`. Results are labeled MODELED and confidence C. The statewide rate is 6%. The current Alachua discretionary surtax rate is 1.5%.

Florida law applies the county surtax cap to the first $5,000 of many individual tangible-personal-property transactions. Quick mode cannot reconstruct transactions, so Phase 9A applies an explicitly labeled approximation only to the modeled annual vehicle-purchase component. This approximation is not represented as statutory calculation.

BLS flags estimates with high relative standard errors and cautions users about demographic estimates. Phase 9A therefore exposes its source year, selected quintile, taxability assumptions, and limitations. A later 9B/PUMD layer can replace the coarse quick-mode model with household-feature regression/microdata and manual-consumption overrides.

## Phase 7 Florida spending

The modeled 6% Florida sales-tax liability is attributed proportionally across the State of Florida FY2025 audited governmental-activity expenses from the Annual Comprehensive Financial Report Statement of Activities. This is ALLOCATED attribution, not literal tracing.

The additive state categories are:

- general government;
- education;
- human services;
- criminal justice and corrections;
- natural resources and environment;
- transportation;
- judicial branch;
- indirect interest on long-term debt.

Business-type activities are not mixed into this state governmental-activity partition.

## Phase 8 Alachua and Gainesville

The current 1.5% Alachua surtax is kept in dedicated legal-purpose pools rather than allocated across all county/city spending:

- 0.5 percentage point school capital outlay;
- 0.5 percentage point Wild Spaces & Public Places;
- 0.5 percentage point local-government infrastructure / Streets, Stations & Strong Foundations.

For the local-government/WSPP distribution layer, the model uses the official population-based allocation of 56.98% Alachua County, 35.45% Gainesville, and 7.57% other municipalities. Because the user's surtax amount itself is MODELED, these DIRECT purpose relationships carry confidence C in the personalized receipt.

Gainesville FY2025 audited governmental-activity expenditures are loaded as an ACTUAL reference view. They are deliberately **not** added to the user's tax receipt because quick-mode wages do not establish a personal property-tax, utility-tax, fee, or other city-revenue liability.

## Federal Product V2 receipt and explorer scope

The federal receipt uses calculated supported personal liabilities, effective tax-to-pool mappings, actual OMB account outlays, explicit financing-pool eligibility rules, and exact cent conservation.

OMB remains the controlling additive account attribution. Warehouse V2 then exposes deeper alternate views without replacing or adding to that parent:

- File B can partition an OMB-controlled account into program activity × object class using a proven full-year File B denominator;
- File C can receive personalized award-financial attribution only for the fraction of the account defensibly represented by full-year File C outlays relative to that File B denominator;
- repeated File C rows are collapsed to canonical award identity before personalized shares are assigned;
- unlinked File C rows remain explicit rather than being dropped;
- D1/D2 can enrich a collapsed prime-award identity with recipient and transaction context but create no additional personalized dollars;
- File F subawards are downstream, non-additive detail and create no additional personalized dollars.

If File C cannot be bounded conservatively by the File B account denominator, the product refuses award allocation and leaves the parent amount residual for that view.

Cross-view addition is prohibited because purpose, agency, account, File B, File C, D1/D2, and File F can describe the same underlying spending simultaneously.

The root federal page uses `/v2/receipt/federal` as its primary calculation API. The mature V1 purpose/agency explorer remains available over the nested conserved base receipt while Warehouse V2 account and award views complete their staged migration.

## State/local receipt scope

The Florida and Alachua receipt layers each enforce independent cent-level conservation. Gainesville's spending reference is non-additive to the quick-mode personalized receipt.

The national Census Warehouse V2 backbone is implemented, but a nationwide state/local personalized receipt is not yet represented as complete. The next major state/local product work is an official additive Census taxonomy followed by jurisdiction resolution and a national receipt bridge.

## Search scope

Federal Search V2 is the primary award-scale Warehouse V2 search path in 0.6.5. It searches normalized full-year D1/D2 and File F Parquet data directly with DuckDB rather than copying award-scale rows into the legacy relational search-document table.

D1/D2 are transaction grains, so prime-award search results are collapsed to canonical award identity before display. Recipient results group distinct prime-award identities by recipient name/UEI. File F subaward and subrecipient results remain downstream of the prime award. Prime awards, recipients, subawards, accounts, agencies, programs, and classifications can overlap, so all search results are non-additive.

Public-data search is exposed through `GET /v2/search/federal`. Receipt-aware search is exposed through `POST /v2/search/federal`. Receipt context can annotate a prime award or recipient only with personalized amounts already produced by the conserved File C award projection. File F never receives an independent personalized amount; a subaward may show its prime award's File C amount only as clearly labeled navigation context.

Only exact READY full-year award releases back annual Search V2 coverage. Missing release metadata or local Parquet objects produces an explicit incomplete-coverage state rather than fabricated results.

The dedicated web surface is `/search`. The original portable V1 search remains available for backward compatibility and legacy non-award entities during the broader Warehouse V2 migration.

See `docs/FEDERAL_SEARCH_V2.md` for the detailed search contract.

## Privacy posture

No account, SSN, name, tax document, or street address is required. Tax inputs are sent in POST bodies. Public-data Federal Search V2 requires no personal tax inputs. Receipt-aware search receives only the same supported tax inputs used by the federal receipt.

Production deployments should prevent request-body logging of income/household inputs. Future nationwide jurisdiction resolution should prefer the least precise location sufficient for the requested tax/jurisdiction calculation and should not require a street address unless a tax rule actually depends on one.
