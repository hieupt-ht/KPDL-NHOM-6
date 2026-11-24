"""Kiểm tra chất lượng dữ liệu (Data Quality) và phát hiện bất thường (Anomaly Detection).

Mô-đun này cung cấp báo cáo đánh giá chất lượng dữ liệu Silver:
- Phát hiện NULL, NaN, Infinity.
- Phát hiện trùng lặp mốc thời gian (duplicate timestamps).
- Phát hiện các khoảng thời gian bị thiếu (temporal gaps trong bước 1 giờ).
- Kiểm tra miền giá trị hợp lệ (percentage bounds, non-negative bounds).
- Phân tích thống kê phân phối (Min, Max, Mean, Median, IQR, MAD).
- Phát hiện điểm bất thường thống kê bằng Robust Z-score (dựa trên Median & MAD)
  kết hợp IQR method, phân biệt lỗi chất lượng với biến động an ninh mạng thực tế.
- Báo cáo nội bộ và ghi log, không sửa đổi Silver và không tự tạo bảng Gold.
"""

from dataclasses import dataclass, field
import logging
from typing import Any

import numpy as np
import pandas as pd

from correlation import correlation_feasible
from reader import ALL_METRICS
from temporal_patterns import MIN_TEMPORAL_PATTERN_OBSERVATIONS
from trend import trend_series_feasible

log = logging.getLogger(__name__)

# Số quan sát hợp lệ tối thiểu cho mỗi metric để chuỗi được xem là đủ điều kiện phân tích
MIN_VALID_RECORDS_PER_METRIC: int = 24


@dataclass
class MetricQualitySummary:
    """Tóm tắt chất lượng và phân phối của một chỉ số."""

    metric: str
    total_records: int = 0
    valid_records: int = 0
    null_or_nan_count: int = 0
    inf_count: int = 0
    duplicate_count: int = 0
    invalid_value_count: int = 0
    missing_hours_count: int = 0
    temporal_coverage: float = 1.0
    min_value: float | None = None
    max_value: float | None = None
    mean_value: float | None = None
    median_value: float | None = None
    std_value: float | None = None
    iqr_value: float | None = None
    mad_value: float | None = None
    robust_z_outliers_count: int = 0
    iqr_outliers_count: int = 0
    anomaly_samples: list[dict[str, Any]] = field(default_factory=list)
    is_sufficient: bool = False
    sufficient_for_resampling: bool = False
    sufficient_for_histogram: bool = False
    sufficient_for_temporal_pattern: bool = False
    sufficient_for_trend: bool = False


@dataclass
class QualityReport:
    """Báo cáo tổng hợp chất lượng toàn bộ dữ liệu Silver."""

    is_usable: bool
    total_rows: int
    metrics_summary: dict[str, MetricQualitySummary]
    issues_detected: list[str] = field(default_factory=list)
    algorithm_fitness: dict[str, bool] = field(default_factory=dict)
    status: str = "usable"  # 'usable', 'partial', 'unusable'

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "is_usable": self.is_usable,
            "total_rows": self.total_rows,
            "issues": self.issues_detected,
            "algorithm_fitness": self.algorithm_fitness,
            "metrics": {m: vars(s) for m, s in self.metrics_summary.items()},
        }


def detect_anomalies_robust_z(
    values: np.ndarray,
    threshold: float = 3.5,
) -> tuple[np.ndarray, float, float]:
    """Tính Robust Z-score bằng Median và MAD (Median Absolute Deviation).

    Lý do áp dụng:
    Trong dữ liệu an ninh mạng, các cuộc tấn công DDoS/bot thường tạo ra các đột biến rất lớn,
    khiến Mean và Standard Deviation bị kéo lệch mạnh. Sử dụng Median và MAD mang lại tính kháng
    nhiễu (robustness) cao hơn nhiều so với Z-score thông thường.

    Công thức:
        MAD = median(|x - median(x)|)
        Robust_Z = 0.6745 * (x - median(x)) / MAD (khi MAD > 0)
    Điểm có |Robust_Z| > 3.5 được xem là ngoại lai thống kê.
    """
    if len(values) == 0:
        return np.array([], dtype=bool), 0.0, 0.0

    med = float(np.median(values))
    abs_diff = np.abs(values - med)
    mad = float(np.median(abs_diff))

    if mad > 1e-9:
        robust_z = 0.6745 * (values - med) / mad
        outliers = np.abs(robust_z) > threshold
    else:
        # Trường hợp hầu hết các điểm bằng median (MAD = 0), dùng độ lệch tuyệt đối so với mean
        std = float(np.std(values))
        if std > 1e-9:
            outliers = np.abs(values - med) > (threshold * std)
        else:
            outliers = np.zeros(len(values), dtype=bool)

    return outliers, med, mad


def detect_anomalies_iqr(values: np.ndarray) -> tuple[np.ndarray, float, float, float]:
    """Phát hiện ngoại lai theo khoảng tứ phân vị IQR.

    IQR = Q3 - Q1
    Khoảng hợp lệ: [Q1 - 1.5 * IQR, Q3 + 1.5 * IQR]
    """
    if len(values) < 4:
        return np.zeros(len(values), dtype=bool), 0.0, 0.0, 0.0

    q25, q75 = np.percentile(values, [25, 75])
    iqr = float(q75 - q25)
    lower = float(q25 - 1.5 * iqr)
    upper = float(q75 + 1.5 * iqr)
    outliers = (values < lower) | (values > upper)
    return outliers, iqr, lower, upper


def evaluate_data_quality(df: pd.DataFrame) -> QualityReport:
    """Đánh giá toàn diện chất lượng dữ liệu Silver và phát hiện bất thường."""
    issues: list[str] = []
    summaries: dict[str, MetricQualitySummary] = {}

    if df.empty or not {"ts", "metric", "value"} <= set(df.columns):
        issues.append("Dữ liệu Silver trống hoặc không đúng cấu trúc bảng.")
        return QualityReport(
            is_usable=False,
            total_rows=0,
            metrics_summary=summaries,
            issues_detected=issues,
        )

    total_rows = len(df)

    # Kiểm tra nguồn dữ liệu (source): không trộn lẫn nhiều nguồn trong một chu kỳ
    if "source" in df.columns:
        sources = df["source"].dropna().unique().tolist()
        if len(sources) > 1:
            msg = f"Phát hiện trộn lẫn nhiều nguồn dữ liệu ({sources}) trong cùng một chu kỳ phân tích."
            issues.append(msg)
            log.warning(msg)

    grouped = df.groupby("metric")

    for metric_name, group in grouped:
        summary = MetricQualitySummary(metric=str(metric_name), total_records=len(group))

        # 1. Kiểm tra timestamp trùng lặp
        dup_mask = group.duplicated(subset=["ts"], keep=False)
        summary.duplicate_count = int(dup_mask.sum())
        if summary.duplicate_count > 0:
            msg = f"Metric '{metric_name}' có {summary.duplicate_count} dòng trùng lặp timestamp."
            issues.append(msg)
            log.warning(msg)

        # 2. Kiểm tra Null / NaN / Infinity
        vals = group["value"]
        null_mask = vals.isna()
        inf_mask = np.isinf(vals)
        summary.null_or_nan_count = int(null_mask.sum())
        summary.inf_count = int(inf_mask.sum())

        finite_mask = ~null_mask & ~inf_mask
        finite_df = group[finite_mask]
        finite_vals = finite_df["value"].to_numpy(dtype=float)

        if summary.null_or_nan_count > 0:
            issues.append(f"Metric '{metric_name}' có {summary.null_or_nan_count} giá trị NULL hoặc NaN.")
        if summary.inf_count > 0:
            issues.append(f"Metric '{metric_name}' có {summary.inf_count} giá trị Infinity.")

        # 3. Kiểm tra tính hợp lệ miền giá trị theo ngữ cảnh chỉ số
        if metric_name in ("bot_share", "human_share"):
            invalid_bounds = (finite_vals < 0.0) | (finite_vals > 100.0)
        else:
            # http_traffic, l7_attack, netflows không được âm
            invalid_bounds = finite_vals < 0.0
        summary.invalid_value_count = int(invalid_bounds.sum())
        if summary.invalid_value_count > 0:
            bound_desc = "[0, 100]" if metric_name in ("bot_share", "human_share") else ">= 0"
            issues.append(
                f"Metric '{metric_name}' có {summary.invalid_value_count} giá trị ngoài miền {bound_desc}."
            )

        # Giá trị ngoài miền giá trị không được tính là quan sát hợp lệ
        valid_df = finite_df[~invalid_bounds].sort_values("ts")
        valid_vals = valid_df["value"].to_numpy(dtype=float)
        summary.valid_records = len(valid_vals)

        # 4. Kiểm tra khoảng thời gian bị thiếu (gaps > 1h) và độ phủ thời gian
        if len(valid_df) >= 2:
            ts_series = valid_df["ts"].drop_duplicates()
            total_sec = (ts_series.max() - ts_series.min()).total_seconds()
            expected_hours = int(round(total_sec / 3600.0)) + 1
            actual_hours = len(ts_series)
            missing = max(0, expected_hours - actual_hours)
            summary.missing_hours_count = missing
            summary.temporal_coverage = (
                round(actual_hours / expected_hours, 4) if expected_hours > 0 else 1.0
            )
            if missing > 0:
                log.info("Metric '%s' thiếu %d mốc giờ trong khoảng khảo sát.", metric_name, missing)
        elif len(valid_df) == 1:
            summary.temporal_coverage = 1.0
            summary.missing_hours_count = 0
        else:
            summary.temporal_coverage = 0.0
            summary.missing_hours_count = 0

        # 5. Phân phối và Anomaly Detection
        if summary.valid_records > 0:
            summary.min_value = float(np.min(valid_vals))
            summary.max_value = float(np.max(valid_vals))
            summary.mean_value = float(np.mean(valid_vals))
            summary.std_value = float(np.std(valid_vals))

            # Robust Z-score (Median & MAD)
            outliers_z, med, mad = detect_anomalies_robust_z(valid_vals)
            summary.median_value = med
            summary.mad_value = mad
            summary.robust_z_outliers_count = int(outliers_z.sum())

            # IQR
            outliers_iqr, iqr, _, _ = detect_anomalies_iqr(valid_vals)
            summary.iqr_value = iqr
            summary.iqr_outliers_count = int(outliers_iqr.sum())

            # Thu thập mẫu bất thường (kết hợp cả Robust Z và IQR)
            anomaly_mask = outliers_z | outliers_iqr
            if np.any(anomaly_mask):
                # Rào "far out" (Q3 + 3*IQR): chỉ đột biến vượt rào này mới xem
                # là nghi vấn bất thường lưu lượng mạng (TRAFFIC_ANOMALY_CANDIDATE)
                q75 = float(np.percentile(valid_vals, 75))
                far_upper = q75 + 3.0 * iqr if iqr > 0 else med + 3.0 * mad
                anom_indices = np.where(anomaly_mask)[0]
                for idx in anom_indices[:5]:
                    r = valid_df.iloc[idx]
                    is_z = bool(outliers_z[idx])
                    is_iqr = bool(outliers_iqr[idx])
                    if is_z and is_iqr:
                        method = "ROBUST_Z+IQR"
                    elif is_z:
                        method = "ROBUST_Z"
                    else:
                        method = "IQR"

                    val = float(r["value"])
                    # Không tự gán nhãn tấn công cho mọi outlier thống kê.
                    # Phân biệt: chỉ đột biến cực lớn trên metric mạng (http_traffic, l7_attack)
                    # mới được xem là ứng viên biến động an ninh mạng (TRAFFIC_ANOMALY_CANDIDATE),
                    # còn lại là STATISTICAL_OUTLIER.
                    is_attack_candidate = (
                        metric_name in ("l7_attack", "http_traffic")
                        and val > far_upper
                    )
                    category = (
                        "TRAFFIC_ANOMALY_CANDIDATE" if is_attack_candidate else "STATISTICAL_OUTLIER"
                    )
                    summary.anomaly_samples.append({
                        "metric": str(metric_name),
                        "ts": str(r["ts"]),
                        "value": val,
                        "category": category,
                        "detection_method": method,
                    })

        summary.is_sufficient = summary.valid_records >= MIN_VALID_RECORDS_PER_METRIC

        # Điều kiện "đủ" cho từng thuật toán phải khớp với cách thuật toán đó
        # thực sự đếm và lọc dữ liệu:
        # - Các thuật toán chỉ loại NULL/NaN/Inf (không loại giá trị ngoài miền
        #   như valid_records), nên đếm trên finite_df.
        # - Temporal pattern dedup theo timestamp rồi đếm số quan sát -> đếm distinct ts.
        # - Trend/Histo/Resample dùng trực tiếp các giá trị hữu hạn.
        n_finite = len(finite_vals)
        n_distinct_ts = int(finite_df["ts"].nunique()) if len(finite_df) else 0

        summary.sufficient_for_resampling = n_finite >= 1
        summary.sufficient_for_histogram = n_finite >= 1
        summary.sufficient_for_temporal_pattern = (
            n_distinct_ts >= MIN_TEMPORAL_PATTERN_OBSERVATIONS
        )
        # Trend: dùng đúng logic _prepare_regular_series của trend.py
        # (bucket đầy đủ theo giờ thực tế của tháng/tuần + liên tục + >= 2 chu kỳ).
        summary.sufficient_for_trend = trend_series_feasible(finite_df)

        summaries[str(metric_name)] = summary

    # Metric bắt buộc phải có đủ dữ liệu hợp lệ, không chỉ cần 1 metric bất kỳ
    missing_metrics = [m for m in ALL_METRICS if m not in summaries]
    for m in missing_metrics:
        issues.append(f"Metric '{m}' không có dữ liệu trong Silver.")

    insufficient = [
        m for m in ALL_METRICS
        if m in summaries and not summaries[m].is_sufficient
    ]
    for m in insufficient:
        issues.append(
            f"Metric '{m}' chỉ có {summaries[m].valid_records} quan sát hợp lệ "
            f"(< {MIN_VALID_RECORDS_PER_METRIC} yêu cầu)."
        )

    # Đánh giá khả năng đáp ứng theo từng thuật toán.
    # Mỗi điều kiện phải khớp với điều kiện thật của thuật toán tương ứng:
    # - resampling/histogram: cần >= 1 giá trị hữu hạn (histogram chỉ 3 metric).
    # - temporal_pattern: >= MIN_TEMPORAL_PATTERN_OBSERVATIONS quan sát distinct theo metric.
    # - trend: trend_series_feasible dùng chung logic bucket với decompose.
    # - correlation: correlation_feasible kiểm tra cặp quan sát ghép đôi >= 3
    #   và phương sai > 0, không chỉ đếm metric có variance.
    hist_metrics = ("http_traffic", "l7_attack", "bot_share")

    algorithm_fitness = {
        "resampling": any(s.sufficient_for_resampling for s in summaries.values()),
        "histogram": any(
            summaries[m].sufficient_for_histogram
            for m in hist_metrics
            if m in summaries
        ),
        "temporal_pattern": any(s.sufficient_for_temporal_pattern for s in summaries.values()),
        "trend": any(s.sufficient_for_trend for s in summaries.values()),
        "correlation": correlation_feasible(df),
    }

    # Đánh giá status: usable, partial, unusable
    # Không dùng một điều kiện chung để chặn toàn bộ pipeline khi chỉ một metric không đủ dữ liệu.
    # usable: Tất cả 5 metrics đều đạt is_sufficient (>= 24 valid records).
    # partial: Ít nhất 1 metric đủ dữ liệu và ít nhất 1 thuật toán chạy được, nhưng chưa đạt toàn bộ 5 metrics.
    # unusable: Không có bất kỳ metric nào có dữ liệu hợp lệ hoặc không thuật toán nào khả thi.
    sufficient_metrics = [
        m for m in ALL_METRICS
        if m in summaries and summaries[m].is_sufficient
    ]
    has_any_valid_metrics = any(s.valid_records > 0 for s in summaries.values())
    can_run_any_algo = any(algorithm_fitness.values())

    if not has_any_valid_metrics or not can_run_any_algo or len(sufficient_metrics) == 0:
        status = "unusable"
    elif len(sufficient_metrics) == len(ALL_METRICS):
        status = "usable"
    else:
        status = "partial"

    is_usable = (status != "unusable")

    report = QualityReport(
        is_usable=is_usable,
        total_rows=total_rows,
        metrics_summary=summaries,
        issues_detected=issues,
        algorithm_fitness=algorithm_fitness,
        status=status,
    )

    log.info(
        "Hoàn tất kiểm tra chất lượng dữ liệu: status=%s, usable=%s, tổng dòng=%d, vấn đề phát hiện=%d",
        report.status,
        report.is_usable,
        report.total_rows,
        len(report.issues_detected),
    )
    return report
