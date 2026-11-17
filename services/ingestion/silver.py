"""Chuẩn hóa dữ liệu chỉ số vào Silver."""

import math
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import psycopg

from dbutil import use_conn
from metrics import MetricSpec


def _parse_ts(raw: Any) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def _valid(value: Any, spec: MetricSpec) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        v = float(value)  # Radar trả giá trị dạng chuỗi số, ví dụ "0.603005"
    except ValueError:
        return None
    if not math.isfinite(v) or not (spec.lo <= v <= spec.hi):
        return None
    return v


def parse_series(payload: dict[str, Any], spec: MetricSpec) -> dict[datetime, float]:
    """Tách (mốc UTC -> giá trị) hợp lệ cho một chỉ số; mốc trùng giữ giá trị cuối."""
    if payload.get("success") is not True:
        return {}
    serie = (payload.get("result") or {}).get("serie_0")
    if not isinstance(serie, dict):
        return {}
    stamps, values = serie.get("timestamps"), serie.get(spec.field)
    if not isinstance(stamps, list) or not isinstance(values, list):
        return {}
    out: dict[datetime, float] = {}
    for raw_ts, raw_v in zip(stamps, values):
        ts, v = _parse_ts(raw_ts), _valid(raw_v, spec)
        if ts is not None and v is not None:
            out[ts] = v
    return out


def upsert_metrics(
    metric: str, points: Mapping[datetime, float], *, source: str = "radar", conn: psycopg.Connection | None = None
) -> int:
    """Ghi các mốc vào Silver, cập nhật mốc đã có. Trả số mốc được ghi."""
    rows = [(ts, metric, v, source) for ts, v in points.items()]
    if not rows:
        return 0
    with use_conn(conn) as c, c.cursor() as cur:
        cur.executemany(
            "INSERT INTO silver.metrics_hourly (ts, metric, value, source) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (ts, metric) DO UPDATE SET value = EXCLUDED.value, "
            "updated_at = now(), source = EXCLUDED.source",
            rows,
        )
    return len(rows)


def read_range(
    metric: str, start: datetime, end: datetime, *, conn: psycopg.Connection | None = None
) -> dict[datetime, float]:
    with use_conn(conn) as c:
        rows = c.execute(
            "SELECT ts, value FROM silver.metrics_hourly WHERE metric = %s AND ts >= %s AND ts <= %s",
            (metric, start, end),
        ).fetchall()
    return {ts.astimezone(timezone.utc): v for ts, v in rows}


def earliest_ts(metric: str, *, conn: psycopg.Connection | None = None) -> datetime | None:
    with use_conn(conn) as c:
        row = c.execute("SELECT min(ts) FROM silver.metrics_hourly WHERE metric = %s", (metric,)).fetchone()
    return row[0].astimezone(timezone.utc) if row and row[0] else None
