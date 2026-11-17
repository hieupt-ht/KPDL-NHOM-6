"""Precomputed time series from the Data Mart."""

from typing import Annotated

from auth import require_user
from dependencies import Page, TimeRange, get_mart
from fastapi import APIRouter, Depends, Response
from psycopg import Connection, sql
from repository import read_rows, require_rows, time_conditions
from schemas import Granularity, Metric, TimeseriesPoint

router = APIRouter(dependencies=[Depends(require_user)], tags=["Timeseries"])


@router.get("/timeseries", response_model=list[TimeseriesPoint])
def get_timeseries(
    granularity: Granularity,
    metric: Metric,
    response: Response,
    window: Annotated[TimeRange, Depends()],
    page: Annotated[Page, Depends()],
    connection: Annotated[Connection, Depends(get_mart)],
):
    clauses, params = time_conditions("ts", window)
    clauses.extend([sql.SQL("granularity = %s"), sql.SQL("metric = %s")])
    return require_rows(
        read_rows(
            connection,
            "timeseries_resampled",
            "granularity, ts, metric, mean, min, max",
            "ts ASC",
            clauses,
            params + [granularity, metric],
            page,
            response,
        )
    )
