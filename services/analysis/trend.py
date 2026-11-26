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
# Tỷ lệ giờ tối thiểu so với số giờ kỳ vọng thực tế của bucket để xem là đầy đủ
MIN_BUCKET_COMPLETENESS: float = 0.9


def _expected_bucket_hours(bucket_ts: pd.Timestamp, freq: str) -> float:
    """Số giờ kỳ vọng thực tế của một bucket theo lịch giờ địa phương.

    - Tuần: luôn 168 giờ (7 ngày × 24, không DST ở Asia/Ho_Chi_Minh).
    - Tháng: số ngày thực tế của tháng đó (28/29/30/31) × 24.
    """
    if freq == "W":
        return 168.0
    return float(pd.Timestamp(bucket_ts).days_in_month) * 24.0


def _prepare_regular_series(
    metric_df: pd.DataFrame,
    freq: str,
    target_tz: zoneinfo.ZoneInfo,
) -> pd.Series | None:
    """Tạo chuỗi thời gian định kỳ theo tần suất freq ('MS' cho đầu tháng, 'W-MON' cho đầu tuần).

    Quy định:
    - Kiểm tra tính liên tục và độ đầy đủ của dữ liệu theo từng bucket.
    - Phân biệt bucket đầy đủ và bucket chưa hoàn chỉnh:
      + Bucket biên (đầu hoặc cuối) chưa hoàn chỉnh được cắt tỉa an toàn.
      + Bucket bên trong bị thiếu dữ liệu không được tự ý nội suy hoặc tạo dữ liệu giả;
        khi đó toàn bộ chuỗi bị từ chối để bảo đảm tính chuẩn xác của trend.
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

    # Gom nhóm: giá trị trung bình và số TIMESTAMP HỢP LỆ DUY NHẤT theo bucket.
    # Đếm distinct ts (không đếm số dòng) để bản ghi trùng timestamp không làm
    # phình độ đầy đủ của bucket.
    ts_counts = df.groupby("bucket_ts")["ts"].nunique().sort_index()
    means = df.groupby("bucket_ts")["value"].mean().sort_index()
    if means.empty:
        return None

    # Xác định độ phân giải thời gian của dữ liệu đầu vào (hourly vs đã tổng hợp)
    sorted_ts = df["ts_local"].sort_values()
    diffs = sorted_ts.diff().dropna()
    is_hourly = (diffs.median() <= pd.Timedelta(hours=2)) if len(diffs) > 0 else False

    # Đối với dữ liệu theo giờ, kiểm tra độ đầy đủ của từng bucket:
    # tỷ lệ = số timestamp distinct / số giờ kỳ vọng thực tế của bucket đó
    # (tuần: 168 giờ; tháng: số ngày thực tế của tháng × 24 giờ).
    if is_hourly:

        def _is_complete(bucket) -> bool:
            expected = _expected_bucket_hours(bucket, freq)
            return ts_counts[bucket] / expected >= MIN_BUCKET_COMPLETENESS

        bucket_indices = list(means.index)

        # Phân biệt và cắt tỉa bucket biên đầu tiên nếu chưa hoàn chỉnh
        if not _is_complete(bucket_indices[0]):
            expected = _expected_bucket_hours(bucket_indices[0], freq)
            log.info(
                "Bucket đầu %s chỉ có %d giờ distinct (%.1f%% < %.0f%% yêu cầu). "
                "Cắt tỉa bucket biên chưa hoàn chỉnh.",
                bucket_indices[0],
                ts_counts[bucket_indices[0]],
                100.0 * ts_counts[bucket_indices[0]] / expected,
                100.0 * MIN_BUCKET_COMPLETENESS,
            )
            bucket_indices = bucket_indices[1:]

        # Phân biệt và cắt tỉa bucket biên cuối cùng nếu chưa hoàn chỉnh
        if bucket_indices and not _is_complete(bucket_indices[-1]):
            expected = _expected_bucket_hours(bucket_indices[-1], freq)
            log.info(
                "Bucket cuối %s chỉ có %d giờ distinct (%.1f%% < %.0f%% yêu cầu). "
                "Cắt tỉa bucket biên chưa hoàn chỉnh.",
                bucket_indices[-1],
                ts_counts[bucket_indices[-1]],
                100.0 * ts_counts[bucket_indices[-1]] / expected,
                100.0 * MIN_BUCKET_COMPLETENESS,
            )
            bucket_indices = bucket_indices[:-1]

        if not bucket_indices:
            log.warning("Không còn bucket nào hoàn chỉnh sau khi cắt tỉa bucket biên.")
            return None

        means = means.loc[bucket_indices]

        # Kiểm tra độ đầy đủ của các bucket bên trong (interior buckets)
        incomplete_interior = [b for b in bucket_indices if not _is_complete(b)]
        if incomplete_interior:
            log.warning(
                "Chuỗi %s có %d bucket bên trong không đầy đủ dữ liệu (thiếu giờ). "
                "Không tự nội suy hay tạo dữ liệu giả; bỏ qua chuỗi.",
                freq,
                len(incomplete_interior),
            )
            return None

    # Kiểm tra tính liên tục: không được thiếu bất kỳ bucket nào ở giữa chuỗi
    full_range_freq = "MS" if freq == "M" else "W-MON"
    full_range = pd.date_range(
        start=means.index.min(), end=means.index.max(), freq=full_range_freq
    )
    if len(full_range) != len(means):
        log.warning(
            "Chuỗi %s có %d mốc nhưng khoảng thời gian liên tục cần %d mốc (có khoảng trống ở giữa).",
            freq,
            len(means),
            len(full_range),
        )
        return None

    means.index = pd.DatetimeIndex(means.index, freq=full_range_freq)
    return means


def _decompose_series(
    series: pd.Series | None,
    *,
    granularity: str,
    period: int,
    metric_name: str,
) -> list[dict[str, Any]]:
    """Tách xu hướng cho một chuỗi đã chuẩn hóa; trả [] nếu không đủ 2 chu kỳ hoặc lỗi."""
    min_points = 2 * period
    n = len(series) if series is not None else 0
    if series is None or n < min_points:
        log.info(
            "Metric '%s': chuỗi %s có %d điểm (< %d yêu cầu cho 2 chu kỳ). Bỏ qua độ phân giải này.",
            metric_name, granularity, n, min_points,
        )
        return []
    try:
        decomp = seasonal_decompose(series, model="additive", period=period)
    except Exception as exc:
        log.warning("Không thể phân tích trend chuỗi %s cho '%s': %s", granularity, metric_name, exc)
        return []
    records: list[dict[str, Any]] = []
    for ts_idx, val in decomp.trend.dropna().items():
        if not np.isnan(val) and not np.isinf(val):
            records.append({
                "granularity": granularity,
                "ts": ts_idx.to_pydatetime() if hasattr(ts_idx, "to_pydatetime") else ts_idx,
                "metric": metric_name,
                "trend_value": float(val),
            })
    log.info("Metric '%s': tách trend chuỗi %s thành công (%d điểm trend)", metric_name, granularity, len(records))
    return records


def decompose_metric_trend(
    metric_name: str,
    metric_df: pd.DataFrame,
    target_tz: zoneinfo.ZoneInfo,
) -> list[dict[str, Any]]:
    """Tách xu hướng cho một chỉ số ở cả hai độ phân giải, độc lập nhau.

    - Chuỗi tháng: period = 12, cần tối thiểu 2 chu kỳ hoàn chỉnh (>= 24 quan sát liên tục).
    - Chuỗi tuần: period = 4, cần tối thiểu 2 chu kỳ hoàn chỉnh (>= 8 quan sát liên tục).
    - Hai chuỗi được tính riêng: chuỗi nào đủ điều kiện thì ghi, chuỗi kia không bị bỏ
      chỉ vì chuỗi còn lại đã đủ. Trước đây tháng đủ thì tuần bị bỏ, khiến giao diện
      (vốn gọi tuần cho khoảng ngắn) nhận 404 khi dữ liệu dài hơn 24 tháng.
    - Loại bỏ các giá trị NaN ở đầu và cuối sau khi decompose.
    - Không nội suy hay tạo dữ liệu giả.
    - Nếu cả hai đều không đủ điều kiện, ghi log lý do và trả danh sách rỗng.
    """
    records: list[dict[str, Any]] = []
    records += _decompose_series(
        _prepare_regular_series(metric_df, freq="M", target_tz=target_tz),
        granularity="month", period=MONTH_PERIOD, metric_name=metric_name,
    )
    records += _decompose_series(
        _prepare_regular_series(metric_df, freq="W", target_tz=target_tz),
        granularity="week", period=WEEK_PERIOD, metric_name=metric_name,
    )
    if not records:
        log.warning("Metric '%s': không đủ điều kiện tính trend ở cả chuỗi tháng và tuần. Bỏ qua metric này.", metric_name)
    return records


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


def trend_series_feasible(metric_df: pd.DataFrame, tz_name: str | None = None) -> bool:
    """Kiểm tra một metric có đủ điều kiện tách trend hay không.

    Dùng đúng cùng logic `_prepare_regular_series` và cùng ngưỡng tối thiểu với
    `decompose_metric_trend`: ưu tiên chuỗi tháng (>= 2*MONTH_PERIOD điểm liên tục,
    bucket đầy đủ), fallback chuỗi tuần (>= 2*WEEK_PERIOD điểm). Dùng cho Quality
    Gate để điều kiện "đủ" khớp với điều kiện thuật toán thật.
    """
    if metric_df.empty or "ts" not in metric_df.columns or "value" not in metric_df.columns:
        return False

    clean = metric_df[metric_df["value"].notna() & ~np.isinf(metric_df["value"])]
    if clean.empty:
        return False

    target_tz = zoneinfo.ZoneInfo(tz_name or settings.tz_local)

    month_series = _prepare_regular_series(clean, freq="M", target_tz=target_tz)
    if month_series is not None and len(month_series) >= 2 * MONTH_PERIOD:
        return True

    week_series = _prepare_regular_series(clean, freq="W", target_tz=target_tz)
    return week_series is not None and len(week_series) >= 2 * WEEK_PERIOD
