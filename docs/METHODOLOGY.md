# TaxTrace methodology specification

Methodology version: **1.1.0**
Status: governing specification for implemented phases 0–6

## 1. Headline definition

> **A user's estimated contribution** represents the amount of the user's estimated personal tax liability attributed to a government activity. Where a tax is legally or accounting-wise dedicated to a financing pool, attribution is restricted to expenditures associated with that pool. Where revenue is fungible, the user's contribution is distributed proportionally according to eligible government expenditures. This is an attribution model, not a claim that an individual taxpayer's literal dollars can be traced through the Treasury to a particular expenditure.

That definition is the core semantic contract of the project.

## 2. Controlled terminology

### CALCULATED
An amount derived deterministically from user-supplied facts and codified tax law within the supported scope.

### MODELED
An amount inferred statistically because the user's actual taxable base is not known. Future sales-tax estimates are the primary example.

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

The Phase 4 receipt engine enforces this invariant for every pool and for the complete purpose receipt. Cent rounding is reconciled so displayed children equal the displayed parent.

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

A user's tax year and the latest completed spending fiscal year may differ. Every future receipt must carry both. The system must never manufacture a completed spending year simply to match the user's tax year.

## 12. Classification dimensions and non-additivity

Federal spending may simultaneously be classified by:

- budget function/subfunction;
- agency/subagency;
- federal account/Treasury account;
- program activity;
- object class;
- award and recipient.

These describe overlapping views of spending. TaxTrace stores them as distinct warehouse scopes. Amounts from different scopes cannot be summed unless a specific mapping proves they form a mutually exclusive partition.

USAspending facts in this repository therefore include `record_scope`, such as `usaspending_object_class` or `usaspending_budget_function`.

## 13. Source hierarchy and provenance

Preferred evidence order:

1. official audited/administrative financial records;
2. official government financial databases;
3. official budget/financial reports;
4. standardized official statistical sources;
5. secondary sources for interpretation only unless no primary data exist and the limitation is explicit.

Every imported external object is backed by an immutable `SourceSnapshot` containing source URL, retrieval timestamp, reference period, SHA-256 digest, original filename, parser version, and local archived path.

A revision creates a new snapshot; it does not mutate the bytes of an old snapshot.

## 14. Federal source roles

### U.S. Treasury Combined Statement
Used as the authoritative completed-year aggregate receipts/outlays control source. Treasury describes the Combined Statement as the official publication of receipts and outlays.

### OMB Public Budget Database
Used for account/bureau/subfunction outlay and receipt detail. The FY2027 user guide documents its positional schema and reports amounts in thousands of dollars; the parser converts them to dollars.

### USAspending
Used for federal agency/account, Treasury account, program-activity, object-class, budget-function/subfunction, award, and recipient detail. These dimensions are maintained as overlapping views, not added together.

## 15. Reconciliation

Source systems differ in scope, timing, revisions, gross/net treatment, and classification. Differences are not deleted or hidden.

The repository's initial reconciliation policy is:

- absolute relative difference <= 0.1%: `PASS`;
- >0.1% and <=1%: `REVIEW`;
- >1%: `FAIL`.

These thresholds are operational defaults, not a claim that all source pairs ought to match exactly. Every reconciliation result stores both values, absolute difference, relative difference, status, and metadata.

A failed or ambiguous reconciliation should block publication of a dependent public number until reviewed.

## 16. Monetary precision and rounding

Warehouse monetary values are stored as fixed-precision decimals in dollars. Float arithmetic is not used for tax liability or allocation mathematics.

Calculations retain precision internally. Additive receipt/explorer views use a deterministic largest-remainder cent-reconciliation method so displayed children sum exactly to their displayed parent and source-row ordering cannot move a rounding cent between categories.

## 17. Confidence versus uncertainty

A methodological confidence grade is not a statistical confidence interval.

Planned confidence semantics:

- **A** — statutory calculation plus high-quality actual expenditure and direct financing relationship;
- **B** — statutory calculation plus high-quality actual expenditure and proportional general-pool attribution;
- **C** — one important modeled component;
- **D** — multiple material modeling assumptions or incomplete funding separation;
- **N/A** — insufficient data.

When a future statistical model can estimate prediction uncertainty, that interval should be reported separately.

## 18. Refusal rule

Specificity ends where evidence ends. If public accounting supports an agency total but not a particular covert or internal activity, TaxTrace must return insufficient data rather than invent a line-item estimate.

## 19. Machine-enforced invariants present in phases 0–6

- active revenue-to-pool shares sum to 1;
- money is represented with decimals;
- source bytes receive immutable content hashes;
- actual/proposed status is attached to imported OMB records;
- overlapping USAspending dimensions receive distinct scopes;
- reconciliation differences are retained explicitly;
- tax-to-pool, pool-to-child, top-level receipt, and explorer-scope conservation are enforced;
- tax rules are versioned by tax year rather than embedded as timeless constants.

## 20. Methodology change policy

A change that alters the semantic meaning or numerical result of a published receipt requires a methodology-version change and an ADR/changelog entry. Historical calculations must retain enough version metadata to remain reproducible.


## 21. Operational pool-to-spending eligibility (methodology 1.1.0)

Phase 4 makes the funding-pool restriction operational through effective-dated `PoolSpendRule` rows. The current federal rules use OMB actual account outlays as the primary receipt base.

- `FED_GENERAL` allocates across OMB actual account outlays after excluding the Social Security 650/651 base. Medicare remains in the general allocation domain because Medicare is materially mixed-funded. General-pool attribution is `ALLOCATED` and receives confidence B.
- `OASI` and `DI` restrict attribution to the Social Security 650/651 spending base. Their revenue relationship is `DIRECT`, but the current public spending grain does not separate final OASI and DI uses, so these allocations receive confidence D for incomplete source separation.
- `MEDICARE_HI` restricts attribution to the Medicare 570/571 spending base. Its revenue relationship is `DIRECT`, but that broad Medicare spending base also contains spending financed from other sources, so the current allocation receives confidence D for incomplete source separation.
- When a displayed purpose receives attribution from more than one financing pool, TaxTrace labels the combined purpose `MIXED_FUNDING`. This prevents the UI from implying that a mixed-financed program has one exclusive revenue source.

If an active pool has no matching actual expenditure facts, TaxTrace does not widen the pool automatically. The contribution is retained as `UNALLOCATED_DETAIL` with confidence N/A. This preserves the tax-dollar conservation invariant while obeying the refusal rule.

## 22. Drill-down explorer methodology

The Phase 5 explorer begins with the exact Phase 4 fact allocations and changes only how those facts are grouped or, for deeper USAspending dimensions, how a defensible parent scope is subdivided.

OMB purpose, agency, and federal-account views are direct regroupings of the same allocated OMB account facts. Program-activity detail is used only when a USAspending federal account can be crosswalked by exact federal-account code. Object-class detail is crosswalked at agency level by native code or normalized agency name. Award detail is crosswalked through explicit `AwardAccountLink` records.

When USAspending detail covers only part of a selected parent scope, the uncovered share is returned as a residual node. Therefore every explorer response is additive within itself:

`sum(view nodes including residual) = selected parent scope amount`.

Explorer views are not additive across dimensions. Adding an agency view to a purpose view would double count the same underlying receipt.

## 23. Award/recipient semantics

Awards are a detail classification, not an additional expenditure layer. Award amounts and reported award outlays are used only to subdivide a crosswalked parent receipt scope. They are never added on top of OMB outlays. Award searches may overlap each other, accounts, agencies, recipients, and program categories.

## 24. Search methodology

Phase 6 maintains a separate portable search index over normalized finance entities. Search ranking uses canonical titles, descriptions, identifiers, aliases, abbreviations, curated synonyms, and approximate string similarity. The current portable implementation is designed to run on SQLite and PostgreSQL; a later OpenSearch-backed implementation may replace ranking without changing the public entity contract.

Search results are discovery/navigation results, not an additive partition. They are explicitly marked non-additive because the same spending can match multiple entities or concepts.

Manual/curated aliases are stored separately from official names so TaxTrace never rewrites government-native source labels.
