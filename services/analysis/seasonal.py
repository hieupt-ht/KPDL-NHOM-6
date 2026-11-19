"""Tính toán tính mùa vụ (Seasonal Analysis) theo giờ trong ngày, thứ trong tuần và tháng."""

import logging
from typing import Any
import zoneinfo

import numpy as np
import pandas as pd

from common.config import settings

log = logging.getLogger(__name__)

# (period_type, tên cột bucket đã gán trên clean_df)
PERIOD_BUCKETS: tuple[tuple[str, str], ...] = (
    ("hour_of_day", "bucket_hour"),
    ("day_of_week", "bucket_dow"),
    ("month", "bucket_month"),
)


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

    clean_df["bucket_hour"] = clean_df["ts_local"].dt.hour
    clean_df["bucket_dow"] = clean_df["ts_local"].dt.dayofweek
    clean_df["bucket_month"] = clean_df["ts_local"].dt.month

    records: list[dict[str, Any]] = []
    for period_type, bucket_col in PERIOD_BUCKETS:
        grouped = clean_df.groupby([bucket_col, "metric"])["value"].mean().reset_index()
        for _, row in grouped.iterrows():
            val = float(row["value"])
            if not np.isnan(val) and not np.isinf(val):
                records.append({
                    "period_type": period_type,
                    "bucket": int(row[bucket_col]),
                    "metric": str(row["metric"]),
                    "value": val,
                })

    log.info("Tính toán seasonal thành công: %d bản ghi", len(records))
    return records
