"""Kiểm thử mô-đun Data Quality và Anomaly Detection."""

from datetime import datetime, timezone
import numpy as np
import pandas as pd

from quality import (
    detect_anomalies_iqr,
    detect_anomalies_robust_z,
    evaluate_data_quality,
)


def test_empty_dataframe_quality():
    report = evaluate_data_quality(pd.DataFrame())
    assert not report.is_usable
    assert report.total_rows == 0
    assert len(report.issues_detected) > 0


def test_quality_null_and_nan_detection():
    df = pd.DataFrame([
        {"ts": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 0.5},
        {"ts": datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": None},
        {"ts": datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": np.nan},
        {"ts": datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": np.inf},
    ])
    report = evaluate_data_quality(df)
    summary = report.metrics_summary["http_traffic"]
    assert summary.total_records == 4
    assert summary.valid_records == 1
    assert summary.null_or_nan_count == 2
    assert summary.inf_count == 1


def test_quality_duplicate_timestamps():
    ts = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    df = pd.DataFrame([
        {"ts": ts, "metric": "http_traffic", "value": 0.5},
        {"ts": ts, "metric": "http_traffic", "value": 0.6},
    ])
    report = evaluate_data_quality(df)
    summary = report.metrics_summary["http_traffic"]
    assert summary.duplicate_count == 2
    assert any("trùng lặp" in issue for issue in report.issues_detected)


def test_quality_invalid_bounds():
    df = pd.DataFrame([
        {"ts": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), "metric": "bot_share", "value": -5.0},
        {"ts": datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), "metric": "bot_share", "value": 105.0},
        {"ts": datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": -0.1},
    ])
    report = evaluate_data_quality(df)
    assert report.metrics_summary["bot_share"].invalid_value_count == 2
    assert report.metrics_summary["http_traffic"].invalid_value_count == 1


def test_robust_z_detection():
    # Chuỗi dữ liệu bình thường quanh 1.0, có 1 outlier cực lớn 100.0
    values = np.array([1.0, 1.02, 0.98, 1.01, 0.99, 1.0, 1.03, 0.97, 100.0])
    outliers, med, mad = detect_anomalies_robust_z(values, threshold=3.5)
    assert outliers[-1]
    assert np.sum(outliers) == 1
    assert abs(med - 1.0) < 0.05
    assert mad > 0


def test_robust_z_zero_mad():
    # Trường hợp tất cả giá trị giống hệt nhau
    values = np.array([2.0, 2.0, 2.0, 2.0, 2.0])
    outliers, med, mad = detect_anomalies_robust_z(values)
    assert not np.any(outliers)
    assert mad == 0.0


def test_iqr_detection():
    values = np.array([1.0, 2.0, 2.5, 3.0, 3.2, 3.5, 4.0, 50.0])
    outliers, iqr, lower, upper = detect_anomalies_iqr(values)
    assert outliers[-1]
    assert iqr > 0
    assert values[-1] > upper

