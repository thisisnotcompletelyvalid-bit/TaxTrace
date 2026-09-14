# TaxTrace product scope — phases 0–9A

Version: 0.3.0
Methodology version: 1.2.0

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
- Phase 9A: quick-mode statistical sales-tax estimation using BLS Consumer Expenditure data and a transparent Florida taxability matrix.

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

## Receipt and explorer scope

The federal receipt continues to use calculated supported personal liabilities, effective tax-to-pool mappings, actual OMB account outlays, explicit financing-pool eligibility rules, and exact cent conservation.

Federal additive explorer views include purpose, agency, account, program activity, object class, and awards. Cross-view addition is prohibited because the same underlying spending can be classified simultaneously in more than one way.

The Florida and Alachua receipt layers each enforce independent cent-level conservation. Gainesville's spending reference is non-additive to the quick-mode personalized receipt.

## Search scope

The federal portable SQLite/PostgreSQL-compatible search index covers agencies, federal/Treasury accounts, program activities, object classes, budget functions/subfunctions, awards, recipients, canonical categories, agency abbreviations, automatic aliases, and curated synonyms. Search results can overlap and are never presented as an additive receipt.

## Privacy posture

No account, SSN, name, tax document, or street address is required. Tax inputs are sent in POST bodies. The Gainesville quick mode requires no address. Production deployments should prevent request-body logging of income/household inputs.
