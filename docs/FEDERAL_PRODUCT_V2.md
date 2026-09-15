# Federal Product V2

Application target: **TaxTrace 0.6.0**  
Governing methodology: **1.3.0**

Federal Product V2 connects the national Warehouse V2 federal grains to the personalized receipt without replacing the accounting controls that made the original receipt auditable.

## Accounting hierarchy

The personalized federal path is:

```text
personal tax calculation
→ financing pools
→ OMB actual federal-account attribution
→ alternate Warehouse V2 detail views
```

OMB remains the controlling additive account parent. USAspending provides deeper classifications and relationships. Those classifications do not become independent piles of federal spending.

## File B: program activity × object class

For a federal account with personalized attribution `A_account`, full-year File B can partition that amount into program-activity × object-class children.

```text
A_child = A_account × FileB_child_outlay / FileB_account_outlay
```

The displayed children are cent-reconciled back to the OMB-controlled parent exactly.

The OMB government outlay and File B government outlay are both exposed because source systems can differ. They are never added together, and TaxTrace does not silently replace the OMB parent with File B.

A File B release is accepted for the full-year personalized partition only when stored request provenance proves reporting period `12`. If the release is partial, unknown, unavailable locally, has no normalized Parquet objects, or has an unusable denominator, the parent remains conserved through an explicit residual child.

## File C: award-financial projection

File C is not complete-account spending. It contains award-financial activity, including linked contract/assistance awards and potentially unlinked activity. TaxTrace therefore does not normalize File C to 100% of an OMB account.

For a safely matched full-year account:

```text
award_share = FileC_account_outlay / FileB_account_outlay
personalized_award_pool = personalized_OMB_account_amount × award_share
```

The current conservative gate requires:

```text
FileB_account_outlay > 0
0 <= FileC_account_outlay <= FileB_account_outlay
```

If the gate fails, no personalized dollars are assigned to File C awards. The entire account remains an explicit residual for this view.

When the gate passes, File C rows are collapsed by canonical award identity before personalized shares are calculated. Repeated File C rows for one award therefore form one award node. Blank identities are preserved as an explicit unlinked File C node rather than dropped or guessed.

Any part of the personalized account not represented by File C remains `Non-award or unreconciled account activity`.

## D1/D2: prime-award enrichment

The live-validated canonical identity aliases are:

```text
File C  award_unique_key
D1      contract_award_unique_key
D2      assistance_award_unique_key
File F  prime_award_unique_key
```

File C and D1/D2 can each contain repeated rows for the same identity. A raw join can therefore create many-to-many fan-out and multiply monetary values.

Federal Product V2 first collapses the File C side. A selected canonical identity is then queried independently against D1 or D2 to summarize descriptive prime-award information such as:

- prime award identifier;
- recipient name and UEI;
- awarding and funding agency;
- award type and description;
- transaction count;
- first and last action dates.

D1/D2 transaction monetary fields do not create additional personalized dollars. The prime summary is `additive=false` and has no independent personalized amount.

## File F: subaward drilldown

File F is downstream of a prime award. Federal Product V2 can show subaward number, subrecipient name/UEI, description, action date, and government-reported subaward amount.

Every File F result is explicitly non-additive. A `$25` subaward is not `$25` of spending to place beside the prime award. It describes how part of the prime award was distributed.

## Full-year product coverage versus validation slices

TaxTrace has live-validated D1/D2/File F ingestion using bounded source slices. A bounded slice proves the ingestion and crosswalk machinery works, but it does not prove annual product coverage.

The product detail service therefore requires a READY release keyed to the complete fiscal year (`FY{year}`) before labeling D1/D2/File F coverage full-year. Date slices remain validation evidence only.

## Additivity matrix

| View | Personalized? | Additive within itself? | Add with other views? |
| --- | --- | --- | --- |
| OMB purpose | Yes | Yes | No |
| OMB agency | Yes | Yes | No |
| OMB federal account | Yes | Yes | No |
| File B program activity × object class | Yes, as account partition | Yes within each account | No |
| File C award projection | Yes, after File B denominator gate | Yes within each account, including residual | No |
| D1/D2 prime transaction summary | No new dollars | No | No |
| File F subawards | No new dollars | No | No |

## API

Primary personalized receipt:

```text
POST /v2/receipt/federal
```

Conserved File C award projection:

```text
POST /v2/explorer/federal/awards
```

Non-additive D1/D2/File F detail for one collapsed identity:

```text
POST /v2/explorer/federal/award-detail
```

The root Next.js federal page uses the V2 receipt as its primary calculation API. It retains the mature V1 purpose/agency explorer over the nested conserved base receipt while exposing Warehouse V2 account, File B, File C, prime-recipient, and subaward detail. Federal search remains on the V1 index until the planned 0.6.5 Warehouse V2 search migration.

## Failure behavior

The V2 product is designed to become less specific when evidence disappears, not less accurate.

Examples:

- no READY File B release → conserved account residuals;
- partial File B → conserved account residuals;
- File B metadata but missing local Parquet → conserved account residuals;
- File C unavailable → no personalized award attribution;
- File C greater than File B denominator → no personalized award attribution;
- no full-year D1/D2/File F release → File C personalized award nodes remain valid, but deeper descriptive detail reports unavailable coverage;
- unlinked File C activity → explicit unlinked bucket;
- conflicting D1/D2 family match → no fabricated single-family prime summary.

At every additive level, displayed-cent conservation is a publication invariant.
