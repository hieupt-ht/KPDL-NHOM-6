"""Latest run per service and Silver freshness, including initial empty state."""

from typing import Annotated

from fastapi import APIRouter, Depends
from psycopg import Connection

from dependencies import SnapshotRange, get_mart
from schemas import StatusResponse

router = APIRouter(tags=["Status"])


@router.get("/status", response_model=StatusResponse)
def get_status(
    window: Annotated[SnapshotRange, Depends()],
    connection: Annotated[Connection, Depends(get_mart)],
):
    runs = connection.execute("""
        SELECT DISTINCT ON (service) id, service, started_at, finished_at, status, error
        FROM gold.service_runs
        ORDER BY service, started_at DESC NULLS LAST, id DESC
    """).fetchall()
    freshness = connection.execute(
        "SELECT id, latest_silver_ts, computed_at FROM gold.data_freshness WHERE id = 1"
    ).fetchone()
    return {"service_runs": runs, "data_freshness": freshness}
