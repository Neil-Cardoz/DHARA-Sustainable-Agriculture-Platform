import logging

from dhara_shared.config import get_settings
from dhara_shared.db import init_db
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import advisory, clusters, control, devices, energy, ledger, plots, storage, telemetry

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="DHARA Platform API",
    description="Core cloud API for the DHARA energy-aware irrigation, storage and advisory platform.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tightened to the operator-console origin in infra (APIM/Front Door) for production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clusters.router)
app.include_router(plots.router)
app.include_router(devices.router)
app.include_router(telemetry.router)
app.include_router(control.router)
app.include_router(storage.router)
app.include_router(advisory.router)
app.include_router(ledger.router)
app.include_router(energy.router)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/healthz")
def healthz():
    return {"status": "ok", "environment": settings.environment}
