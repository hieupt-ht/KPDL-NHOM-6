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

log = logging.getLogger(__name__)


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


@dataclass
class QualityReport:
    """Báo cáo tổng hợp chất lượng toàn bộ dữ liệu Silver."""

    is_usable: bool
    total_rows: int
    metrics_summary: dict[str, MetricQualitySummary]
    issues_detected: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_usable": self.is_usable,
            "total_rows": self.total_rows,
            "issues": self.issues_detected,
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

        valid_mask = ~null_mask & ~inf_mask
        valid_df = group[valid_mask].sort_values("ts")
        valid_vals = valid_df["value"].to_numpy(dtype=float)
        summary.valid_records = len(valid_vals)

        if summary.null_or_nan_count > 0:
            issues.append(f"Metric '{metric_name}' có {summary.null_or_nan_count} giá trị NULL hoặc NaN.")
        if summary.inf_count > 0:
            issues.append(f"Metric '{metric_name}' có {summary.inf_count} giá trị Infinity.")

        # 3. Kiểm tra tính hợp lệ miền giá trị theo ngữ cảnh chỉ số
        if metric_name in ("bot_share", "human_share"):
            invalid_bounds = (valid_vals < 0.0) | (valid_vals > 100.0)
            summary.invalid_value_count = int(invalid_bounds.sum())
            if summary.invalid_value_count > 0:
                issues.append(f"Metric '{metric_name}' có {summary.invalid_value_count} giá trị ngoài miền [0, 100].")
        else:
            # http_traffic, l7_attack, netflows không được âm
            invalid_neg = valid_vals < 0.0
            summary.invalid_value_count = int(invalid_neg.sum())
            if summary.invalid_value_count > 0:
                issues.append(f"Metric '{metric_name}' có {summary.invalid_value_count} giá trị âm không hợp lệ.")

        # 4. Kiểm tra khoảng thời gian bị thiếu (gaps > 1h)
        if len(valid_df) >= 2:
            ts_series = valid_df["ts"].drop_duplicates()
            total_sec = (ts_series.max() - ts_series.min()).total_seconds()
            expected_hours = int(round(total_sec / 3600.0)) + 1
            actual_hours = len(ts_series)
            missing = max(0, expected_hours - actual_hours)
            summary.missing_hours_count = missing
            if missing > 0:
                log.info("Metric '%s' thiếu %d mốc giờ trong khoảng khảo sát.", metric_name, missing)

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
                anom_rows = valid_df[anomaly_mask].head(5)
                for _, r in anom_rows.iterrows():
                    # Phân biệt lỗi chất lượng với đột biến nghiệp vụ thực tế
                    is_domain_surge = (metric_name == "l7_attack" and r["value"] > med) or (
                        metric_name == "http_traffic" and r["value"] > med
                    )
                    category = "ATTACK_OR_TRAFFIC_SURGE" if is_domain_surge else "STATISTICAL_OUTLIER"
                    summary.anomaly_samples.append({
                        "ts": str(r["ts"]),
                        "value": float(r["value"]),
                        "category": category,
                    })

        summaries[str(metric_name)] = summary

    # Dữ liệu được xem là dùng được nếu có ít nhất 1 metric có quan sát hợp lệ
    is_usable = any(s.valid_records > 0 for s in summaries.values())

    report = QualityReport(
        is_usable=is_usable,
        total_rows=total_rows,
        metrics_summary=summaries,
        issues_detected=issues,
    )

    log.info(
        "Hoàn tất kiểm tra chất lượng dữ liệu: usable=%s, tổng dòng=%d, vấn đề phát hiện=%d",
        report.is_usable,
        report.total_rows,
        len(report.issues_detected),
    )
    return report

