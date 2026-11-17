"""Một endpoint x một cửa sổ: gọi API -> Bronze -> parse -> quy đổi thang -> Silver."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import psycopg

from bronze import save_raw_response
from metrics import EndpointSpec
from radar_client import RadarUnavailable, Window, fetch
from rescale import apply_scale, compute_scale
from silver import parse_series, read_range, upsert_metrics

log = logging.getLogger(__name__)


@dataclass
class EndpointResult:
    endpoint: str
    status: str  # "ok" | "skipped" | "error" | "empty"
    rows: int
    message: str = ""


def _error_text(payload: dict) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        return "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors)[:300]
    return ""


def ingest_endpoint(
    spec: EndpointSpec,
    window: Window,
    *,
    client: httpx.Client | None = None,
    conn: psycopg.Connection | None = None,
    token: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> EndpointResult:
    """Xử lý một endpoint cho một cửa sổ. Không ném lỗi mạng/dữ liệu; ConfigError (thiếu token) thì ném."""
    try:
        resp = fetch(spec.path, window, client=client, token=token, sleep=sleep)
    except RadarUnavailable as exc:
        return EndpointResult(spec.name, "error", 0, str(exc))

    save_raw_response(spec.name, resp.params, resp.status_code, resp.payload, conn=conn)
    if not resp.ok:
        msg = f"HTTP {resp.status_code} {_error_text(resp.payload)}".strip()
        return EndpointResult(spec.name, "error", 0, msg)

    series = {m: parse_series(resp.payload, m) for m in spec.metrics}
    if not any(series.values()):
        return EndpointResult(spec.name, "empty", 0, "Radar không trả điểm hợp lệ nào")

    rows, skipped = 0, []
    for metric, points in series.items():
        if not points:
            continue
        if metric.scaled:
            existing = read_range(metric.name, min(points), max(points), conn=conn)
            k = 1.0 if not existing else compute_scale(existing, points)
            if k is None:
                skipped.append(metric.name)
                log.warning("%s: vùng chồng không đủ để quy đổi, bỏ qua cửa sổ này", metric.name)
                continue
            points = apply_scale(points, k)
        rows += upsert_metrics(metric.name, points, conn=conn)

    if skipped:
        return EndpointResult(spec.name, "skipped", rows, "vùng chồng không đủ: " + ", ".join(skipped))
    return EndpointResult(spec.name, "ok", rows)
