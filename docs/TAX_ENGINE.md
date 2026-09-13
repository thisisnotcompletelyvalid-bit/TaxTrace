# Federal tax engine

## Scope

The initial engine answers a narrow question reliably: under supported 2026 rules, what is a taxpayer's federal personal income-tax liability and employee payroll-tax liability given W-2 wages, filing status, and supplied dependent counts?

The rule data live in `src/taxtrace/data/tax_rules/federal/<year>.json` (with an auditable mirror at `data/tax_rules/federal/`). `RuleRepository` refuses unsupported years instead of silently reusing the nearest year.

## Calculation order

1. Add primary and, for MFJ, spouse W-2 wages.
2. Apply the filing-status standard deduction.
3. Calculate ordinary income tax using the year/status progressive bracket table.
4. Calculate potential CTC + ODC from supplied eligible-dependent counts.
5. Apply the MAGI phaseout rule.
6. Use available nonrefundable dependent credit against income tax.
7. Calculate the common ACTC earned-income formula and expose it separately from taxes paid.
8. Calculate employee Social Security tax independently for each spouse because the wage base applies per worker.
9. Calculate employee Medicare tax on wages.
10. Calculate Additional Medicare Tax using the filing-status threshold.
11. Return personal tax liability as income-tax liability + employee payroll taxes. Refundable credits remain separate.

## Precision

All calculation inputs are converted to `Decimal`; monetary results are quantized to cents. No binary floating-point tax arithmetic is used.

## Known boundaries

The engine does not determine whether a person qualifies as a dependent/qualifying child. The caller supplies already-qualified counts. It also does not implement the Schedule 8812 alternative ACTC method that may affect taxpayers with three or more qualifying children; such cases receive a limitation message.

## Testing

Tests cover:

- a known $50,000 single-filer calculation;
- Social Security wage-base boundaries;
- separate spouse wage bases for MFJ;
- Additional Medicare Tax threshold behavior;
- CTC/ACTC behavior;
- credit phaseout;
- ODC;
- unsupported year behavior;
- invalid spouse wage input;
- progressive-bracket edge points.
