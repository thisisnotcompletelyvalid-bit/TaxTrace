# TaxTrace methodology specification

Methodology version: **1.3.0**
Status: governing specification for implemented phases 0–9A and Federal Product V2

## 1. Headline definition

> **A user's estimated contribution** represents the amount of the user's estimated personal tax liability attributed to a government activity. Where a tax is legally or accounting-wise dedicated to a financing pool, attribution is restricted to expenditures associated with that pool. Where revenue is fungible, the user's contribution is distributed proportionally according to eligible government expenditures. This is an attribution model, not a claim that an individual taxpayer's literal dollars can be traced through the Treasury to a particular expenditure.

That definition is the core semantic contract of the project.

## 2. Controlled terminology

### CALCULATED
An amount derived deterministically from user-supplied facts and codified tax law within the supported scope.

### MODELED
An amount inferred statistically because the user's actual taxable base is not known. Sales-tax estimates are the primary implemented example.

### DIRECT
A revenue-to-pool relationship that is legally or accounting-wise restricted. "Direct" does not mean a serial-numbered dollar is followed through bank accounts; it means the allocation domain is restricted by the financing structure.

### ALLOCATED
A fungible revenue contribution attributed proportionally across an eligible expenditure base.

### TRACED
A transfer is followed across funds or governments to a later use without creating an additional dollar.

### ACTUAL
A completed-period expenditure, outlay, receipt, or other realized financial quantity.

### ENACTED
A legally adopted current-period budget quantity that is not yet a completed actual.

### PROPOSED
A proposal or estimate that has not become a completed actual. OMB budget-year estimates must remain visibly distinct from historical actuals.

### OUTLAY
Federal cash disbursement. For the federal warehouse this is the preferred completed-period expenditure metric when available.

### OBLIGATION
A legal commitment that will or may require payment. Obligations are not silently substituted for outlays.

### APPROPRIATION / BUDGET AUTHORITY
Authority to incur obligations, not the same as an outlay.

### MIXED-FUNDING
A program or expenditure whose funding sources cannot be separated sufficiently to make a source-specific attribution without modeling.

## 3. Atomic fiscal objects

TaxTrace distinguishes the following objects rather than treating "the budget" as one table:

- **Tax/revenue type** — e.g. federal individual income tax, employee Social Security tax.
- **Financing source** — current revenue, borrowing, and other financing are conceptually separate.
- **Funding pool/fund** — a legally/accountingly meaningful pool from which expenditures may be financed.
- **Transfer** — movement between funds or governments; it is not automatically a final expenditure.
- **Expenditure/outlay** — final spending recorded according to the relevant accounting system.
- **Classification** — function, organization, account, program activity, object class, award, recipient, etc. Multiple classifications may describe the same underlying spending and therefore are not automatically additive.

## 4. User tax liability

For revenue type `r`, let:

`T_r = the user's calculated or modeled personal tax liability for revenue type r`.

The default project concept is statutory/personal liability, not full economic incidence. Refundable credits are reported separately and do not create negative tax dollars available for allocation.

Withholding is cash prepayment, not liability. A future import of withholding information must not treat withholding as tax paid unless explicitly discussing cash flow.

## 5. Revenue-to-pool mapping

Let `alpha(r,p)` be the fraction of revenue type `r` assigned to funding pool `p`.

For a completely mapped revenue type:

`sum_p alpha(r,p) = 1`.

The user's contribution to pool `p` is:

`C_p = sum_r T_r * alpha(r,p)`.

Every mapping has effective dates and an authority/source explanation. A mapping is invalid if its active shares do not sum to one within the configured numerical tolerance.

The initial federal mappings are:

- federal individual income tax -> federal general financing pool;
- employee OASDI tax -> OASI and DI according to the statutory/current-law split represented in the seed data;
- employee Medicare tax -> Medicare Hospital Insurance financing pool;
- Additional Medicare Tax -> Medicare Hospital Insurance financing pool.

These mappings are methodological inputs. Phase 4 applies them through explicit pool-to-spending eligibility rules; later phases may refine the public-data grain without changing the underlying tax-to-pool relationship.

## 6. General-revenue allocation

When pool revenue is fungible, the implemented Phase 4 engine calculates an attribution weight for eligible activity `j`:

`W(p,j) = E(p,j) / sum_k E(p,k)`

and user attribution:

`A_j = sum_p C_p * W(p,j)`.

A complete additive partition must satisfy:

`sum_j A_j = sum_p C_p`.

The receipt engine enforces this invariant for every pool and for the complete purpose receipt. Cent rounding is reconciled so displayed children equal the displayed parent.

## 7. Deficits and borrowing

Borrowing does **not** enlarge the user's tax receipt. If a user has $8,000 of allocable personal tax liability, the primary receipt allocates $8,000 even if government outlays exceed current receipts.

Borrowing is a financing source and should eventually be presented as fiscal context. Current interest/debt-service outlays can be expenditures to which current general revenue is attributed, but debt issuance itself is not treated as a program expenditure.

## 8. Transfers and double counting

A dollar transferred Federal -> State -> Municipality remains one dollar. TaxTrace may display its path in an end-use view, but a complete additive view cannot count the transfer and the final expenditure as two dollars.

The same rule applies to intragovernmental/interfund transfers. The project must choose the appropriate stage for a given view and conserve the underlying amount.

## 9. Enterprise funds and fees

A charge for a government enterprise service is not automatically a tax. Utilities, parking charges, fares, solid-waste fees, and similar revenues are kept distinct from personal taxes. A tax-financed transfer into an enterprise fund can later be traced to its use without reclassifying customer fees as taxes.

## 10. Expenditure metric precedence

For the primary completed-period receipt, preferred evidence is:

1. actual outlay/expenditure;
2. enacted/current budget if an actual is unavailable and the UI explicitly says so;
3. proposed/estimated budget only in a clearly separated proposed view.

Obligations may be explored as obligations but are not silently substituted for actual outlays.

For OMB's FY2027 Public Budget Database, the source guide states that 2025 and earlier are actual and 2026–2031 are estimates. The parser encodes this rule rather than treating all workbook years identically.

## 11. Fiscal-year versus tax-year alignment

A user's tax year and the latest completed spending fiscal year may differ. Every receipt must carry both. The system must never manufacture a completed spending year simply to match the user's tax year.

## 12. Classification dimensions and non-additivity

Federal spending may simultaneously be classified by:

- budget function/subfunction;
- agency/subagency;
- federal account/Treasury account;
- program activity;
- object class;
- award and recipient;
- subaward and subrecipient.

These describe overlapping views of spending. TaxTrace stores them as distinct warehouse scopes. Amounts from different scopes cannot be summed unless a specific mapping proves they form a mutually exclusive partition.

The same principle applies to state and local dimensions such as fund, department, function, object, vendor, project, and native finance item code.

## 13. Source hierarchy and provenance

Preferred evidence order:

1. official audited/administrative financial records;
2. official government financial databases;
3. official budget/financial reports;
4. standardized official statistical sources;
5. secondary sources for interpretation only unless no primary data exist and the limitation is explicit.

Every imported external object is backed by immutable source or release metadata containing enough information to identify the source, reference period, retrieval or ingestion event, parser/materializer, and stored bytes or object identity.

A revision creates a new source snapshot or dataset release; it does not silently mutate the evidentiary basis of an old calculation.

## 14. Federal source roles

### U.S. Treasury
Used for authoritative federal aggregate receipt/outlay control information.

### OMB Public Budget Database
Used for the controlling federal account and function actual-outlay base for the personalized federal receipt. OMB remains the additive parent when deeper USAspending dimensions are displayed.

### USAspending / DATA Act files
Used for deeper federal account, program-activity, object-class, award, recipient, transaction, subaward, and subrecipient detail. File A, File B, File C, D1, D2, and File F preserve their native grains and are not six additive piles of spending.

## 15. Reconciliation

Source systems differ in scope, timing, revisions, gross/net treatment, and classification. Differences are not deleted or hidden.

The repository's initial reconciliation policy is:

- absolute relative difference <= 0.1%: `PASS`;
- >0.1% and <=1%: `REVIEW`;
- >1%: `FAIL`.

These thresholds are operational defaults, not a claim that all source pairs ought to match exactly. Every reconciliation result stores both values, absolute difference, relative difference, status, and metadata.

A failed or ambiguous reconciliation should block publication of a dependent public number until reviewed. Some V2 detail relationships use stricter semantic gates rather than the generic percentage thresholds; those rules are specified below.

## 16. Monetary precision and rounding

Warehouse monetary values are stored as fixed-precision decimals in dollars. Float arithmetic is not used for tax liability or allocation mathematics.

Calculations retain precision internally. Additive receipt/explorer views use a deterministic largest-remainder cent-reconciliation method so displayed children sum exactly to their displayed parent and source-row ordering cannot move a rounding cent between categories.

## 17. Confidence versus uncertainty

A methodological confidence grade is not a statistical confidence interval.

Current confidence semantics are:

- **A** — statutory calculation plus high-quality actual expenditure and direct financing relationship;
- **B** — statutory calculation plus high-quality actual expenditure and proportional general-pool attribution;
- **C** — one important modeled component;
- **D** — multiple material modeling assumptions or incomplete funding separation;
- **N/A** — insufficient data.

When a statistical model can estimate prediction uncertainty, that interval should be reported separately.

## 18. Refusal rule

Specificity ends where evidence ends. If the available source cannot support a child allocation safely, TaxTrace returns an explicit residual, unavailable status, or non-additive reference instead of inventing a precise line item.

## 19. Machine-enforced invariants

Implemented invariants include:

- active revenue-to-pool shares sum to 1;
- money is represented with decimals;
- source bytes or lake objects retain immutable provenance/content identity;
- actual/proposed status is attached to imported records where applicable;
- overlapping dimensions retain distinct grains/scopes;
- reconciliation differences are retained explicitly;
- tax-to-pool, pool-to-child, top-level receipt, account-detail, jurisdictional, and explorer-scope conservation are enforced where a view is additive;
- tax rules are versioned by tax year rather than embedded as timeless constants;
- partial-period federal bulk releases cannot silently stand in for full-year personalized allocation;
- cross-grain award relationships require canonical identity collapse before enrichment;
- File F subawards cannot be added beside their prime awards as additional federal spending.

## 20. Methodology change policy

A change that alters the semantic meaning or numerical result of a published receipt requires a methodology-version change and a changelog/documentation entry. Historical calculations must retain enough version metadata to remain reproducible.

The authoritative version used by newly produced machine-readable receipts is centralized in `taxtrace.methodology.version.METHODOLOGY_VERSION`.

## 21. Operational pool-to-spending eligibility (methodology 1.1.0)

Phase 4 makes the funding-pool restriction operational through effective-dated `PoolSpendRule` rows. The current federal rules use OMB actual account outlays as the primary receipt base.

- `FED_GENERAL` allocates across OMB actual account outlays after excluding the Social Security 650/651 base. Medicare remains in the general allocation domain because Medicare is materially mixed-funded. General-pool attribution is `ALLOCATED` and receives confidence B.
- `OASI` and `DI` restrict attribution to the Social Security 650/651 spending base. Their revenue relationship is `DIRECT`, but the current public spending grain does not separate final OASI and DI uses, so these allocations receive confidence D for incomplete source separation.
- `MEDICARE_HI` restricts attribution to the Medicare 570/571 spending base. Its revenue relationship is `DIRECT`, but that broad Medicare spending base also contains spending financed from other sources, so the current allocation receives confidence D for incomplete source separation.
- When a displayed purpose receives attribution from more than one financing pool, TaxTrace labels the combined purpose `MIXED_FUNDING`. This prevents the UI from implying that a mixed-financed program has one exclusive revenue source.

If an active pool has no matching actual expenditure facts, TaxTrace does not widen the pool automatically. The contribution is retained as `UNALLOCATED_DETAIL` with confidence N/A. This preserves the tax-dollar conservation invariant while obeying the refusal rule.

## 22. Drill-down explorer methodology

The original Phase 5 explorer begins with the exact Phase 4 fact allocations and changes only how those facts are grouped or, for deeper dimensions, how a defensible parent scope is subdivided.

OMB purpose, agency, and federal-account views are regroupings of the same allocated OMB account facts. When deeper data cover only part of a selected parent scope, the uncovered share must be returned as a residual node.

Therefore every additive explorer response must satisfy:

`sum(view nodes including residual) = selected parent scope amount`.

Explorer views are not additive across dimensions. Adding an agency view to a purpose view, or a File B view to a File C view, would double count the same underlying receipt.

## 23. Award/recipient semantics

Awards are a detail classification, not an additional expenditure layer. Reported award, transaction, and subaward amounts can describe or subdivide a defensible parent scope, but they are never added on top of the controlling OMB account attribution.

Award and recipient searches may overlap each other, accounts, agencies, programs, and classifications. Search overlap never authorizes addition.

## 24. Search methodology

Phase 6 maintains a separate portable search index over normalized finance entities. Search ranking uses canonical titles, descriptions, identifiers, aliases, abbreviations, curated synonyms, and approximate string similarity. The current portable implementation is designed to run on SQLite and PostgreSQL; a later Warehouse V2 search layer may replace ranking without changing the non-additive search contract.

Search results are discovery/navigation results, not an additive partition. They are explicitly marked non-additive because the same spending can match multiple entities or concepts.

Manual/curated aliases are stored separately from official names so TaxTrace never rewrites government-native source labels.

## 25. Florida, Alachua, Gainesville, and modeled sales tax (methodology 1.2.0)

Methodology 1.2.0 added the implemented state/local quick-mode rules in Phases 7, 8, and 9A.

- Florida quick mode does not invent an individual wage-income tax where none is supported.
- Because wages do not reveal actual taxable purchases, the quick-mode Florida and Alachua sales-tax liabilities are `MODELED`, not `CALCULATED`.
- The model uses versioned BLS Consumer Expenditure Survey expenditure information and a TaxTrace taxability matrix rather than multiplying wages directly by a sales-tax rate.
- Florida state sales tax is allocated across a mutually exclusive audited governmental-activity expenditure partition.
- Alachua discretionary surtax remains in its dedicated legal-purpose pools rather than being blended into all county/city spending.
- Florida and Alachua additive partitions conserve independently at displayed-cent precision.
- Gainesville audited spending can be shown as an `ACTUAL` reference but is non-additive to the quick-mode personalized receipt unless a personal city tax or fee liability has been established.

The detailed source and modeling assumptions remain documented in `docs/PHASE_7_8_9A.md`.

## 26. Warehouse V2 federal account detail (methodology 1.3.0)

Methodology 1.3.0 makes Warehouse V2 the operational deep-detail path for the personalized federal product while retaining OMB actual account outlays as the controlling additive parent.

### 26.1 File B program-activity × object-class partition

For a federal account with personalized OMB-controlled attribution `A_account`, TaxTrace may use full-year USAspending File B rows to partition that already-attributed amount into program-activity × object-class children.

Let `B_i` be the signed File B FY-beginning-to-period-end outlay for child `i`, and let:

`B_account = sum_i B_i`.

When a safe full-year File B release is available and the denominator is usable, the raw child attribution is:

`A_i = A_account * B_i / B_account`.

Displayed children are deterministically cent-reconciled back to `A_account`.

OMB and File B government outlay totals are displayed independently. They are never added together. A difference between them does not cause TaxTrace to replace the OMB parent silently.

For the current USAspending account-download path, a release is treated as full-year for personalization only when stored request provenance proves reporting period `12`. Missing local Parquet objects, unknown/partial periods, zero denominators, or unsupported schemas produce explicit detail-unavailable residuals rather than guessed children.

### 26.2 File C award-financial projection

File C is **not** assumed to describe 100% of an OMB account. It is award-financial activity, so normalizing File C identities directly to the full personalized account would falsely classify non-award or uncovered account activity as awards.

TaxTrace therefore uses the matching full-year File B account outlay as the USAspending denominator and File C outlay as the award-financial numerator.

Let:

- `A_account` = personalized OMB-controlled account attribution;
- `B_account` = full-year File B account outlay;
- `C_account` = sum of eligible full-year File C award-financial outlays for the account.

The File C award-share gate is:

`R_award = C_account / B_account`.

The current conservative projection requires:

`B_account > 0`

and

`0 <= C_account <= B_account`.

If those bounds are not satisfied, TaxTrace assigns **no** personalized dollars to File C awards for that account and leaves the complete parent as an explicit residual.

When the bounds are satisfied:

`A_award_pool = A_account * R_award`

and

`A_residual = A_account - A_award_pool`.

File C rows are first collapsed to the canonical USAspending generated award identity. Repeated File C rows for the same award identity therefore contribute to one identity-level outlay before the personalized award pool is subdivided. Blank/unlinked File C activity is preserved in an explicit unlinked bucket rather than dropped or guessed.

Identity child shares use the collapsed File C outlays within `C_account`, followed by deterministic cent reconciliation. The identity children plus the non-award/unreconciled residual must equal `A_account` exactly.

### 26.3 D1/D2 prime transactions and File F subawards

The canonical identity aliases are:

```text
File C: award_unique_key
D1:     contract_award_unique_key
D2:     assistance_award_unique_key
File F: prime_award_unique_key
```

These identify relationships; they do not authorize a raw row-to-row join. File C and D1/D2 can each contain repeated rows for the same identity, so a naive join can create many-to-many fan-out and multiply monetary values.

TaxTrace therefore collapses File C to the intended prime-award identity first, then queries D1/D2 independently by that identity for descriptive prime-award and recipient attributes. D1/D2 transaction counts, obligations, award totals, and other monetary fields do not create additional personalized dollars.

File F is downstream of the prime award. Subaward amounts describe distribution within a prime award and are always non-additive to the personalized receipt. They have no independent personalized amount and must never be added beside the prime award as another federal expenditure.

Federal Product V2 uses only a READY full-fiscal-year D1/D2/File F release for this full-year drilldown. Bounded validation slices remain valid source-validation evidence but do not masquerade as annual product coverage.

### 26.4 Conservation across V2 views

The following remain separate accounting views of the same underlying federal receipt:

- OMB purpose/agency/account;
- File B program activity × object class;
- File C award-financial projection;
- D1/D2 prime-award transaction attributes;
- File F subaward/subrecipient detail.

Only explicitly marked children within one additive partition may be summed. Cross-view addition is prohibited.

The top-level Federal Receipt V2 must still satisfy:

`sum(OMB-controlled account attributions) + explicit top-level residual = total allocable personal federal taxes`.

Every File B account partition and every File C account award projection must independently conserve its personalized parent at displayed-cent precision.
