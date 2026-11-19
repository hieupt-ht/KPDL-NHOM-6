"""Tách thành phần xu hướng (Trend Analysis) sử dụng statsmodels.seasonal_decompose."""

from collections.abc import Iterable
import logging
from typing import Any
import zoneinfo

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import seasonal_decompose

from common.config import settings

log = logging.getLogger(__name__)

MONTH_PERIOD: int = 12  # Chu kỳ năm cho chuỗi tháng (12 tháng)
WEEK_PERIOD: int = 4   # Chu kỳ tháng cho chuỗi tuần (4 tuần)


def _prepare_regular_series(
    metric_df: pd.DataFrame,
    freq: str,
    target_tz: zoneinfo.ZoneInfo,
) -> pd.Series | None:
    """Tạo chuỗi thời gian định kỳ theo tần suất freq ('MS' cho đầu tháng, 'W-MON' cho đầu tuần).

    Không tự nội suy hoặc tạo dữ liệu giả. Nếu chuỗi có khoảng trống ở giữa,
    giữ nguyên index thực tế để kiểm tra tính liên tục.
    """
    if metric_df.empty:
        return None

    df = metric_df.copy()
    df["ts_local"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(target_tz)

    if freq == "M":
        # Gom theo tháng (đầu ngày 1 của tháng theo giờ địa phương)
        days_since_first = df["ts_local"].dt.day - 1
        df["bucket_ts"] = (df["ts_local"] - pd.to_timedelta(days_since_first, unit="D")).dt.floor("D")
    elif freq == "W":
        # Gom theo tuần bắt đầu từ thứ Hai
        days_since_mon = df["ts_local"].dt.dayofweek
        df["bucket_ts"] = (df["ts_local"] - pd.to_timedelta(days_since_mon, unit="D")).dt.floor("D")
    else:
        raise ValueError(f"Tần suất không hợp lệ: {freq}")

    # Gom nhóm lấy trung bình theo bucket
    grouped = df.groupby("bucket_ts")["value"].mean().sort_index()
    if grouped.empty:
        return None

    # Kiểm tra xem có bị thiếu mốc ở giữa hay không bằng cách tạo full range
    full_range_freq = "MS" if freq == "M" else "W-MON"
    full_range = pd.date_range(
        start=grouped.index.min(), end=grouped.index.max(), freq=full_range_freq
    )
    if len(full_range) != len(grouped):
        # Có mốc thời gian bị khuyết ở giữa chuỗi
        log.warning(
            "Chuỗi %s có %d mốc nhưng khoảng thời gian liên tục cần %d mốc (có khoảng trống).",
            freq,
            len(grouped),
            len(full_range),
        )
        # Vì yêu cầu: 'Không nội suy hoặc tạo dữ liệu giả để đủ điều kiện', nếu chuỗi bị đứt quãng không thể decompose
        return None

    grouped.index = pd.DatetimeIndex(grouped.index, freq=full_range_freq)
    return grouped


def decompose_metric_trend(
    metric_name: str,
    metric_df: pd.DataFrame,
    target_tz: zoneinfo.ZoneInfo,
) -> list[dict[str, Any]]:
    """Tách xu hướng cho một chỉ số.

    Quy tắc:
    - Ưu tiên chuỗi tháng: period = 12, cần tối thiểu 2 chu kỳ hoàn chỉnh (>= 24 quan sát liên tục).
    - Fallback chuỗi tuần: period = 4, cần tối thiểu 2 chu kỳ hoàn chỉnh (>= 8 quan sát liên tục).
    - Loại bỏ các giá trị NaN ở đầu và cuối sau khi decompose.
    - Không nội suy hay tạo dữ liệu giả.
    - Nếu không đủ điều kiện, ghi log lý do và bỏ qua.
    """
    records: list[dict[str, Any]] = []

    # 1. Thử nghiệm chuỗi tháng trước
    month_series = _prepare_regular_series(metric_df, freq="M", target_tz=target_tz)
    min_month_points = 2 * MONTH_PERIOD  # 24 điểm

    if month_series is not None and len(month_series) >= min_month_points:
        try:
            decomp = seasonal_decompose(month_series, model="additive", period=MONTH_PERIOD)
            trend_clean = decomp.trend.dropna()
            for ts_idx, val in trend_clean.items():
                if not np.isnan(val) and not np.isinf(val):
                    records.append({
                        "granularity": "month",
                        "ts": ts_idx.to_pydatetime() if hasattr(ts_idx, "to_pydatetime") else ts_idx,
                        "metric": metric_name,
                        "trend_value": float(val),
                    })
            log.info("Metric '%s': Tách trend thành công trên chuỗi tháng (%d điểm trend)", metric_name, len(records))
            return records
        except Exception as exc:
            log.warning("Không thể phân tích trend chuỗi tháng cho '%s': %s", metric_name, exc)

    month_len = len(month_series) if month_series is not None else 0
    log.info(
        "Metric '%s': Chuỗi tháng có %d điểm (< %d yêu cầu cho 2 chu kỳ). Fallback sang chuỗi tuần.",
        metric_name,
        month_len,
        min_month_points,
    )

    # 2. Fallback sang chuỗi tuần
    week_series = _prepare_regular_series(metric_df, freq="W", target_tz=target_tz)
    min_week_points = 2 * WEEK_PERIOD  # 8 điểm

    if week_series is not None and len(week_series) >= min_week_points:
        try:
            decomp = seasonal_decompose(week_series, model="additive", period=WEEK_PERIOD)
            trend_clean = decomp.trend.dropna()
            for ts_idx, val in trend_clean.items():
                if not np.isnan(val) and not np.isinf(val):
                    records.append({
                        "granularity": "week",
                        "ts": ts_idx.to_pydatetime() if hasattr(ts_idx, "to_pydatetime") else ts_idx,
                        "metric": metric_name,
                        "trend_value": float(val),
                    })
            log.info(
                "Metric '%s': Tách trend thành công trên chuỗi tuần fallback (%d điểm trend)",
                metric_name,
                len(records),
            )
            return records
        except Exception as exc:
            log.warning("Không thể phân tích trend chuỗi tuần cho '%s': %s", metric_name, exc)

    week_len = len(week_series) if week_series is not None else 0
    log.warning(
        "Metric '%s': Không đủ điều kiện tính trend. Chuỗi tuần chỉ có %d điểm (< %d yêu cầu). Bỏ qua metric này.",
        metric_name,
        week_len,
        min_week_points,
    )
    return []


def compute_trend_records(
    df: pd.DataFrame,
    metrics: Iterable[str] | None = None,
    tz_name: str | None = None,
) -> list[dict[str, Any]]:
    """Tính toán thành phần xu hướng cho các metrics từ Silver."""
    if df.empty or "metric" not in df.columns or "value" not in df.columns:
        return []

    target_tz = zoneinfo.ZoneInfo(tz_name or settings.tz_local)
    clean_df = df[df["value"].notna() & ~np.isinf(df["value"])].copy()

    if clean_df.empty:
        return []

    target_metrics = list(metrics) if metrics else clean_df["metric"].unique().tolist()
    all_records: list[dict[str, Any]] = []

    for m in target_metrics:
        m_df = clean_df[clean_df["metric"] == m]
        if m_df.empty:
            continue
        m_records = decompose_metric_trend(str(m), m_df, target_tz)
        all_records.extend(m_records)

    log.info("Hoàn tất tính trend: %d bản ghi cho %d metrics", len(all_records), len(target_metrics))
    return all_records
