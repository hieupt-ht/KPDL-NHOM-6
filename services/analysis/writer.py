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

from collections.abc import Sequence
from datetime import datetime
import logging
from typing import Any

import psycopg

from common.db import get_mart_conn

log = logging.getLogger(__name__)


def write_resampled(
    resampled_records: Sequence[dict[str, Any]],
    conn: psycopg.Connection | None = None,
) -> None:
    """Ghi bảng gold.timeseries_resampled."""
    def _run(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                cur.execute("DELETE FROM gold.timeseries_resampled")
                if resampled_records:
                    cur.executemany(
                        """
                        INSERT INTO gold.timeseries_resampled
                            (granularity, ts, metric, mean, min, max)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (
                                r["granularity"],
                                r["ts"],
                                r["metric"],
                                r["mean"],
                                r["min"],
                                r["max"],
                            )
                            for r in resampled_records
                        ],
                    )

    if conn is not None:
        _run(conn)
    else:
        with get_mart_conn() as own_conn:
            _run(own_conn)


def write_histogram(
    histogram_records: Sequence[dict[str, Any]],
    conn: psycopg.Connection | None = None,
) -> None:
    """Ghi bảng gold.histogram."""
    def _run(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                cur.execute("DELETE FROM gold.histogram")
                if histogram_records:
                    cur.executemany(
                        """
                        INSERT INTO gold.histogram
                            (metric, bin_start, bin_end, count)
                        VALUES (%s, %s, %s, %s)
                        """,
                        [
                            (
                                r["metric"],
                                r["bin_start"],
                                r["bin_end"],
                                r["count"],
                            )
                            for r in histogram_records
                        ],
                    )

    if conn is not None:
        _run(conn)
    else:
        with get_mart_conn() as own_conn:
            _run(own_conn)


def write_trend(
    trend_records: Sequence[dict[str, Any]],
    conn: psycopg.Connection | None = None,
) -> None:
    """Ghi bảng gold.trend."""
    def _run(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                cur.execute("DELETE FROM gold.trend")
                if trend_records:
                    cur.executemany(
                        """
                        INSERT INTO gold.trend
                            (granularity, ts, metric, trend_value)
                        VALUES (%s, %s, %s, %s)
                        """,
                        [
                            (
                                r["granularity"],
                                r["ts"],
                                r["metric"],
                                r["trend_value"],
                            )
                            for r in trend_records
                        ],
                    )

    if conn is not None:
        _run(conn)
    else:
        with get_mart_conn() as own_conn:
            _run(own_conn)


def write_seasonal(
    seasonal_records: Sequence[dict[str, Any]],
    conn: psycopg.Connection | None = None,
) -> None:
    """Ghi bảng gold.seasonal."""
    def _run(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                cur.execute("DELETE FROM gold.seasonal")
                if seasonal_records:
                    cur.executemany(
                        """
                        INSERT INTO gold.seasonal
                            (period_type, bucket, metric, value)
                        VALUES (%s, %s, %s, %s)
                        """,
                        [
                            (
                                r["period_type"],
                                r["bucket"],
                                r["metric"],
                                r["value"],
                            )
                            for r in seasonal_records
                        ],
                    )

    if conn is not None:
        _run(conn)
    else:
        with get_mart_conn() as own_conn:
            _run(own_conn)


def write_correlation(
    correlation_records: Sequence[dict[str, Any]],
    conn: psycopg.Connection | None = None,
) -> None:
    """Ghi bảng gold.correlation."""
    def _run(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                cur.execute("DELETE FROM gold.correlation")
                if correlation_records:
                    cur.executemany(
                        """
                        INSERT INTO gold.correlation
                            (var_x, var_y, coef, computed_at)
                        VALUES (%s, %s, %s, now())
                        """,
                        [
                            (
                                r["var_x"],
                                r["var_y"],
                                r["coef"],
                            )
                            for r in correlation_records
                        ],
                    )

    if conn is not None:
        _run(conn)
    else:
        with get_mart_conn() as own_conn:
            _run(own_conn)


def write_freshness(
    latest_silver_ts: datetime,
    conn: psycopg.Connection | None = None,
) -> None:
    """Cập nhật gold.data_freshness."""
    def _run(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO gold.data_freshness (id, latest_silver_ts, computed_at)
                    VALUES (1, %s, now())
                    ON CONFLICT (id) DO UPDATE
                    SET latest_silver_ts = EXCLUDED.latest_silver_ts,
                        computed_at = now()
                    """,
                    (latest_silver_ts,),
                )

    if conn is not None:
        _run(conn)
    else:
        with get_mart_conn() as own_conn:
            _run(own_conn)


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

    def _execute_in_transaction(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                # 1. Ghi gold.timeseries_resampled
                cur.execute("DELETE FROM gold.timeseries_resampled")
                if resampled_records:
                    cur.executemany(
                        """
                        INSERT INTO gold.timeseries_resampled
                            (granularity, ts, metric, mean, min, max)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (
                                r["granularity"],
                                r["ts"],
                                r["metric"],
                                r["mean"],
                                r["min"],
                                r["max"],
                            )
                            for r in resampled_records
                        ],
                    )

                # 2. Ghi gold.histogram
                cur.execute("DELETE FROM gold.histogram")
                if histogram_records:
                    cur.executemany(
                        """
                        INSERT INTO gold.histogram
                            (metric, bin_start, bin_end, count)
                        VALUES (%s, %s, %s, %s)
                        """,
                        [
                            (
                                r["metric"],
                                r["bin_start"],
                                r["bin_end"],
                                r["count"],
                            )
                            for r in histogram_records
                        ],
                    )

                # 3. Ghi gold.trend
                cur.execute("DELETE FROM gold.trend")
                if trend_records:
                    cur.executemany(
                        """
                        INSERT INTO gold.trend
                            (granularity, ts, metric, trend_value)
                        VALUES (%s, %s, %s, %s)
                        """,
                        [
                            (
                                r["granularity"],
                                r["ts"],
                                r["metric"],
                                r["trend_value"],
                            )
                            for r in trend_records
                        ],
                    )

                # 4. Ghi gold.seasonal
                cur.execute("DELETE FROM gold.seasonal")
                if seasonal_records:
                    cur.executemany(
                        """
                        INSERT INTO gold.seasonal
                            (period_type, bucket, metric, value)
                        VALUES (%s, %s, %s, %s)
                        """,
                        [
                            (
                                r["period_type"],
                                r["bucket"],
                                r["metric"],
                                r["value"],
                            )
                            for r in seasonal_records
                        ],
                    )

                # 5. Ghi gold.correlation
                cur.execute("DELETE FROM gold.correlation")
                if correlation_records:
                    cur.executemany(
                        """
                        INSERT INTO gold.correlation
                            (var_x, var_y, coef, computed_at)
                        VALUES (%s, %s, %s, now())
                        """,
                        [
                            (
                                r["var_x"],
                                r["var_y"],
                                r["coef"],
                            )
                            for r in correlation_records
                        ],
                    )

                # 6. Cập nhật gold.data_freshness sau khi toàn bộ tác vụ thành công
                cur.execute(
                    """
                    INSERT INTO gold.data_freshness (id, latest_silver_ts, computed_at)
                    VALUES (1, %s, now())
                    ON CONFLICT (id) DO UPDATE
                    SET latest_silver_ts = EXCLUDED.latest_silver_ts,
                        computed_at = now()
                    """,
                    (latest_silver_ts,),
                )

    if conn is not None:
        _execute_in_transaction(conn)
    else:
        with get_mart_conn() as own_conn:
            _execute_in_transaction(own_conn)

    log.info(
        "Ghi Data Mart thành công: %d resampled, %d histogram, %d trend, %d seasonal, %d correlation. Freshness: %s",
        len(resampled_records),
        len(histogram_records),
        len(trend_records),
        len(seasonal_records),
        len(correlation_records),
        latest_silver_ts,
    )
