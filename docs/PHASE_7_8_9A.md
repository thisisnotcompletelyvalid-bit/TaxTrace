# Phases 7, 8 and 9A — Florida + Gainesville

Methodology version: 1.2.0

## Phase 7 — Florida

Quick mode does not invent a Florida individual income-tax liability. It adds only the tax types supported by the supplied inputs.

The Phase 9A model estimates Florida general sales tax, then Phase 7 attributes that modeled liability proportionally across FY2025 audited State of Florida governmental-activity expenses. The spending denominator comes from the State of Florida FY2025 Annual Comprehensive Financial Report, Statement of Activities:

https://flauditor.gov/pages/pdf_files/2025%20annual%20comprehensive%20financial%20report.pdf

Florida Department of Revenue states that the general state sales tax rate is 6%:

https://floridarevenue.com/taxes/taxesfees/Pages/tax_interest_rates.aspx

The state allocation is labeled ALLOCATED and confidence C because the expenditure data are official actuals but the user's sales-tax liability is modeled.

## Phase 8 — Alachua County + Gainesville

Florida Department of Revenue's current rate table lists Alachua County's discretionary sales surtax at 1.5%:

https://pointmatch.floridarevenue.com/General/DiscretionarySalesSurtaxRates.aspx

The current surtax is kept in separate half-cent legal-purpose pools instead of being blended into general local spending:

- 0.5 percentage point school capital outlay;
- 0.5 percentage point Wild Spaces & Public Places;
- 0.5 percentage point local-government infrastructure.

The City of Gainesville documents the current 2023–2032 Wild Spaces & Public Places half-cent surtax and the population-based distribution: 56.98% Alachua County, 35.45% Gainesville and 7.57% the other municipalities:

https://www.gainesvillefl.gov/Government-Pages/Government/Departments/Wild-Spaces-Public-Places

Gainesville's adopted financial plan describes the infrastructure half, branded Streets, Stations and Strong Foundations, and the 10% affordable-housing set-aside within the public-infrastructure portion:

https://www.gainesvillefl.gov/files/assets/public/v/2/budget-amp-finance/documents/fy25-adopted-fop-final.pdf

Gainesville FY2025 governmental-activity expenses are loaded from the audited city ACFR as an ACTUAL reference view:

https://flauditor.gov/pages/mun_efile%20rpts/2025%20gainesville.pdf

Quick mode does not allocate those city expenses to the user because wage income does not establish the user's property tax, utility taxes, fees or other city liabilities.

## Phase 9A — modeled sales tax

Phase 9A uses the U.S. Bureau of Labor Statistics 2024 Consumer Expenditure Survey income-quintile expenditure levels:

https://www.bls.gov/news.release/cesan.htm

The 2024 lower income bounds are $29,932, $57,452, $94,511 and $155,925. Average annual expenditures by quintile are $35,046, $50,054, $66,900, $89,972 and $150,342.

Quick mode uses supported wage income as a proxy for BLS income before taxes. It scales a versioned set of expenditure components and applies a TaxTrace category-taxability matrix. Category taxability shares are model assumptions, not BLS estimates or Florida Department of Revenue rulings.

The model does not calculate sales tax as `income × rate`.

Florida Department of Revenue explains that discretionary surtax generally applies only to the first $5,000 of a taxable tangible-personal-property item and that this is a transaction-level rule:

https://floridarevenue.com/taxes/taxesfees/Pages/discretionary.aspx

Because quick mode has no transaction history, Phase 9A approximates that cap only for the modeled annual vehicle-purchase component and discloses the approximation. A later microdata/manual-consumption phase should replace this shortcut.

BLS now flags mean estimates whose relative standard errors are at least 25% and cautions users about those estimates. TaxTrace therefore reports Phase 9A as MODELED, confidence C, with source year and assumptions visible.

## Conservation

The federal, Florida and Alachua additive partitions reconcile independently to the corresponding tax amount at displayed-cent precision. Gainesville's city spending reference is intentionally non-additive to the personalized quick-mode receipt.
