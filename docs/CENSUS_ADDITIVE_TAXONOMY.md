# Census additive expenditure taxonomy

Application: **0.7.0**  
Methodology: **1.4.0**  
Taxonomy revision: **1.2.0**

## Purpose

Warehouse V2 preserves Census government-finance source grain. Raw native item codes are not automatically additive because the public-use data contain multiple expenditure concepts, transfers, enterprise activity, special object codes, and historical code families.

Release 0.7.0 establishes the first official nationwide additive expenditure parent that subsequent state/local receipt work may use: **Direct General Expenditure**.

This document records the source-selection, membership, grouping, reconciliation, and refusal rules behind that parent.

## Controlling source family

The nationwide product uses the U.S. Census Bureau **State and Local Government Finances** classification/manual and revised public-use data. A similarly named summary methodology workbook under `programs-surveys/state` belongs to State Government Finances and is not interchangeable with the combined state-and-local methodology.

That distinction was discovered during live 2022 reconciliation. Treating the state-only workbook as the nationwide formula incorrectly removed fire protection and admitted state-only natural-resource code 54.

## Post-2022 additive parent

The supported post-2022 Direct General Expenditure parent contains a literal 72 native codes.

Current and capital expenditure families use `E` and consolidated `F` rows for these function suffixes:

```text
01 03 04 05 12 16 18 21 22 23 24 25 26 29 31 32 36
44 45 50 52 55 56 59 60 61 62 66 77 79 80 81 85 87 89
```

The parent additionally includes:

```text
I89  general-debt interest
J19  education subsidies
```

Important consequences:

- `E24` / `F24` fire protection are included.
- `E54` / `F54` are not members of the combined state/local parent.
- code 27 is outside the parent.
- utilities 91–94 and liquor-store activity 90 are outside the parent.
- obsolete G/K capital families are not additive beside consolidated F.
- transfers and discontinued welfare rows are not silently admitted.

Parent membership is literal and year-versioned. TaxTrace must not regenerate it from a prefix or suffix rule.

## Presentation taxonomy

Only after a native code is admitted to Direct General Expenditure is it assigned to a TaxTrace presentation category. Current categories include general government, education/libraries, welfare/human services, health, hospitals, police, fire, corrections, judicial/legal, protective regulation, transportation, natural resources/environment, parks/recreation, housing/community development, sewerage/solid waste, general-debt interest, and other/unallocable general expenditure.

The presentation taxonomy does not change the accounting parent. It only partitions the already-admitted parent.

For every supported fiscal year, the machine audit requires:

```text
every official parent code -> exactly one TaxTrace category
```

Missing or duplicate assignments invalidate the taxonomy.

## Government-level accounting rule

For one government `g`:

```text
DGE_g = sum(amount(g, code) for code in official_parent_codes)
```

The published TaxTrace partition must satisfy:

```text
sum(category children) + explicit residual = DGE_g
```

Excluded native expenditure codes remain reported as excluded detail. They do not enter the additive parent.

Duplicate source rows for the same government and native item code are first combined at native-code grain.

Raw Census rows outside an explicit additive partition remain non-additive.

## Unit rows versus Census aggregate controls

Census aggregate public-use totals are a distinct source grain. They need not be the literal arithmetic sum of every individual-government record because Census can apply aggregate-stage revisions or adjustments.

TaxTrace therefore uses:

- individual-government rows for government-level partitions;
- the bundled state-by-government-type public-use aggregation for aggregate validation;
- the current `GS00LOCALFIN` release as the published aggregate control.

An aggregate-stage difference is retained as reconciliation metadata. It is never distributed back to governments unless Census supplies an official government-level mapping.

## Live 2022 reconciliation

The release gate downloads the current revised 2022 individual-unit archive and current `GS00LOCALFIN` data and imports the production taxonomy constants directly.

Validated values:

```text
individual-government DGE sum     $4,081,976,281,000
22statetypepu national DGE         $4,082,022,589,000
GS00LOCALFIN national DGE          $4,082,022,589,000
aggregate public-use vs GS gap     $0
aggregate-stage adjustment         +$46,308,000
```

Component reconciliation:

```text
current expenditure
  unit rows                         $3,540,085,080,000
  aggregate/published               $3,540,126,596,000

capital expenditure
  unit rows                           $370,491,814,000
  aggregate/published                 $370,496,561,000

other (I89 + J19)
  unit rows                           $171,399,387,000
  aggregate/published                 $171,399,432,000
```

The component adjustments sum exactly to the $46.308 million parent adjustment.

The largest code-level aggregate adjustments observed in the current revised 2022 release are E89, E29, and F89. These are source reconciliation facts, not TaxTrace allocation weights.

## Validation gates

Release-quality changes to the Census taxonomy require both normal repository CI and the dedicated live Census validation workflow.

Normal CI checks:

- formula membership;
- taxonomy audit completeness/uniqueness;
- unsupported-year refusal;
- government-level exact conservation;
- excluded-code behavior;
- duplicate native-row combination;
- release/API behavior;
- the rest of TaxTrace Python, migration, web, and no-Docker E2E tests.

The live workflow checks current official source files and requires:

- production taxonomy audit is valid;
- the expected post-2022 membership invariants hold;
- aggregate public-use Direct General Expenditure equals current `GS00LOCALFIN` exactly;
- current, capital, and other components also reconcile exactly;
- aggregate adjustment equals the sum of component adjustments.

## Forward use

0.7.0 establishes spending classification, not jurisdiction determination or nationwide personal tax liability.

The next phase, 0.7.5, resolves which state/local governments apply to a user and creates a defensible jurisdiction graph. Only after that graph is stable should 0.8.0 connect supported state/local tax liabilities to the Census additive spending parent.
