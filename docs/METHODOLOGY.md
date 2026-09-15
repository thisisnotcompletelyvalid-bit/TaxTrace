# TaxTrace methodology specification

Methodology version: **1.3.0**  
Status: governing specification for implemented phases 0–9A, Federal Product V2, and Federal Search V2

## 1. Headline definition

> **A user's estimated contribution** represents the amount of the user's estimated personal tax liability attributed to a government activity. Where a tax is legally or accounting-wise dedicated to a financing pool, attribution is restricted to expenditures associated with that pool. Where revenue is fungible, the user's contribution is distributed proportionally according to eligible government expenditures. This is an attribution model, not a claim that an individual taxpayer's literal dollars can be traced through the Treasury to a particular expenditure.

That definition is the core semantic contract of TaxTrace.

## 2. Controlled terminology

### CALCULATED
An amount derived deterministically from user-supplied facts and codified tax law within the supported scope.

### MODELED
An amount inferred statistically because the user's actual taxable base is unknown. Sales-tax estimates are the primary implemented example.

### DIRECT
A revenue-to-pool relationship that is legally or accounting-wise restricted. `DIRECT` does not mean a serial-numbered dollar is followed through bank accounts; it means the allocation domain is restricted by the financing structure.

### ALLOCATED
A fungible revenue contribution attributed proportionally across an eligible expenditure base.

### TRACED
A transfer is followed across funds or governments to a later use without creating an additional dollar.

### ACTUAL
A completed-period expenditure, outlay, receipt, or other realized financial quantity.

### ENACTED
A legally adopted current-period budget quantity that is not yet a completed actual.

### PROPOSED
A proposal or estimate that has not become a completed actual.

### OUTLAY
Federal cash disbursement. For the federal warehouse this is the preferred completed-period expenditure metric when available.

### OBLIGATION
A legal commitment that will or may require payment. Obligations are not silently substituted for outlays.

### APPROPRIATION / BUDGET AUTHORITY
Authority to incur obligations, not the same as an outlay.

### MIXED-FUNDING
A program or expenditure whose funding sources cannot be separated sufficiently to make a source-specific attribution without modeling.

### RESIDUAL
An amount that remains explicitly unassigned within a deeper view because available evidence does not support a defensible child classification. Residuals are part of conservation, not missing arithmetic.

## 3. Atomic fiscal objects

TaxTrace distinguishes the following objects rather than treating “the budget” as one table:

- tax/revenue type;
- financing source;
- funding pool/fund;
- transfer;
- expenditure/outlay;
- classification or dimension;
- award/recipient relationship;
- jurisdiction;
- source release and coverage state.

Multiple classifications may describe the same spending. Classification overlap never creates another dollar.

## 4. User tax liability

For revenue type `r`, let:

`T_r = the user's calculated or modeled personal tax liability for revenue type r`.

The default concept is statutory/personal liability, not full economic incidence. Refundable credits are reported separately and do not create negative tax dollars available for allocation.

Withholding is cash prepayment, not liability. A future import of withholding information must not represent withholding as final tax paid unless the view is explicitly about cash flow.

## 5. Revenue-to-pool mapping

Let `alpha(r,p)` be the fraction of revenue type `r` assigned to funding pool `p`.

For a completely mapped revenue type:

`sum_p alpha(r,p) = 1`.

The user's contribution to pool `p` is:

`C_p = sum_r T_r * alpha(r,p)`.

Every mapping has effective dates and an authority/source explanation. Active shares must sum to one within configured numerical tolerance.

Current federal mappings include:

- federal individual income tax → federal general financing pool;
- employee OASDI tax → OASI and DI according to the represented statutory/current-law split;
- employee Medicare tax → Medicare Hospital Insurance financing pool;
- Additional Medicare Tax → Medicare Hospital Insurance financing pool.

## 6. General-revenue allocation

When pool revenue is fungible, the engine calculates an attribution weight for eligible activity `j`:

`W(p,j) = E(p,j) / sum_k E(p,k)`

and user attribution:

`A_j = sum_p C_p * W(p,j)`.

A complete additive partition must satisfy:

`sum_j A_j = sum_p C_p`.

The receipt engine enforces this invariant for every pool and the complete receipt. Displayed cents use deterministic reconciliation so children equal their displayed parent exactly.

## 7. Deficits and borrowing

Borrowing does **not** enlarge the user's tax receipt. If a user has `$8,000` of allocable personal tax liability, the primary receipt allocates `$8,000` even when government outlays exceed current receipts.

Borrowing is a financing source, not a program expenditure. Current interest/debt-service outlays can be expenditures to which current general revenue is attributed, but debt issuance itself is not treated as another use of the user's tax dollars.

## 8. Transfers and double counting

A dollar transferred Federal → State → Municipality remains one dollar. TaxTrace may display its path, but a complete additive view cannot count the transfer and final expenditure as two dollars.

The same rule applies to interfund/intragovernmental transfers. Each additive view must choose the appropriate stage and conserve the underlying amount.

## 9. Enterprise funds and fees

A charge for a government enterprise service is not automatically a tax. Utilities, parking charges, fares, solid-waste fees, and similar revenues remain distinct from personal taxes.

A tax-financed transfer into an enterprise fund may later be traced to its use without reclassifying customer fees as tax revenue.

## 10. Expenditure metric precedence

For a primary completed-period receipt, preferred evidence is:

1. actual outlay/expenditure;
2. enacted/current budget only when an actual is unavailable and the UI says so;
3. proposed/estimated budget only in an explicitly proposed view.

Obligations may be explored as obligations but are not silently substituted for actual outlays.

OMB years identified by the source as estimates remain distinct from historical actuals.

## 11. Fiscal-year versus tax-year alignment

A user's tax year and the latest completed spending fiscal year may differ. Every receipt carries both. TaxTrace never manufactures a completed spending year simply to match the tax year.

## 12. Classification dimensions and non-additivity

Federal spending may simultaneously be classified by:

- budget function/subfunction;
- agency/subagency;
- federal account/Treasury account;
- program activity;
- object class;
- award and recipient;
- subaward and subrecipient.

State/local data can simultaneously use fund, department, function, object, project, vendor, program, government, and native finance item code.

Amounts across these dimensions cannot be summed unless a specific mapping proves they form a mutually exclusive partition.

## 13. Source hierarchy and provenance

Preferred evidence order is:

1. official audited/administrative financial records;
2. official government financial databases;
3. official budget/financial reports;
4. standardized official statistical sources;
5. secondary sources for interpretation only unless no primary source exists and the limitation is explicit.

Imported evidence retains enough immutable metadata to identify its source, vintage/reference period, retrieval or ingestion event, parser/materializer, content identity, and stored object.

A revised source creates a new snapshot or dataset release rather than silently replacing the evidentiary basis of an older calculation.

## 14. Federal source roles

### U.S. Treasury
Used for authoritative aggregate federal receipt/outlay control information.

### OMB Public Budget Database
Used for the controlling federal account and function actual-outlay base for the personalized federal receipt. OMB remains the additive parent when deeper USAspending dimensions are displayed.

### USAspending / DATA Act files
Used for deeper account, program-activity, object-class, award, recipient, transaction, subaward, and subrecipient detail. File A, File B, File C, D1, D2, and File F preserve their native grains and are not six additive spending piles.

## 15. Reconciliation

Source systems differ in timing, revisions, gross/net treatment, scope, and classification. Differences are retained rather than deleted.

The repository's generic reconciliation defaults are:

- absolute relative difference <= 0.1%: `PASS`;
- >0.1% and <=1%: `REVIEW`;
- >1%: `FAIL`.

These are operational defaults, not a statement that every source pair ought to match exactly. Specific V2 relationships can impose stricter semantic gates, such as refusing File C award attribution when the File C account total exceeds its File B denominator.

## 16. Monetary precision and rounding

Money is represented with fixed-precision decimals. Float arithmetic is not used for tax liability or allocation mathematics.

Calculations retain precision internally. Additive receipt/explorer views use deterministic cent reconciliation so displayed children sum exactly to their displayed parent and source-row order cannot move a rounding cent unpredictably.

## 17. Confidence versus uncertainty

A methodology confidence grade is not a statistical confidence interval.

Current semantics are:

- **A** — statutory calculation plus high-quality actual expenditure and direct financing relationship;
- **B** — statutory calculation plus high-quality actual expenditure and proportional general-pool attribution;
- **C** — one material modeled component;
- **D** — multiple material assumptions or incomplete funding separation;
- **N/A** — insufficient data.

Statistical prediction uncertainty, where available, should be shown separately.

## 18. Refusal rule

Specificity ends where evidence ends. If a source cannot support a child allocation safely, TaxTrace returns an explicit residual, unavailable state, incomplete coverage warning, or non-additive reference instead of inventing precision.

## 19. Machine-enforced invariants

Implemented invariants include:

- active revenue-to-pool shares sum to 1;
- tax and allocation money uses decimals;
- source/lake objects retain immutable provenance/content identity;
- actual/proposed status remains explicit where applicable;
- overlapping dimensions retain distinct grains;
- reconciliation differences remain visible;
- additive receipt and explorer scopes conserve their parent;
- tax rules are versioned by tax year;
- partial-period federal bulk releases cannot silently stand in for full-year personalization;
- File C/D1/D2/File F relationships require canonical identity control before enrichment;
- File F cannot be counted beside its prime award as an additional federal expenditure;
- Search V2 results are always non-additive.

## 20. Methodology change policy

A change that alters the semantic meaning or numerical result of a published receipt requires a methodology-version change and changelog/documentation entry. Historical calculations must retain enough version metadata to remain reproducible.

The authoritative current machine-readable version is centralized in `taxtrace.methodology.version.METHODOLOGY_VERSION`.

Product or search changes that do not change tax calculation or personalized allocation semantics may advance the application version without advancing methodology.

## 21. Operational pool-to-spending eligibility (methodology 1.1.0)

Phase 4 made funding-pool restrictions operational through effective-dated `PoolSpendRule` rows.

- `FED_GENERAL` allocates across eligible OMB actual account outlays after excluding the Social Security 650/651 base. Medicare remains in the general allocation domain because it is materially mixed-funded. General attribution is `ALLOCATED`, confidence B.
- `OASI` and `DI` restrict attribution to the Social Security 650/651 spending base. Their revenue relationship is `DIRECT`, but the current public expenditure grain does not fully separate final OASI and DI uses, so confidence is reduced.
- `MEDICARE_HI` restricts attribution to the Medicare 570/571 spending base. Because that broad base contains spending financed from other sources, confidence remains reduced for source separation.
- A displayed purpose receiving attribution from more than one financing pool is labeled `MIXED_FUNDING` rather than implying one exclusive funding source.

If an active pool has no matching actual expenditure facts, TaxTrace does not widen it automatically. The contribution remains `UNALLOCATED_DETAIL` with confidence N/A.

## 22. Drill-down explorer methodology

The explorer begins with already-computed receipt allocations and changes only how those facts are grouped or how a defensible parent scope is subdivided.

OMB purpose, agency, and federal-account views regroup the same allocated OMB account facts. When deeper data cover only part of a parent scope, uncovered value remains a residual.

Every additive explorer response must satisfy:

`sum(view children including residual) = selected parent scope amount`.

Explorer views are not additive across dimensions. Adding agency to purpose, File B to File C, or award detail to account totals would double count the same receipt.

## 23. Award/recipient semantics

Awards are a detail classification, not an additional expenditure layer. Award, transaction, obligation, and subaward values can describe or subdivide a defensible parent scope but are not added on top of OMB account attribution.

The validated canonical identity aliases are:

```text
File C: award_unique_key
D1:     contract_award_unique_key
D2:     assistance_award_unique_key
File F: prime_award_unique_key
```

They identify relationships rather than authorize raw additive joins.

## 24. Search methodology

### 24.1 Legacy portable search

The original Phase 6 search maintains a relational index over normalized finance entities. It uses canonical titles, descriptions, identifiers, aliases, abbreviations, curated synonyms, and approximate similarity. That surface remains available for compatibility and legacy non-award entities.

Manual/curated aliases remain separate from official source names so TaxTrace does not rewrite government-native labels.

### 24.2 Federal Search V2 (application 0.6.5)

Federal Search V2 searches normalized full-year D1/D2 and File F Parquet directly with DuckDB. Award-scale rows are not copied into the legacy relational search-document table.

D1/D2 are transaction grains. Matching transactions are collapsed to the canonical prime-award identity before a prime award is returned. A prime result may expose descriptive transaction count and selected attributes, but D1/D2 monetary fields do not create personalized dollars.

Recipient results group distinct canonical prime-award identities by recipient name/UEI. A recipient result can overlap prime-award results and other finance classifications and is always non-additive.

File F is searched independently as downstream subaward/subrecipient detail. A subaward result links back to its prime-award identity and is always non-additive.

Candidate matching can use identifiers, recipient/subrecipient names, UEIs, descriptions, agency names, award types, and subaward numbers. Ranking may combine exact, prefix, substring, token, and approximate text similarity. Ranking is a navigation heuristic and has no accounting meaning.

Annual V2 search accepts only a READY exact full-year award release. Bounded validation slices are not represented as complete annual search coverage. If a full-year release or local normalized Parquet is unavailable, TaxTrace returns explicit incomplete coverage rather than fabricating results.

### 24.3 Receipt-aware search

Receipt-aware V2 search does not calculate personalized award amounts from D1/D2 or File F.

Instead it may annotate results only from the already-conserved File C award projection:

1. a prime-award result may receive the existing File C personalized amount for that canonical identity;
2. a recipient result may aggregate existing File C identity allocations matching that recipient name/UEI;
3. a File F subaward receives **no** personalized amount;
4. a subaward may expose its prime award's personalized amount only as explicitly labeled navigation context.

Search therefore cannot enlarge or redistribute the user's receipt.

All search results are discovery/navigation results and expose `additive = false`.

Federal Search V2 changes discovery and ranking behavior but not the methodology-1.3.0 allocation semantics, so application 0.6.5 does not advance the methodology version.

## 25. Florida, Alachua, Gainesville, and modeled sales tax (methodology 1.2.0)

Methodology 1.2.0 added the implemented state/local quick-mode rules in Phases 7, 8, and 9A.

- Florida quick mode does not invent an individual wage-income tax where none is supported.
- Because wages do not reveal actual taxable purchases, Florida and Alachua sales-tax liabilities are `MODELED`, not `CALCULATED`.
- The model uses versioned BLS Consumer Expenditure information and an explicit TaxTrace taxability matrix instead of multiplying wages directly by a sales-tax rate.
- Florida state sales tax is allocated across a mutually exclusive audited governmental-activity expenditure partition.
- Alachua discretionary surtax remains in dedicated legal-purpose pools rather than being blended into all local spending.
- Florida and Alachua additive partitions conserve independently at displayed-cent precision.
- Gainesville audited governmental spending can be shown as an `ACTUAL` reference but is non-additive to the personalized quick-mode receipt unless a personal city tax/fee liability is established.

Detailed assumptions are documented in `docs/PHASE_7_8_9A.md`.

## 26. Warehouse V2 federal account detail (methodology 1.3.0)

Methodology 1.3.0 makes Warehouse V2 the operational deep-detail path for the personalized federal product while retaining OMB actual account outlays as the controlling additive parent.

### 26.1 File B program-activity × object-class partition

For a federal account with personalized OMB-controlled attribution `A_account`, TaxTrace may use safe full-year File B rows to partition that existing amount.

Let `B_i` be the signed File B FY-beginning-to-period-end outlay for child `i` and:

`B_account = sum_i B_i`.

When the denominator is usable:

`A_i = A_account * B_i / B_account`.

Displayed children are cent-reconciled to `A_account`.

OMB and File B government totals are displayed independently and never added together. A source difference does not silently replace the OMB parent.

For the current account-download path, File B is treated as a full-year personalization denominator only when stored request provenance proves reporting period `12`. Missing local Parquet, unknown/partial periods, unusable denominators, or unsupported schemas produce explicit residuals/unavailable detail.

### 26.2 File C award-financial projection

File C is **not** assumed to describe 100% of an OMB account.

Let:

- `A_account` = personalized OMB-controlled account attribution;
- `B_account` = matching full-year File B account outlay;
- `C_account` = eligible full-year File C award-financial outlay for that account.

The award coverage ratio is:

`R_award = C_account / B_account`.

The current conservative gate requires:

`B_account > 0`

and

`0 <= C_account <= B_account`.

If those bounds fail, TaxTrace assigns no personalized dollars to File C awards for that account and leaves the complete parent residual in the award view.

When the bounds hold:

`A_award_pool = A_account * R_award`

`A_residual = A_account - A_award_pool`.

File C rows first collapse to canonical award identity. Repeated rows contribute to one identity-level outlay before the personalized award pool is subdivided. Blank/unlinked activity remains an explicit unlinked bucket.

Identity children plus the explicit non-award/unreconciled residual must equal `A_account` exactly after displayed-cent reconciliation.

### 26.3 D1/D2 prime transactions and File F

File C and D1/D2 can each repeat a canonical identity, so a raw row-to-row join can create many-to-many fan-out. TaxTrace collapses File C first and queries D1/D2 independently by identity for descriptive enrichment.

D1/D2 transaction counts, obligations, total award amounts, and related fields do not create additional personalized spending.

File F is downstream of the prime award. Subaward amounts are descriptive distribution context and are always non-additive. They have no independent personalized amount.

Federal Product V2 uses only READY full-fiscal-year D1/D2/File F releases for annual product detail. Bounded validation slices remain source-validation evidence only.

### 26.4 Conservation across Federal Product V2 views

Separate views include:

- OMB purpose/agency/account;
- File B program activity × object class;
- File C award-financial projection;
- D1/D2 prime-award transaction/recipient attributes;
- File F subaward/subrecipient detail.

Only explicitly marked children inside one additive partition may be summed. Cross-view addition is prohibited.

The top-level Federal Receipt V2 must satisfy:

`sum(OMB-controlled account attributions) + explicit top-level residual = total allocable personal federal taxes`.

Every File B account partition and File C account award projection must independently conserve its personalized parent at displayed-cent precision.

## 27. State/local Warehouse V2 forward rule

The nationwide Census government and finance warehouse is implemented as a source-grain backbone, but raw Census item codes can contain components and rollups. They remain non-additive until an official defensible taxonomy identifies a complete mutually exclusive expenditure partition.

A future nationwide state/local receipt must not sum native Census finance rows directly. It must first establish that additive taxonomy, preserve transfers and enterprise distinctions, and then enforce the same parent-child conservation rules used by the federal receipt.
