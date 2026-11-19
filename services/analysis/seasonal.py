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


# Số quan sát hợp lệ tối thiểu cho một metric để được xem là đủ dữ liệu tính mùa vụ.
# Một bản ghi đơn lẻ không thể tạo thành chu kỳ lặp lại hay phản ánh tính mùa vụ.
MIN_SEASONAL_OBSERVATIONS: int = 2


def check_seasonal_cycle_completeness(
    df: pd.DataFrame,
    tz_name: str | None = None,
) -> dict[str, dict[str, bool]]:
    """Kiểm tra độ đầy đủ theo chu kỳ (full cycle) cho từng metric.

    - hour_of_day: Có đủ 24 giờ (0..23) hay không.
    - day_of_week: Có đủ 7 ngày trong tuần (0..6) hay không.
    - month: Có đủ 12 tháng (1..12) hay không.
    """
    if df.empty or "ts" not in df.columns or "metric" not in df.columns or "value" not in df.columns:
        return {}

    target_tz = zoneinfo.ZoneInfo(tz_name or settings.tz_local)
    clean = df[df["value"].notna() & ~np.isinf(df["value"])].copy()
    if clean.empty:
        return {}

    clean["ts_local"] = pd.to_datetime(clean["ts"], utc=True).dt.tz_convert(target_tz)
    clean["bucket_hour"] = clean["ts_local"].dt.hour
    clean["bucket_dow"] = clean["ts_local"].dt.dayofweek
    clean["bucket_month"] = clean["ts_local"].dt.month

    result: dict[str, dict[str, bool]] = {}
    for m, m_group in clean.groupby("metric"):
        result[str(m)] = {
            "hour_of_day": len(m_group["bucket_hour"].unique()) == 24,
            "day_of_week": len(m_group["bucket_dow"].unique()) == 7,
            "month": len(m_group["bucket_month"].unique()) == 12,
        }
    return result


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
    - Chuyển timestamp sang múi giờ chuẩn Asia/Ho_Chi_Minh trước khi tính.
    - Tuần bắt đầu từ thứ Hai (dayofweek == 0).
    - Xử lý timestamp trùng lặp qua phép tính trung bình mốc giờ trước khi phân phối vào bucket.
    - Xử lý khoảng thời gian thiếu: không tự tạo giá trị giả cho bucket không có dữ liệu.
    - Kiểm tra số lượng dữ liệu: không kết luận có tính mùa vụ khi metric có ít hơn MIN_SEASONAL_OBSERVATIONS quan sát.
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

    # Khử trùng lặp timestamp cho cùng một metric bằng cách lấy trung bình,
    # bảo đảm mỗi mốc thời gian có trọng số đồng đều, không làm lệch bucket
    dedup_df = clean_df.groupby(["metric", "ts_local"])["value"].mean().reset_index()

    # Kiểm tra số lượng dữ liệu theo từng metric: loại bỏ metric không đủ quan sát tối thiểu
    metric_counts = dedup_df.groupby("metric")["value"].count()
    eligible_metrics = set(metric_counts[metric_counts >= MIN_SEASONAL_OBSERVATIONS].index)

    ineligible_metrics = set(metric_counts[metric_counts < MIN_SEASONAL_OBSERVATIONS].index)
    if ineligible_metrics:
        log.info(
            "Bỏ qua các metric không đủ dữ liệu tính mùa vụ (< %d quan sát): %s",
            MIN_SEASONAL_OBSERVATIONS,
            ineligible_metrics,
        )

    if not eligible_metrics:
        log.warning("Không có metric nào đủ điều kiện quan sát tối thiểu để tính mùa vụ.")
        return []

    dedup_df = dedup_df[dedup_df["metric"].isin(eligible_metrics)].copy()

    dedup_df["bucket_hour"] = dedup_df["ts_local"].dt.hour
    dedup_df["bucket_dow"] = dedup_df["ts_local"].dt.dayofweek
    dedup_df["bucket_month"] = dedup_df["ts_local"].dt.month

    records: list[dict[str, Any]] = []
    for period_type, bucket_col in PERIOD_BUCKETS:
        grouped = dedup_df.groupby([bucket_col, "metric"])["value"].mean().reset_index()
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
