"""Tổng hợp dữ liệu chuỗi thời gian (Resampling) theo ngày, tuần, tháng."""

from collections.abc import Iterable
from datetime import datetime
import logging
from typing import Any
import zoneinfo

import numpy as np
import pandas as pd

from common.config import settings

log = logging.getLogger(__name__)

GRANULARITIES: tuple[str, ...] = ("day", "week", "month")


def _truncate_to_bucket(dt_series: pd.Series, granularity: str) -> pd.Series:
    """Xác định mốc thời gian đại diện (đầu chu kỳ) theo múi giờ địa phương.

    - day: Đầu ngày (00:00:00 giờ VN).
    - week: Đầu thứ Hai của tuần (00:00:00 giờ VN).
    - month: Đầu ngày mùng 1 của tháng (00:00:00 giờ VN).
    """
    if granularity == "day":
        return dt_series.dt.floor("D")

    if granularity == "week":
        # Tuần bắt đầu từ thứ Hai (dt.dayofweek == 0)
        # Lấy ngày hiện tại trừ đi số ngày chênh lệch tới thứ Hai
        days_since_monday = dt_series.dt.dayofweek
        return (dt_series - pd.to_timedelta(days_since_monday, unit="D")).dt.floor("D")

    if granularity == "month":
        # Đầu tháng (ngày 1, 00:00:00) theo múi giờ địa phương
        days_since_first = dt_series.dt.day - 1
        return (dt_series - pd.to_timedelta(days_since_first, unit="D")).dt.floor("D")

    raise ValueError(f"Không hỗ trợ granularity '{granularity}'. Chỉ chấp nhận: day, week, month.")


def compute_resampling_records(
    df: pd.DataFrame,
    tz_name: str | None = None,
) -> list[dict[str, Any]]:
    """Tính toán Mean, Min, Max theo day, week, month từ dữ liệu Silver.

    Quy định:
    - Timezone: Asia/Ho_Chi_Minh (mặc định cấu hình).
    - Tuần bắt đầu từ thứ Hai.
    - Bỏ qua các giá trị NULL, NaN, Infinity.
    - Không tự nội suy hay tạo dữ liệu cho khoảng thời gian thiếu.
    - Xử lý timestamp trùng lặp qua phép gom nhóm (aggregation).
    """
    if df.empty or "ts" not in df.columns or "metric" not in df.columns or "value" not in df.columns:
        return []

    target_tz = zoneinfo.ZoneInfo(tz_name or settings.tz_local)

    # Lọc bỏ giá trị không hợp lệ
    valid_mask = df["value"].notna() & ~np.isinf(df["value"])
    clean_df = df[valid_mask].copy()

    if clean_df.empty:
        return []

    # Chuyển ts sang datetime và đưa về timezone địa phương
    clean_df["ts"] = pd.to_datetime(clean_df["ts"], utc=True)
    clean_df["ts_local"] = clean_df["ts"].dt.tz_convert(target_tz)

    records: list[dict[str, Any]] = []

    for gran in GRANULARITIES:
        clean_df["bucket_ts"] = _truncate_to_bucket(clean_df["ts_local"], gran)

        # Gom nhóm theo (granularity, bucket_ts, metric)
        grouped = clean_df.groupby(["bucket_ts", "metric"])["value"].agg(
            mean="mean",
            min="min",
            max="max",
        ).reset_index()

        for _, row in grouped.iterrows():
            bucket_ts_val = row["bucket_ts"]
            if hasattr(bucket_ts_val, "to_pydatetime"):
                bucket_dt = bucket_ts_val.to_pydatetime()
            else:
                bucket_dt = bucket_ts_val

            records.append({
                "granularity": gran,
                "ts": bucket_dt,
                "metric": str(row["metric"]),
                "mean": float(row["mean"]),
                "min": float(row["min"]),
                "max": float(row["max"]),
            })

    log.info("Tính toán resampled thành công: %d bản ghi tổng hợp", len(records))
    return records
