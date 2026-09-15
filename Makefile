.PHONY: install bootstrap test lint api migrate seed demo-fixtures ingest-usaspending ingest-omb ingest-treasury activate-product data-status

install:
	python -m pip install -e '.[dev]'

migrate:
	alembic upgrade head

seed:
	taxtrace warehouse seed

bootstrap: migrate seed demo-fixtures

api:
	uvicorn apps.api.app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest

lint:
	ruff check src apps tests

activate-product: migrate
	python -m taxtrace.warehouse_v2.product_activation

data-status:
	python -m taxtrace.warehouse_v2.product_activation --status-only

demo-fixtures:
	taxtrace warehouse ingest-fixtures

ingest-usaspending:
	taxtrace warehouse ingest-usaspending --fiscal-year 2025 --agency 012

ingest-omb:
	taxtrace warehouse ingest-omb --fiscal-year 2025

ingest-treasury:
	taxtrace warehouse ingest-treasury --fiscal-year 2025
