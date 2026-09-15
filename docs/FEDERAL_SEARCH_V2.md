# Federal Search V2

Application release: **0.6.5**  
Governing methodology: **1.3.0**

Federal Search V2 is the Warehouse V2 discovery layer for USAspending prime awards, recipients, subawards, and subrecipients. It is deliberately separate from the additive receipt model: search discovers relationships and navigation targets, while personalized dollars continue to originate only from the conserved receipt and File C award projection defined by methodology 1.3.0.

## Source grains

The search layer preserves the same federal award grains used by Federal Product V2:

- **D1**: contract prime-award transactions;
- **D2**: assistance prime-award transactions;
- **File F**: contract and assistance subawards.

The canonical relationship path is:

```text
File C award_unique_key
↔ D1 contract_award_unique_key
↔ D2 assistance_award_unique_key
↔ File F prime_award_unique_key
```

These are identity relationships, not additive joins.

## Search execution

Search executes directly over normalized Parquet objects with DuckDB. TaxTrace does not duplicate award-scale D1/D2/File F rows into the legacy relational search-document table.

Only a READY exact full-year release with release key `FY{year}` and federal-award coverage may back annual Search V2 results. A validation slice remains evidence that parsing and crosswalks work, but is not represented as complete annual search coverage.

D1/D2 are transaction grains. Before a prime award becomes a result, matching rows are grouped by the canonical award identity. The result may report descriptive transaction count and selected award/recipient attributes, but transaction-level monetary fields do not become personalized spending.

Recipient results group distinct prime-award identities by recipient name/UEI. A recipient result can therefore overlap prime-award results, other recipient-name variants, accounts, programs, agencies, and classifications. It is always non-additive.

File F is searched independently. A File F result points back to its prime-award identity so the user can open prime-award detail. Subaward amounts remain government-reported downstream context and are not another federal expenditure layer.

## Ranking

The initial V2 ranking is intentionally portable and deterministic. Candidate matching is performed in DuckDB over identifiers and descriptive fields, including where available:

- canonical award identity;
- PIID, FAIN, or URI;
- recipient/subrecipient name;
- recipient/subrecipient UEI;
- award/subaward description;
- awarding and funding agency names;
- award type;
- subaward number.

The application then ranks the bounded candidates using exact matches, normalized prefix/substring matches, token coverage, and approximate string similarity. A later specialized text index may improve performance or ranking without changing the public result semantics.

## Receipt-aware search

`POST /v2/search/federal` accepts the same supported personal federal-tax inputs used by the receipt plus the search query.

Receipt context does not recalculate award money from D1/D2 or File F. Instead:

1. TaxTrace builds the existing conserved File C award projection.
2. Prime-award results are annotated only when their canonical identity already has a File C personalized amount.
3. Recipient results may aggregate those existing File C identity amounts for matching recipient name/UEI.
4. A File F subaward receives **no personalized amount**.
5. A subaward may display its prime award's File C personalized amount as explicitly labeled context for navigation, but that amount is not allocated to the subaward.

This means search cannot enlarge, redistribute, or otherwise alter the user's receipt.

## API

Public-data search:

```text
GET /v2/search/federal?q=...&fiscal_year=2025&limit=20
```

Optional repeated `entity_type` filters support:

- `prime_award`
- `recipient`
- `subaward`

Receipt-aware search:

```text
POST /v2/search/federal
```

with the federal receipt inputs plus:

```json
{
  "q": "Acme Research",
  "limit": 20,
  "entity_types": []
}
```

All results expose `additive: false`.

## Web product

The dedicated Next.js route is `/search`. It supports:

- public-data search without tax inputs;
- optional receipt-context annotation;
- explicit D1/D2 and File F coverage status;
- warnings when full-year data are unavailable;
- navigation from a prime award, recipient sample award, or subaward to the canonical V2 award-detail view.

The original V1 search remains available for backward compatibility and for legacy non-award finance entities while the project continues its staged Warehouse V2 migration.

## Refusal and coverage behavior

If a READY full-year release is absent, no normalized Parquet objects are registered, or the registered objects are not local to the runtime, Search V2 returns an explicit coverage status and does not fabricate search results from incomplete data.

The core rule is unchanged: search results are discovery/navigation objects. They overlap, are non-additive, and must never be summed into a receipt.
