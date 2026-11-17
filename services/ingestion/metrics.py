"""Bảng endpoint Radar và các chỉ số lấy từ chúng (dữ liệu thuần)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSpec:
    name: str  # tên trong silver.metrics_hourly.metric
    field: str  # khóa trong result.serie_0
    scaled: bool  # True: MIN0_MAX, cần quy đổi về thang của Silver
    lo: float
    hi: float


@dataclass(frozen=True)
class EndpointSpec:
    name: str  # tên ghi vào bronze.raw_api_responses.endpoint
    path: str  # đường dẫn sau /radar
    metrics: tuple[MetricSpec, ...]


def _minmax(name: str) -> MetricSpec:
    return MetricSpec(name, "values", True, 0.0, 1.0)


ENDPOINTS: tuple[EndpointSpec, ...] = (
    EndpointSpec("http_traffic", "/http/timeseries", (_minmax("http_traffic"),)),
    EndpointSpec("l7_attack", "/attacks/layer7/timeseries", (_minmax("l7_attack"),)),
    EndpointSpec(
        "bot_class",
        "/http/timeseries_groups/bot_class",
        (
            MetricSpec("bot_share", "bot", False, 0.0, 100.0),
            MetricSpec("human_share", "human", False, 0.0, 100.0),
        ),
    ),
    EndpointSpec("netflows", "/netflows/timeseries", (_minmax("netflows"),)),
)

ALL_METRICS: tuple[str, ...] = tuple(m.name for e in ENDPOINTS for m in e.metrics)
