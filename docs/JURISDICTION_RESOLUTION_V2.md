# Jurisdiction Resolution V2

Target application milestone: **0.7.5**

## Goal

Given authoritative geography matches for one location and one fiscal/geographic vintage, determine which governments can apply to that location without collapsing U.S. local government into one parent-child tree.

A single location can simultaneously fall within a state, county, municipality or county subdivision, one or more school-district layers, and multiple special districts. These governments are overlapping taxing/spending authorities. Their budgets are **not additive children of one another**.

## Core model

0.7.5 introduces `JurisdictionRelation` as a versioned, provenance-capable graph edge between two TaxTrace jurisdictions.

Representative relation types include:

- `GEOGRAPHICALLY_WITHIN`;
- `OVERLAPS`;
- `COEXTENSIVE`;
- `ADMINISTERED_BY` when an official source requires that distinction.

The existing `Jurisdiction.parent_id` remains a lightweight administrative convenience for legacy data. It is not sufficient evidence that one government's fiscal activity is an additive subset of another government.

`GovernmentIdentifier` remains the crosswalk table for external IDs. Resolution is effective-dated through `valid_from_year` and `valid_to_year`.

## Resolver contract

External boundary/geocoder adapters normalize source results into:

```text
scheme
value
geography_type
name (optional)
required
```

The pure resolver then:

1. normalizes identifier schemes;
2. applies fiscal-year validity bounds;
3. maps external IDs to TaxTrace governments;
4. deduplicates a government matched by multiple identifiers;
5. returns every applicable government rather than choosing one per level;
6. returns graph edges among the resolved governments;
7. reports required unmatched identifiers explicitly;
8. marks the result `additive = false`.

An optional unmatched geography does not make the whole result incomplete. A required unmatched geography does.

## Authoritative geography adapters

The initial national adapters should use U.S. Census geography products where they actually represent the relevant boundary:

- Census Geocoder for address/coordinate-to-geography lookup;
- TIGERweb/TIGER geography for states, counties, places/county subdivisions, and school districts;
- geography vintages matched to the fiscal/reference period rather than silently using current boundaries for historical finance.

The current Census Geocoder supports geography lookup from addresses and coordinates and allows explicit benchmark/vintage selection. TIGERweb exposes separate State/County, Place/County Subdivision, and School map services.

These Census geographic products do **not** imply that every independent special district in the Government Units universe has a nationally standardized polygon suitable for automatic point-in-polygon resolution. Special districts therefore require a coverage-aware strategy using official state/local boundary sources, official crosswalks, or an explicit unresolved state rather than invented applicability.

## Privacy and API boundaries

The core resolver does not store or require a street address. It accepts normalized geography identifiers.

A later adapter may accept an address or coordinates to call an authoritative geocoder, but the public product should retain only the least precise location evidence needed for the jurisdiction calculation unless the user explicitly asks for something else.

## 0.7.5 implementation order

1. relation graph schema + migration;
2. deterministic identifier resolver and API;
3. identifier-scheme registry for Census state/county/place/school GEOIDs;
4. Census Geocoder/TIGER adapter with explicit benchmark/vintage provenance;
5. crosswalk ingestion from geography GEOIDs to TaxTrace/Census government IDs;
6. special-district coverage states and state/local adapters where authoritative national polygons do not exist;
7. end-to-end jurisdiction graph examples and live-source validation;
8. release documentation and CI gates.

## Safety invariant for 0.8.0

Jurisdiction resolution identifies **which governments may apply**. It does not authorize summing their expenditures.

The future 0.8.0 nationwide receipt must calculate or model each supported tax liability against the correct taxing authority and allocate each liability within that government's own additive expenditure parent. Cross-government totals may be summed only at the personalized tax-liability layer after each jurisdiction's contribution has been independently conserved.
