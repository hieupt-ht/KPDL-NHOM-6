"""Đọc dữ liệu chuỗi thời gian từ tầng Silver."""

from collections.abc import Sequence
from datetime import datetime
import logging

import pandas as pd
import psycopg

from common.db import get_warehouse_conn

log = logging.getLogger(__name__)

ALL_METRICS: tuple[str, ...] = (
    "http_traffic",
    "l7_attack",
    "bot_share",
    "human_share",
    "netflows",
)


def get_latest_silver_ts(conn: psycopg.Connection | None = None) -> datetime | None:
    """Lấy mốc thời gian mới nhất hiện có trong silver.metrics_hourly."""
    query = "SELECT MAX(ts) FROM silver.metrics_hourly"
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(query)
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else None

    with get_warehouse_conn() as own_conn:
        with own_conn.cursor() as cur:
            cur.execute(query)
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else None


def fetch_silver_metrics(
    metrics: Sequence[str] | None = None,
    conn: psycopg.Connection | None = None,
) -> pd.DataFrame:
    """Đọc dữ liệu từ silver.metrics_hourly và trả về DataFrame chuẩn hóa.

    Trả về DataFrame với các cột: ['ts', 'metric', 'value'].
    'ts' được ép kiểu datetime UTC.
    'value' được ép kiểu float64.
    """
    selected_metrics = tuple(metrics) if metrics else ALL_METRICS

    query = """
        SELECT ts, metric, value
        FROM silver.metrics_hourly
        WHERE metric = ANY(%s)
        ORDER BY ts ASC, metric ASC
    """

    def _execute(c: psycopg.Connection) -> list[tuple]:
        with c.cursor() as cur:
            cur.execute(query, (list(selected_metrics),))
            return cur.fetchall()

    if conn is not None:
        rows = _execute(conn)
    else:
        with get_warehouse_conn() as own_conn:
            rows = _execute(own_conn)

    if not rows:
        return pd.DataFrame(columns=["ts", "metric", "value"])

    df = pd.DataFrame(rows, columns=["ts", "metric", "value"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["metric"] = df["metric"].astype(str)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df
