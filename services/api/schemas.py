"""Response contracts matching the dashboard's field names."""

import math
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field

Metric = Literal["http_traffic", "l7_attack", "bot_share", "human_share", "netflows"]
Granularity = Literal["day", "week", "month"]
PeriodType = Literal["hour_of_day", "day_of_week", "month"]


def finite_or_none(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


Number = Annotated[float | None, BeforeValidator(finite_or_none)]


class TimeseriesPoint(BaseModel):
    granularity: Granularity
    ts: datetime
    metric: Metric
    mean: Number
    min: Number
    max: Number


class HistogramBin(BaseModel):
    metric: Metric
    bin_start: float
    bin_end: float
    count: int = Field(ge=0)


class TrendPoint(BaseModel):
    granularity: Literal["week", "month"]
    ts: datetime
    metric: Metric
    trend_value: Number


class SeasonalPoint(BaseModel):
    period_type: PeriodType
    bucket: int
    metric: Metric
    value: Number


class CorrelationPoint(BaseModel):
    var_x: Metric
    var_y: Metric
    coef: Number
    computed_at: datetime | None


class ClusterResult(BaseModel):
    date: date
    cluster_id: int
    cluster_name: str
    features: dict[str, Number] | None
    computed_at: datetime | None


class ForecastContinuous(BaseModel):
    target_date: date
    predicted_value: Number
    model_name: str | None
    created_at: datetime | None


class ForecastDiscrete(BaseModel):
    target_date: date
    label: Literal["Cao", "Thấp"] | None
    probability: Annotated[float, Field(ge=0, le=1)] | None
    model_name: str | None
    created_at: datetime | None


class ServiceRun(BaseModel):
    id: int
    service: str
    started_at: datetime | None
    finished_at: datetime | None
    status: str | None
    error: str | None


class DataFreshness(BaseModel):
    id: int
    latest_silver_ts: datetime | None
    computed_at: datetime | None


class StatusResponse(BaseModel):
    service_runs: list[ServiceRun]
    data_freshness: DataFreshness | None
