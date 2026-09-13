# TaxTrace product scope — phases 0–3

Version: 0.1.0  
Methodology version: 1.0.0

## Purpose

TaxTrace is intended to become an auditable answer to: **given a person's location and personal tax liability, what government activities can those tax dollars defensibly be attributed to?**

This repository implements only the foundation required before that receipt can be built:

- Phase 0: engineering/data foundation;
- Phase 1: operational methodology and invariants;
- Phase 2: versioned federal W-2 tax-liability engine;
- Phase 3: federal finance warehouse ingestion, immutable source snapshots, normalized dimensions, and reconciliation infrastructure.

Phase 4 (allocating a user's liabilities to spending and presenting the complete receipt) is deliberately not implemented.

## Supported taxpayer scope

The 2026 federal engine supports:

- W-2 wage income;
- Single, Married Filing Jointly, Married Filing Separately, and Head of Household;
- standard deduction;
- ordinary federal income-tax brackets;
- employee Social Security tax, including a per-worker wage base;
- employee Medicare tax;
- Additional Medicare Tax;
- supplied counts of qualifying children under 17 and other dependents;
- CTC/ODC phaseout;
- the common ACTC earned-income formula.

It is a **liability calculator, not a tax-return-preparation product**. It does not yet model itemized deductions, self-employment, capital gains, investment income, above-the-line adjustments, education credits, EITC, ACA credits, AMT, NIIT, foreign income, retirement income, or the alternative ACTC calculation that can matter for families with three or more qualifying children.

## Explicitly excluded from the default tax concept

- employer-side payroll taxes;
- corporate-tax incidence;
- tariff incidence;
- property taxes passed through rent;
- general-equilibrium incidence assumptions;
- benefits received from government;
- user fees as though they were taxes.

Those may eventually exist as clearly separated advanced modes.

## Privacy posture

No account, SSN, name, tax document, or street address is required by phases 0–3. The API accepts tax inputs in a POST body. Production deployments should configure request logging so tax inputs are not retained in logs.
