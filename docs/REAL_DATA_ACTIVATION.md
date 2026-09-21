# Real Data Activation

TaxTrace's application code and its public-finance datasets are separate deployment concerns. A successful API process does **not** by itself mean the deployment has national product data.

Release 0.7.1 makes that distinction explicit and gives deployments one reproducible activation path.

## Product readiness contract

Use:

```text
GET /v2/data/product-readiness
```

or:

```bash
make data-status
```

The readiness response reports the actual warehouse state rather than inferring completeness from a running application.

A fixture-scale or empty deployment is reported as `FIXTURE_OR_EMPTY`. It must not present itself as a nationally populated TaxTrace instance.

For the validated Census baseline, national state/local readiness requires at least the real-source scale already demonstrated by the live gate:

- 92,114 2022 government-unit source records;
- 1,337,594 2022 finance records;
- 88,819 governments represented in the 2022 finance release;
- READY release metadata and local normalized data objects.

Federal readiness is separate. Federal core readiness requires real OMB and Treasury controls. Full federal account-detail readiness additionally requires full-fiscal-year USAspending File B and File C releases whose stored requests prove reporting period 12 and whose normalized Parquet objects are physically available on the running deployment. A separate source-activation readiness flag requires all three File A/B/C releases, so an interrupted deployment cannot skip repair merely because the product's B+C detail views are already usable.

This distinction is deliberate: database metadata without its corresponding lake objects is not usable product coverage.

## Activation command

The supported product initializer is idempotent:

```bash
make activate-product
```

The underlying command inspects current readiness first. It skips expensive national imports that are already present at validated scale and populates missing layers only when required.

The activation path can populate:

1. the national Census government registry;
2. 2022 Census government finance and the supported 2024 sample release;
3. real Treasury MTS aggregate controls;
4. real OMB Public Budget Database account data;
5. full-year USAspending DATA Act account Files A/B/C.

Raw archives and normalized lake objects are retained with release provenance.

## Docker Compose behavior

The standard Compose stack includes a one-shot data initializer between PostgreSQL and the API. A normal product stack therefore does not intentionally start the API against a fresh fixture-only database and call that a populated deployment.

The database and warehouse/raw-data locations must be backed by persistent storage. Recreating a container without retaining those volumes means the data must be activated again.

The initializer is safe to rerun because readiness is checked before expensive imports.

## Census live-source release gate

The dedicated product-data activation workflow creates a clean PostgreSQL database, runs the real national import, and verifies that the resulting deployment reaches national scale. It also selects a real government from the imported data and requires its supported 2022 Direct General Expenditure partition to conserve exactly.

This is distinct from unit tests and from the smaller Census taxonomy reconciliation gate. A synthetic fixture cannot satisfy this release gate.

## Federal live-source release gate

The federal product-data workflow starts from a clean PostgreSQL database and requires:

- current real Treasury controls;
- real OMB account rows;
- full-year period-12 USAspending account detail;
- physically present File B/File C Parquet;
- a Federal Product V2 receipt with READY full-year warehouse coverage;
- at least one OMB account matched to File B detail;
- nontrivial program/activity/object children;
- exact personalized receipt conservation.

### USAspending account source grains and transport

TaxTrace does not ask USAspending for one mixed-grain A+B+C archive.

Files A and B are requested at **Treasury Account** level because their native account/program/object detail is useful to the federal receipt. File C is requested separately at **Federal Account × award** grain. That choice is explicit in the source catalog and release provenance: the award projection already groups by federal account and canonical award identity, and USAspending's Federal Account File C performs the Treasury-account rollup upstream while preserving award identity and summing the monetary fields.

The FY2025 live probe that motivated this contract is concrete: Treasury's period-12 TAS-level File C request repeatedly failed during generation, while the equivalent Federal Account File C request completed successfully with 104,154 rows across contract, assistance, and unlinked members.

Federal Account File C can still be too large as one all-agency generator job, so its transport may be sharded across the exact set of agencies with current-period submissions. TaxTrace joins that reporting universe to USAspending's numeric top-tier agency identifiers, submits every shard, requires every shard to reach terminal success, and combines the official archives locally. Missing or failed shards fail the activation rather than degrading coverage.

These transport choices never make A, B, and C additive. Each logical release stores the exact fiscal-year/period-12 request that generated its source grain, and the personalized accounting hierarchy remains OMB-controlled.

## Government explorer

Once national state/local readiness is true, the `/governments` web route can search the imported Census government registry and display the supported state/local finance coverage and additive 2022 spending partition for individual governments.

The page surfaces readiness first. If the deployment is fixture-only or missing the national warehouse, that limitation is visible rather than silently disguised as an empty search result.

## Hosted deployment note

Merging application code into GitHub does not by itself populate an unrelated hosted database. The host must run the initializer with persistent database and lake storage, or run an equivalent one-shot activation job using the same commands.

TaxTrace should only be described as nationally populated after the deployed instance's own `/v2/data/product-readiness` response confirms the required layers are present.
