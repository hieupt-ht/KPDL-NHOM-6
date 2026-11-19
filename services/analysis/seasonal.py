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


# Số quan sát hợp lệ tối thiểu cho một metric để được xem là đủ dữ liệu tính trung bình chu kỳ.
# Một hoặc hai bản ghi đơn lẻ không thể tạo thành chu kỳ lặp lại hay phản ánh tính mùa vụ thực sự.
MIN_SEASONAL_OBSERVATIONS: int = 3


def check_seasonal_cycle_completeness(
    df: pd.DataFrame,
    tz_name: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Kiểm tra độ đầy đủ theo chu kỳ (cycle completeness & periodicity) cho từng metric.

    Quy định kiểm tra:
    - hour_of_day: Có đủ 24 giờ (0..23) hay không.
    - day_of_week: Có đủ 7 ngày trong tuần (0..6) hay không.
    - month: Có đủ 12 tháng (1..12) hay không.
    - Phân biệt giá trị trung bình theo bucket và tính mùa vụ thực sự có chu kỳ lặp lại:
      Để xác nhận tính mùa vụ (confirmed = True), chuỗi cần có đủ các bucket trong chu kỳ
      và chu kỳ đó phải lặp lại ít nhất 2 lần (cycle_count >= 2).
    - Thể hiện rõ hạn chế khi dữ liệu chưa đủ 12 tháng hoặc chưa quan sát qua nhiều năm
      đối với chu kỳ tháng.

    Trả về dict tương thích ngược:
        result[metric]["hour_of_day"]: bool (True nếu đủ 24 giờ)
        result[metric]["day_of_week"]: bool (True nếu đủ 7 ngày)
        result[metric]["month"]: bool (True nếu đủ 12 tháng)
        result[metric]["cycle_details"]: thông tin chi tiết độ phủ, số chu kỳ và xác nhận mùa vụ.
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
    clean["date_local"] = clean["ts_local"].dt.date
    # Tuần ISO (%G-W%V) bắt đầu từ thứ Hai, khớp quy ước tuần của toàn hệ thống
    clean["week_local"] = clean["ts_local"].dt.strftime("%G-W%V")
    clean["year_local"] = clean["ts_local"].dt.year

    result: dict[str, dict[str, Any]] = {}
    for m, m_group in clean.groupby("metric"):
        m_str = str(m)
        # Số lần lặp của một bucket = số chu kỳ khác nhau mà bucket đó xuất hiện.
        # hour_of_day: mỗi giờ phải xuất hiện trong >= 2 ngày khác nhau.
        unique_hours = set(m_group["bucket_hour"].unique())
        hour_complete = len(unique_hours) == 24
        hour_rep = m_group.groupby("bucket_hour")["date_local"].nunique()
        hour_min_rep = int(hour_rep.min()) if not hour_rep.empty else 0
        hour_max_rep = int(hour_rep.max()) if not hour_rep.empty else 0
        # Số chu kỳ hoàn chỉnh: tính theo số quan sát chia cho độ dài chu kỳ 24
        hour_cycles = max(1, len(m_group) // 24) if len(m_group) >= 24 else 0
        hour_confirmed = hour_complete and (hour_min_rep >= 2)

        # Day of week (chu kỳ 7 ngày)
        # Mỗi thứ phải xuất hiện trong >= 2 tuần ISO khác nhau.
        unique_dows = set(m_group["bucket_dow"].unique())
        dow_complete = len(unique_dows) == 7
        dow_rep = m_group.groupby("bucket_dow")["week_local"].nunique()
        dow_min_rep = int(dow_rep.min()) if not dow_rep.empty else 0
        dow_max_rep = int(dow_rep.max()) if not dow_rep.empty else 0
        distinct_days = m_group["date_local"].nunique()
        dow_cycles = max(1, distinct_days // 7) if distinct_days >= 7 else 0
        dow_confirmed = dow_complete and (dow_min_rep >= 2)

        # Month (chu kỳ 12 tháng)
        # Mỗi tháng phải xuất hiện trong >= 2 năm khác nhau.
        unique_months = set(m_group["bucket_month"].unique())
        month_complete = len(unique_months) == 12
        month_cycles = int(m_group["year_local"].nunique())
        month_rep = m_group.groupby("bucket_month")["year_local"].nunique()
        month_min_rep = int(month_rep.min()) if not month_rep.empty else 0
        month_max_rep = int(month_rep.max()) if not month_rep.empty else 0
        month_confirmed = month_complete and (month_min_rep >= 2)
        month_limitation = None
        if not month_confirmed:
            month_limitation = (
                f"Chưa đủ dữ liệu để xác nhận tính mùa vụ theo tháng (hiện có {len(unique_months)}/12 tháng "
                f"qua {month_cycles} năm; cần đủ 12 tháng qua ít nhất 2 năm)."
            )

        result[m_str] = {
            "hour_of_day": hour_complete,
            "day_of_week": dow_complete,
            "month": month_complete,
            "cycle_details": {
                "hour_of_day": {
                    "cycle_complete": hour_complete,
                    "unique_buckets": len(unique_hours),
                    "expected_buckets": 24,
                    "cycle_count": hour_cycles,
                    "min_repetitions": hour_min_rep,
                    "max_repetitions": hour_max_rep,
                    "confirmed": hour_confirmed,
                },
                "day_of_week": {
                    "cycle_complete": dow_complete,
                    "unique_buckets": len(unique_dows),
                    "expected_buckets": 7,
                    "cycle_count": dow_cycles,
                    "min_repetitions": dow_min_rep,
                    "max_repetitions": dow_max_rep,
                    "confirmed": dow_confirmed,
                },
                "month": {
                    "cycle_complete": month_complete,
                    "unique_buckets": len(unique_months),
                    "expected_buckets": 12,
                    "cycle_count": month_cycles,
                    "min_repetitions": month_min_rep,
                    "max_repetitions": month_max_rep,
                    "confirmed": month_confirmed,
                    "limitation": month_limitation,
                },
            },
        }
    return result


def compute_seasonal_records(
    df: pd.DataFrame,
    tz_name: str | None = None,
) -> list[dict[str, Any]]:
    """Tính trung bình giá trị các chỉ số theo bucket mùa vụ (bucket averages).

    Các chu kỳ bucket:
    - hour_of_day: 0 đến 23
    - day_of_week: 0 đến 6 (0 = Thứ Hai, 6 = Chủ Nhật)
    - month: 1 đến 12

    Lưu ý:
    - Phép tính này cung cấp giá trị trung bình gom nhóm theo bucket (bucket averages),
      không đồng nghĩa với việc chuỗi dữ liệu đã được xác nhận có tính chu kỳ mùa vụ (periodicity).
    - Tính mùa vụ thực sự cần được đánh giá kết hợp với check_seasonal_cycle_completeness().

    Quy định:
    - Chuyển timestamp sang múi giờ chuẩn Asia/Ho_Chi_Minh trước khi tính.
    - Tuần bắt đầu từ thứ Hai (dayofweek == 0).
    - Xử lý timestamp trùng lặp qua phép tính trung bình mốc giờ trước khi phân phối vào bucket.
    - Xử lý khoảng thời gian thiếu: không tự tạo giá trị giả cho bucket không có dữ liệu.
    - Kiểm tra số lượng dữ liệu: không kết luận hay tính toán khi metric có ít hơn MIN_SEASONAL_OBSERVATIONS (3) quan sát.
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
