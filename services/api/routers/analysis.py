"""Precomputed analysis; snapshots cannot be recalculated for arbitrary windows."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from psycopg import Connection, sql

from dependencies import SnapshotRange, TimeRange, get_mart
from repository import read_rows, require_rows, time_conditions
from schemas import (
    CorrelationPoint,
    HistogramBin,
    Metric,
    PeriodType,
    SeasonalPoint,
    TrendPoint,
)

router = APIRouter(tags=["Analysis"])
Mart = Annotated[Connection, Depends(get_mart)]
Snapshot = Annotated[SnapshotRange, Depends()]


@router.get("/histogram", response_model=list[HistogramBin])
def get_histogram(metric: Metric, window: Snapshot, connection: Mart):
    return require_rows(
        read_rows(
            connection,
            "histogram",
            "metric, bin_start, bin_end, count",
            "bin_start ASC, bin_end ASC",
            [sql.SQL("metric = %s")],
            [metric],
        )
    )


@router.get("/trend", response_model=list[TrendPoint])
def get_trend(
    granularity: Literal["month", "week"],
    metric: Metric,
    window: Annotated[TimeRange, Depends()],
    connection: Mart,
):
    clauses, params = time_conditions("ts", window)
    clauses.extend([sql.SQL("granularity = %s"), sql.SQL("metric = %s")])
    return require_rows(
        read_rows(
            connection,
            "trend",
            "granularity, ts, metric, trend_value",
            "ts ASC",
            clauses,
            params + [granularity, metric],
        )
    )


@router.get("/seasonal", response_model=list[SeasonalPoint])
def get_seasonal(
    period_type: PeriodType, metric: Metric, window: Snapshot, connection: Mart
):
    return require_rows(
        read_rows(
            connection,
            "seasonal",
            "period_type, bucket, metric, value",
            "bucket ASC",
            [sql.SQL("period_type = %s"), sql.SQL("metric = %s")],
            [period_type, metric],
        )
    )


@router.get("/correlation", response_model=list[CorrelationPoint])
def get_correlation(window: Snapshot, connection: Mart):
    return require_rows(
        read_rows(
            connection,
            "correlation",
            "var_x, var_y, coef, computed_at",
            "var_x ASC, var_y ASC",
        )
    )
