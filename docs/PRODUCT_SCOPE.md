# TaxTrace product scope — phases 0–6

Version: 0.2.0
Methodology version: 1.1.0

## Purpose

TaxTrace answers: **given a supported personal federal tax liability, what government activities can those dollars defensibly be attributed to using public finance data?**

Implemented scope:

- Phase 0: engineering/data foundation;
- Phase 1: methodology/invariants;
- Phase 2: federal W-2 personal tax engine;
- Phase 3: federal finance warehouse;
- Phase 4: complete auditable federal receipt;
- Phase 5: drill-down explorer;
- Phase 6: indexed search.

## Supported taxpayer scope

The 2026 federal engine supports W-2 wage income, four common filing statuses, standard deduction, ordinary brackets, employee Social Security/Medicare/Additional Medicare tax, supplied dependent counts, CTC/ODC phaseout, and the common ACTC earned-income formula.

It is not tax-return preparation. Itemization, self-employment, investment/capital-gain tax, EITC, AMT, NIIT, ACA credits, retirement/foreign income, and many other provisions remain outside the supported scope.

## Receipt scope

The primary receipt uses:

- calculated supported personal liabilities;
- effective tax-to-pool mappings;
- actual OMB account outlays for the selected completed fiscal year;
- explicit financing-pool eligibility rules;
- exact conservation after display rounding.

Fungible general revenue is proportionally attributed, not literally traced. Dedicated revenue is first restricted to the relevant financing pool. Missing public detail becomes an explicit residual/unallocated node.

## Explorer scope

Additive views currently include purpose, agency, account, program activity, object class, and awards. The latter USAspending dimensions are crosswalked into the OMB receipt scope and contain residuals when coverage is incomplete.

Cross-view addition is prohibited because the same underlying spending can be classified simultaneously in more than one way.

## Search scope

The portable SQLite/PostgreSQL-compatible search index covers agencies, federal/Treasury accounts, program activities, object classes, budget functions/subfunctions, awards, recipients, canonical categories, agency abbreviations, automatic aliases, and curated synonyms.

Search results can overlap and are never presented as an additive receipt.

## Explicitly excluded from the default tax concept

- employer-side payroll taxes;
- corporate-tax incidence;
- tariff incidence;
- landlord property-tax incidence;
- general-equilibrium incidence assumptions;
- benefits received;
- fees treated as taxes.

## Privacy posture

No account, SSN, name, tax document, or street address is required. Tax inputs are sent in POST bodies. Production deployments should prevent request-body logging of income/household inputs.
