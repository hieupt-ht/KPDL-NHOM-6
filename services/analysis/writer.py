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
import math
from numbers import Integral, Real
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

# Tên hàm/hằng Python dùng "temporal_pattern" (mẫu hình thời gian) cho đúng
# nghiệp vụ, nhưng câu SQL vẫn ghi vào gold.seasonal — tên bảng Gold là hợp
# đồng liên module với api/frontend, giữ nguyên vì tương thích.
_TEMPORAL_PATTERN_DELETE = "DELETE FROM gold.seasonal"
_TEMPORAL_PATTERN_INSERT = """
    INSERT INTO gold.seasonal
        (period_type, bucket, metric, value)
    VALUES (%s, %s, %s, %s)
"""
_TEMPORAL_PATTERN_COLS = ("period_type", "bucket", "metric", "value")

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


def _validate_finite_values(
    records: Sequence[dict[str, Any]],
    columns: tuple[str, ...],
) -> None:
    """Từ chối ghi NaN/Infinity vào các cột đo lường số thực.

    PostgreSQL DOUBLE PRECISION chấp nhận giá trị 'NaN', nên nếu thuật toán
    lỡ trả về giá trị không hữu hạn, nó sẽ được ghi thẳng vào Gold mà không
    có lỗi nào được báo. Kiểm tra tại đây để lỗi rollback toàn bộ transaction.
    """
    for row_idx, record in enumerate(records):
        for col in columns:
            value = record[col]
            if (
                isinstance(value, Real)
                and not isinstance(value, Integral)
                and not math.isfinite(value)
            ):
                raise ValueError(
                    f"Giá trị không hữu hạn (NaN/Infinity) tại bản ghi #{row_idx}, "
                    f"cột '{col}': {value!r}. Từ chối ghi vào Gold."
                )


def _replace_gold_table(
    cur: psycopg.Cursor,
    delete_sql: str,
    insert_sql: str,
    columns: tuple[str, ...],
    records: Sequence[dict[str, Any]],
) -> None:
    """Thay thế dữ liệu bảng Gold: chỉ xóa và chèn khi có kết quả mới.

    Nếu records rỗng (ví dụ: không đủ dữ liệu để tính trend), bảng Gold cũ
    được giữ nguyên — không xóa kết quả hợp lệ trước đó.
    """
    if not records:
        return
    _validate_finite_values(records, columns)
    cur.execute(delete_sql)
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


def write_all_analysis_results(
    resampled_records: Sequence[dict[str, Any]],
    histogram_records: Sequence[dict[str, Any]],
    trend_records: Sequence[dict[str, Any]],
    temporal_pattern_records: Sequence[dict[str, Any]],
    correlation_records: Sequence[dict[str, Any]],
    latest_silver_ts: datetime,
    conn: psycopg.Connection | None = None,
) -> None:
    """Ghi toàn bộ kết quả phân tích vào Data Mart trong một transaction duy nhất.

    Đối với mỗi bảng Gold: chỉ xóa và ghi lại khi kết quả mới không rỗng.
    Bảng có kết quả rỗng (ví dụ trend không đủ dữ liệu, hoặc thuật toán bị
    quality gate bỏ qua) được giữ nguyên dữ liệu cũ.

    Freshness (phương án A — không đổi schema): gold.data_freshness chỉ được
    cập nhật khi CẢ 5 nhóm kết quả đều có dữ liệu mới trong chu kỳ này, tức là
    lần ghi "đủ" gần nhất. Nếu một nhóm rỗng: các nhóm khác vẫn được ghi, bảng
    rỗng giữ snapshot cũ, freshness giữ nguyên giá trị cũ — consumer không bị
    hiểu nhầm rằng mọi bảng Gold đều mới.

    Nếu tất cả kết quả đều rỗng: không ghi gì và không cập nhật freshness.
    Nếu bất kỳ thao tác nào thất bại, toàn bộ transaction bị rollback.
    Nếu latest_silver_ts là None, hàm này không được gọi.
    """
    if latest_silver_ts is None:
        raise ValueError("latest_silver_ts không được rỗng khi cập nhật Data Mart.")

    table_specs = (
        (_RESAMPLED_DELETE, _RESAMPLED_INSERT, _RESAMPLED_COLS, resampled_records),
        (_HISTOGRAM_DELETE, _HISTOGRAM_INSERT, _HISTOGRAM_COLS, histogram_records),
        (_TREND_DELETE, _TREND_INSERT, _TREND_COLS, trend_records),
        (_TEMPORAL_PATTERN_DELETE, _TEMPORAL_PATTERN_INSERT, _TEMPORAL_PATTERN_COLS, temporal_pattern_records),
        (_CORRELATION_DELETE, _CORRELATION_INSERT, _CORRELATION_COLS, correlation_records),
    )

    if not any(spec[3] for spec in table_specs):
        log.warning(
            "Không có kết quả phân tích mới nào. Giữ nguyên toàn bộ Gold "
            "và không cập nhật gold.data_freshness."
        )
        return

    all_groups_fresh = all(spec[3] for spec in table_specs)
    kept_tables = [
        name for name, spec in zip(
            ("timeseries_resampled", "histogram", "trend", "seasonal", "correlation"),
            table_specs,
        )
        if not spec[3]
    ]
    if kept_tables:
        log.info(
            "Các bảng Gold giữ nguyên dữ liệu cũ do không có kết quả mới: %s. "
            "gold.data_freshness không được cập nhật (chỉ cập nhật khi cả 5 nhóm đủ).",
            ", ".join(kept_tables),
        )

    def _execute_in_transaction(c: psycopg.Connection) -> None:
        with c.transaction():
            with c.cursor() as cur:
                for delete_sql, insert_sql, columns, records in table_specs:
                    _replace_gold_table(cur, delete_sql, insert_sql, columns, records)
                # Freshness = mốc Silver của lần ghi ĐỦ GẦN NHẤT: chỉ cập nhật
                # khi cả 5 nhóm kết quả đều được tính và ghi mới trong chu kỳ này.
                if all_groups_fresh:
                    _upsert_freshness(cur, latest_silver_ts)

    _with_mart_conn(conn, _execute_in_transaction)

    log.info(
        "Ghi Data Mart thành công: %d resampled, %d histogram, %d trend, %d temporal_pattern, %d correlation. Freshness cập nhật: %s",
        len(resampled_records),
        len(histogram_records),
        len(trend_records),
        len(temporal_pattern_records),
        len(correlation_records),
        all_groups_fresh,
    )
