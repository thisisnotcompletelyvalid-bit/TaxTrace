# Pipelines

Production ingestion adapters live in `src/taxtrace/finance/sources/` so they are importable and testable as package code. This directory is reserved for future orchestration definitions (scheduled jobs, Dagster/Prefect/Airflow manifests, backfills) rather than source-specific parsing logic.

Current adapters:

- `treasury.py`
- `omb.py`
- `usaspending.py`

The CLI in `src/taxtrace/cli.py` is the phase-0/3 orchestration entry point.
