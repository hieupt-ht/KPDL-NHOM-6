"""Đọc dữ liệu chuỗi thời gian từ tầng Silver."""

from collections.abc import Sequence
from datetime import datetime, timezone
import logging
from typing import Any

import numpy as np
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

DEFAULT_SOURCE: str = "radar"
VALID_SOURCES: tuple[str, ...] = ("radar", "demo")


def get_latest_silver_ts(
    source: str | None = DEFAULT_SOURCE,
    metrics: Sequence[str] | None = None,
    conn: psycopg.Connection | None = None,
) -> datetime | None:
    """Lấy mốc thời gian hợp lệ mới nhất hiện có trong silver.metrics_hourly.

    Quy định:
    - Chỉ lấy mốc có giá trị hợp lệ (NOT NULL, không Infinity).
    - Lọc theo nguồn chỉ định (mặc định: 'radar' cho production).
    - Chỉ xét các metric thuộc danh mục ALL_METRICS.
    - Timestamp trả về luôn được chuẩn hóa thành timezone-aware UTC.
    """
    selected_metrics = tuple(metrics) if metrics else ALL_METRICS

    conditions = [
        "metric = ANY(%s)",
        "value IS NOT NULL",
        "value NOT IN ('NaN'::double precision, 'Infinity'::double precision, '-Infinity'::double precision)",
    ]
    params: list[Any] = [list(selected_metrics)]

    if source is not None:
        conditions.append("COALESCE(source, 'radar') = %s")
        params.append(source)

    query = f"""
        SELECT MAX(ts)
        FROM silver.metrics_hourly
        WHERE {" AND ".join(conditions)}
    """

    def _execute(c: psycopg.Connection) -> datetime | None:
        with c.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            if not row or row[0] is None:
                return None
            ts_val = row[0]
            if isinstance(ts_val, datetime):
                return ts_val.astimezone(timezone.utc) if ts_val.tzinfo else ts_val.replace(tzinfo=timezone.utc)
            parsed = pd.to_datetime(ts_val, utc=True)
            return parsed.to_pydatetime() if pd.notna(parsed) else None

    if conn is not None:
        return _execute(conn)

    with get_warehouse_conn() as own_conn:
        return _execute(own_conn)


def fetch_silver_metrics(
    metrics: Sequence[str] | None = None,
    source: str | None = DEFAULT_SOURCE,
    conn: psycopg.Connection | None = None,
) -> pd.DataFrame:
    """Đọc dữ liệu từ silver.metrics_hourly và trả về DataFrame chuẩn hóa.

    Quy định:
    - Đọc đúng 5 metric: http_traffic, l7_attack, netflows, bot_share, human_share.
    - Phân tách nguồn dữ liệu: mặc định chọn source='radar' cho production,
      tuyệt đối không trộn lẫn 'radar' và 'demo' trong cùng một lần phân tích.
    - Chuẩn hóa timestamp sang UTC timezone-aware (bỏ qua bản ghi có mốc thời gian NaT).
    - Ép kiểu giá trị về số thực float64; xử lý an toàn NULL, NaN, Inf.
    - Phát hiện và ghi log cảnh báo khi có timestamp trùng lặp.
    - Không tự ý giới hạn [0, 1] cho http_traffic, l7_attack, netflows (thang đo tương đối Ingestion).
    - Trả về DataFrame với cấu trúc ['ts', 'metric', 'value', 'source'] tương thích hoàn toàn.
    """
    selected_metrics = tuple(metrics) if metrics else ALL_METRICS

    conditions = ["metric = ANY(%s)"]
    params: list[Any] = [list(selected_metrics)]

    if source is not None:
        conditions.append("COALESCE(source, 'radar') = %s")
        params.append(source)

    query = f"""
        SELECT ts, metric, value, COALESCE(source, 'radar') AS source
        FROM silver.metrics_hourly
        WHERE {" AND ".join(conditions)}
        ORDER BY ts ASC, metric ASC
    """

    def _execute(c: psycopg.Connection) -> list[tuple]:
        with c.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    if conn is not None:
        rows = _execute(conn)
    else:
        with get_warehouse_conn() as own_conn:
            rows = _execute(own_conn)

    columns = ["ts", "metric", "value", "source"]
    if not rows:
        return pd.DataFrame(columns=columns)

    if len(rows[0]) == 4:
        df = pd.DataFrame(rows, columns=columns)
    elif len(rows[0]) == 3:
        df = pd.DataFrame(rows, columns=["ts", "metric", "value"])
        df["source"] = source or DEFAULT_SOURCE
    else:
        df = pd.DataFrame(rows)
        df.columns = columns[: len(df.columns)]

    # 1. Chuẩn hóa timestamp sang UTC timezone-aware
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    nat_mask = df["ts"].isna()
    if nat_mask.any():
        log.warning("Phát hiện %d bản ghi có timestamp không hợp lệ (NaT). Đã loại bỏ.", int(nat_mask.sum()))
        df = df[~nat_mask].copy()

    # 2. Chuẩn hóa metric và kiểu số value
    df["metric"] = df["metric"].astype(str)
    # Lọc chỉ lấy các metric hợp lệ đã định nghĩa
    df = df[df["metric"].isin(ALL_METRICS)].copy()

    # Ép kiểu số thực (float64), chuỗi không hợp lệ sẽ thành NaN
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # 3. Đảm bảo cột source là string
    if "source" in df.columns:
        df["source"] = df["source"].astype(str)

    # 4. Phát hiện timestamp trùng lặp
    dup_mask = df.duplicated(subset=["ts", "metric"], keep=False)
    dup_count = int(dup_mask.sum())
    if dup_count > 0:
        log.warning(
            "Phát hiện %d bản ghi trùng lặp mốc thời gian (ts, metric) trong Silver.",
            dup_count,
        )

    # Đảm bảo thứ tự cột
    return df[["ts", "metric", "value", "source"]]
