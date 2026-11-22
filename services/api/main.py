"""Điểm vào API đọc Data Mart."""

import logging
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from dependencies import get_mart
from routers import analysis, jobs, ml, status, timeseries

app = FastAPI(title="Cyber Radar VN API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Total-Count", "X-Limit", "X-Offset"],
)


@app.exception_handler(psycopg.Error)
def database_error(request: Request, error: psycopg.Error):
    logging.getLogger(__name__).error(
        "Data Mart failure on %s: %s", request.url.path, type(error).__name__
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "Data Mart is unavailable or its schema is not ready"},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@app.get("/ready")
def ready(
    connection: Annotated[psycopg.Connection, Depends(get_mart)],
) -> dict[str, str]:
    """Check connectivity and required tables without requiring populated data."""
    connection.execute("""SELECT 1 FROM gold.timeseries_resampled, gold.histogram,
        gold.trend, gold.seasonal, gold.correlation, gold.data_freshness,
        gold.cluster_results, gold.forecast_continuous, gold.forecast_discrete,
        gold.service_runs LIMIT 0""")
    return {"status": "ready", "service": "api"}


for router in (
    timeseries.router,
    analysis.router,
    ml.router,
    jobs.router,
    status.router,
):
    app.include_router(router, prefix="/api")
