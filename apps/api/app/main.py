from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.app.routers import explorer, health, methodology, receipt, search, tax, warehouse

app = FastAPI(
    title="TaxTrace API",
    version="0.2.0",
    description="Runnable implementation of TaxTrace phases 0-6.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(tax.router, prefix="/v1")
app.include_router(receipt.router, prefix="/v1")
app.include_router(explorer.router, prefix="/v1")
app.include_router(search.router, prefix="/v1")
app.include_router(warehouse.router, prefix="/v1")
app.include_router(methodology.router, prefix="/v1")
