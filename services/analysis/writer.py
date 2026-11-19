"""Ghi kết quả phân tích vào Data Mart (tầng Gold).

Đảm bảo:
- Sử dụng parameterized SQL.
- Toàn bộ quá trình ghi gói trong một Transaction duy nhất (All-or-Nothing).
- Nếu bất kỳ bước nào lỗi -> Rollback ngay lập tức, không để Gold bị cập nhật dở dang.
- Thay thế an toàn các bảng kết quả phân tích để tránh dữ liệu mồ côi hoặc trùng lặp.
- Cập nhật gold.data_freshness chỉ khi toàn bộ tác vụ phân tích thành công.
- Không tự ghi vào gold.service_runs.
- Không ghi dữ liệu giả.
"""

from collections.abc import Callable, Sequence
from datetime import datetime
import logging
from typing import Any

import psycopg

from common.db import get_mart_conn

log = logging.getLogger(__name__)

_RESAMPLED_DELETE = "DELETE FROM gold.timeseries_resampled"
_RESAMPLED_INSERT = """
    INSERT INTO gold.timeseries_resampled
        (granularity, ts, metric, mean, min, max)
    VALUES (%s, %s, %s, %s, %s, %s)
"""
_RESAMPLED_COLS = ("granularity", "ts", "metric", "mean", "min", "max")

_HISTOGRAM_DELETE = "DELETE FROM gold.histogram"
_HISTOGRAM_INSERT = """
    INSERT INTO gold.histogram
        (metric, bin_start, bin_end, count)
    VALUES (%s, %s, %s, %s)
"""
_HISTOGRAM_COLS = ("metric", "bin_start", "bin_end", "count")

_TREND_DELETE = "DELETE FROM gold.trend"
_TREND_INSERT = """
    INSERT INTO gold.trend
        (granularity, ts, metric, trend_value)
    VALUES (%s, %s, %s, %s)
"""
_TREND_COLS = ("granularity", "ts", "metric", "trend_value")

_SEASONAL_DELETE = "DELETE FROM gold.seasonal"
_SEASONAL_INSERT = """
    INSERT INTO gold.seasonal
        (period_type, bucket, metric, value)
    VALUES (%s, %s, %s, %s)
"""
_SEASONAL_COLS = ("period_type", "bucket", "metric", "value")

_CORRELATION_DELETE = "DELETE FROM gold.correlation"
_CORRELATION_INSERT = """
    INSERT INTO gold.correlation
        (var_x, var_y, coef, computed_at)
    VALUES (%s, %s, %s, now())
"""
_CORRELATION_COLS = ("var_x", "var_y", "coef")

_FRESHNESS_UPSERT = """
    INSERT INTO gold.data_freshness (id, latest_silver_ts, computed_at)
    VALUES (1, %s, now())
    ON CONFLICT (id) DO UPDATE
    SET latest_silver_ts = EXCLUDED.latest_silver_ts,
        computed_at = now()
"""


def _replace_gold_table(
    cur: psycopg.Cursor,
    delete_sql: str,
    insert_sql: str,
    columns: tuple[str, ...],
    records: Sequence[dict[str, Any]],
) -> None:
    """Xóa toàn bộ bảng Gold tương ứng rồi chèn lại records trong transaction hiện tại."""
    cur.execute(delete_sql)
    if records:
        cur.executemany(insert_sql, [tuple(r[c] for c in columns) for r in records])


def _upsert_freshness(cur: psycopg.Cursor, latest_silver_ts: datetime) -> None:
    cur.execute(_FRESHNESS_UPSERT, (latest_silver_ts,))


def _with_mart_conn(
    conn: psycopg.Connection | None,
    fn: Callable[[psycopg.Connection], None],
) -> None:
    if conn is not None:
        fn(conn)
    else:
        with get_mart_conn() as own_conn:
            fn(own_conn)


def write_resampled(
    resampled_records: Sequence[dict[str, Any]],
    conn: psycopg.Connection | None = None,
) -> None:
    """Ghi bảng gold.timeseries_resampled."""
    def _run(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                _replace_gold_table(cur, _RESAMPLED_DELETE, _RESAMPLED_INSERT, _RESAMPLED_COLS, resampled_records)

    _with_mart_conn(conn, _run)


def write_histogram(
    histogram_records: Sequence[dict[str, Any]],
    conn: psycopg.Connection | None = None,
) -> None:
    """Ghi bảng gold.histogram."""
    def _run(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                _replace_gold_table(cur, _HISTOGRAM_DELETE, _HISTOGRAM_INSERT, _HISTOGRAM_COLS, histogram_records)

    _with_mart_conn(conn, _run)


def write_trend(
    trend_records: Sequence[dict[str, Any]],
    conn: psycopg.Connection | None = None,
) -> None:
    """Ghi bảng gold.trend."""
    def _run(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                _replace_gold_table(cur, _TREND_DELETE, _TREND_INSERT, _TREND_COLS, trend_records)

    _with_mart_conn(conn, _run)


def write_seasonal(
    seasonal_records: Sequence[dict[str, Any]],
    conn: psycopg.Connection | None = None,
) -> None:
    """Ghi bảng gold.seasonal."""
    def _run(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                _replace_gold_table(cur, _SEASONAL_DELETE, _SEASONAL_INSERT, _SEASONAL_COLS, seasonal_records)

    _with_mart_conn(conn, _run)


def write_correlation(
    correlation_records: Sequence[dict[str, Any]],
    conn: psycopg.Connection | None = None,
) -> None:
    """Ghi bảng gold.correlation."""
    def _run(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                _replace_gold_table(cur, _CORRELATION_DELETE, _CORRELATION_INSERT, _CORRELATION_COLS, correlation_records)

    _with_mart_conn(conn, _run)


def write_freshness(
    latest_silver_ts: datetime,
    conn: psycopg.Connection | None = None,
) -> None:
    """Cập nhật gold.data_freshness."""
    def _run(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                _upsert_freshness(cur, latest_silver_ts)

    _with_mart_conn(conn, _run)


def write_all_analysis_results(
    resampled_records: Sequence[dict[str, Any]],
    histogram_records: Sequence[dict[str, Any]],
    trend_records: Sequence[dict[str, Any]],
    seasonal_records: Sequence[dict[str, Any]],
    correlation_records: Sequence[dict[str, Any]],
    latest_silver_ts: datetime,
    conn: psycopg.Connection | None = None,
) -> None:
    """Ghi toàn bộ kết quả phân tích vào Data Mart trong một transaction duy nhất.

    Nếu Silver rỗng hoặc latest_silver_ts là None, hàm này không được gọi.
    """
    if latest_silver_ts is None:
        raise ValueError("latest_silver_ts không được rỗng khi cập nhật Data Mart.")

    table_specs = (
        (_RESAMPLED_DELETE, _RESAMPLED_INSERT, _RESAMPLED_COLS, resampled_records),
        (_HISTOGRAM_DELETE, _HISTOGRAM_INSERT, _HISTOGRAM_COLS, histogram_records),
        (_TREND_DELETE, _TREND_INSERT, _TREND_COLS, trend_records),
        (_SEASONAL_DELETE, _SEASONAL_INSERT, _SEASONAL_COLS, seasonal_records),
        (_CORRELATION_DELETE, _CORRELATION_INSERT, _CORRELATION_COLS, correlation_records),
    )

    def _execute_in_transaction(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                for delete_sql, insert_sql, columns, records in table_specs:
                    _replace_gold_table(cur, delete_sql, insert_sql, columns, records)
                # Cập nhật gold.data_freshness sau khi toàn bộ tác vụ thành công
                _upsert_freshness(cur, latest_silver_ts)

    _with_mart_conn(conn, _execute_in_transaction)

    log.info(
        "Ghi Data Mart thành công: %d resampled, %d histogram, %d trend, %d seasonal, %d correlation. Freshness: %s",
        len(resampled_records),
        len(histogram_records),
        len(trend_records),
        len(seasonal_records),
        len(correlation_records),
        latest_silver_ts,
    )
