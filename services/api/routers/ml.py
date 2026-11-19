"""Cluster assignments and already-computed forecasts."""

from typing import Annotated

from auth import require_user
from dependencies import Page, TimeRange, get_mart
from fastapi import APIRouter, Depends, Response
from psycopg import Connection
from repository import forecast, read_rows, require_rows, time_conditions
from schemas import ClusterResult, ForecastContinuous, ForecastDiscrete

router = APIRouter(dependencies=[Depends(require_user)], tags=["ML"])
Mart = Annotated[Connection, Depends(get_mart)]
Window = Annotated[TimeRange, Depends()]


@router.get("/clusters", response_model=list[ClusterResult])
def get_clusters(
    window: Window,
    page: Annotated[Page, Depends()],
    response: Response,
    connection: Mart,
):
    clauses, params = time_conditions("date", window, daily=True)
    return require_rows(
        read_rows(
            connection,
            "cluster_results",
            "date, cluster_id, cluster_name, features, computed_at",
            "date ASC",
            clauses,
            params,
            page,
            response,
        )
    )


@router.get("/forecast/continuous", response_model=ForecastContinuous)
def get_forecast_continuous(window: Window, connection: Mart):
    return forecast(
        connection,
        "forecast_continuous",
        "target_date, predicted_value, model_name, created_at",
        window,
    )


@router.get("/forecast/discrete", response_model=ForecastDiscrete)
def get_forecast_discrete(window: Window, connection: Mart):
    return forecast(
        connection,
        "forecast_discrete",
        "target_date, label, probability, model_name, created_at",
        window,
    )
