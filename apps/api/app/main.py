from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from apps.api.app.routers import (
    data_v2,
    explorer,
    explorer_v2,
    health,
    methodology,
    receipt,
    receipt_v2,
    search,
    tax,
    warehouse,
)

app = FastAPI(
    title="TaxTrace API",
    version="0.6.0",
    description="Tax attribution plus a national multi-jurisdiction public-finance warehouse.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


app.include_router(health.router)
app.include_router(tax.router, prefix="/v1")
app.include_router(receipt.router, prefix="/v1")
app.include_router(explorer.router, prefix="/v1")
app.include_router(search.router, prefix="/v1")
app.include_router(warehouse.router, prefix="/v1")
app.include_router(methodology.router, prefix="/v1")
app.include_router(data_v2.router, prefix="/v2")
app.include_router(receipt_v2.router, prefix="/v2")
app.include_router(explorer_v2.router, prefix="/v2")
