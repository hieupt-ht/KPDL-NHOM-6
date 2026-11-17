"""Tính toán tính mùa vụ (Seasonal Analysis) theo giờ trong ngày, thứ trong tuần và tháng."""

import logging
from typing import Any
import zoneinfo

import numpy as np
import pandas as pd

from common.config import settings

log = logging.getLogger(__name__)

PERIOD_TYPES: tuple[str, ...] = ("hour_of_day", "day_of_week", "month")


def compute_seasonal_records(
    df: pd.DataFrame,
    tz_name: str | None = None,
) -> list[dict[str, Any]]:
    """Tính trung bình giá trị các chỉ số theo chu kỳ mùa vụ.

    Các chu kỳ:
    - hour_of_day: 0 đến 23
    - day_of_week: 0 đến 6 (0 = Thứ Hai, 6 = Chủ Nhật)
    - month: 1 đến 12

    Quy định:
    - Chuyển timestamp sang múi giờ Asia/Ho_Chi_Minh trước khi tính.
    - Không tự tạo giá trị cho bucket không có dữ liệu.
    - Bỏ qua các giá trị NULL, NaN, Infinity.
    """
    if df.empty or "ts" not in df.columns or "metric" not in df.columns or "value" not in df.columns:
        return []

    target_tz = zoneinfo.ZoneInfo(tz_name or settings.tz_local)

    valid_mask = df["value"].notna() & ~np.isinf(df["value"])
    clean_df = df[valid_mask].copy()

    if clean_df.empty:
        return []

    clean_df["ts"] = pd.to_datetime(clean_df["ts"], utc=True)
    clean_df["ts_local"] = clean_df["ts"].dt.tz_convert(target_tz)

    records: list[dict[str, Any]] = []

    # 1. hour_of_day (0 - 23)
    clean_df["bucket_hour"] = clean_df["ts_local"].dt.hour
    grouped_hour = clean_df.groupby(["bucket_hour", "metric"])["value"].mean().reset_index()
    for _, row in grouped_hour.iterrows():
        val = float(row["value"])
        if not np.isnan(val) and not np.isinf(val):
            records.append({
                "period_type": "hour_of_day",
                "bucket": int(row["bucket_hour"]),
                "metric": str(row["metric"]),
                "value": val,
            })

    # 2. day_of_week (0 - 6, Thứ Hai = 0)
    clean_df["bucket_dow"] = clean_df["ts_local"].dt.dayofweek
    grouped_dow = clean_df.groupby(["bucket_dow", "metric"])["value"].mean().reset_index()
    for _, row in grouped_dow.iterrows():
        val = float(row["value"])
        if not np.isnan(val) and not np.isinf(val):
            records.append({
                "period_type": "day_of_week",
                "bucket": int(row["bucket_dow"]),
                "metric": str(row["metric"]),
                "value": val,
            })

    # 3. month (1 - 12)
    clean_df["bucket_month"] = clean_df["ts_local"].dt.month
    grouped_month = clean_df.groupby(["bucket_month", "metric"])["value"].mean().reset_index()
    for _, row in grouped_month.iterrows():
        val = float(row["value"])
        if not np.isnan(val) and not np.isinf(val):
            records.append({
                "period_type": "month",
                "bucket": int(row["bucket_month"]),
                "metric": str(row["metric"]),
                "value": val,
            })

    log.info("Tính toán seasonal thành công: %d bản ghi", len(records))
    return records

