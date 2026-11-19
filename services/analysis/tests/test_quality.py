"""Kiểm thử mô-đun Data Quality và Anomaly Detection toàn diện."""

from datetime import datetime, timedelta, timezone
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


def test_quality_unusable_when_all_null():
    df = pd.DataFrame([
        {"ts": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": None},
        {"ts": datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": np.nan},
        {"ts": datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": np.inf},
    ])
    report = evaluate_data_quality(df)
    assert not report.is_usable
    assert report.metrics_summary["http_traffic"].valid_records == 0


def test_distribution_exact_hand_calculated():
    # Tập số: [10.0, 20.0, 30.0, 40.0, 50.0]
    # mean = 30.0, median = 30.0, min = 10.0, max = 50.0
    # Q1 = 20.0, Q3 = 40.0 -> IQR = 20.0
    # |x - 30| = [20, 10, 0, 10, 20] -> median(|x - 30|) = 10.0 -> MAD = 10.0
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = [{"ts": base + timedelta(hours=i), "metric": "http_traffic", "value": float(v)}
            for i, v in enumerate([10.0, 20.0, 30.0, 40.0, 50.0])]
    df = pd.DataFrame(rows)
    report = evaluate_data_quality(df)
    s = report.metrics_summary["http_traffic"]

    assert s.valid_records == 5
    assert abs(s.mean_value - 30.0) < 1e-6
    assert abs(s.median_value - 30.0) < 1e-6
    assert abs(s.min_value - 10.0) < 1e-6
    assert abs(s.max_value - 50.0) < 1e-6
    assert abs(s.iqr_value - 20.0) < 1e-6
    assert abs(s.mad_value - 10.0) < 1e-6


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


def test_quality_hourly_gaps_calculation():
    # 00:00, 01:00, 05:00 -> từ 00:00 tới 05:00 cần 6 mốc giờ, thực tế có 3 -> thiếu 3 mốc
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    df = pd.DataFrame([
        {"ts": base + timedelta(hours=0), "metric": "http_traffic", "value": 1.0},
        {"ts": base + timedelta(hours=1), "metric": "http_traffic", "value": 2.0},
        {"ts": base + timedelta(hours=5), "metric": "http_traffic", "value": 3.0},
    ])
    report = evaluate_data_quality(df)
    assert report.metrics_summary["http_traffic"].missing_hours_count == 3


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


def test_immutability_of_source_dataframe():
    df = pd.DataFrame([
        {"ts": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 1.0},
        {"ts": datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": np.nan},
    ])
    df_copy = df.copy(deep=True)
    evaluate_data_quality(df)
    # df gốc không bị thay đổi cột hay giá trị
    pd.testing.assert_frame_equal(df, df_copy)


def test_quality_unusable_when_insufficient_records():
    # 10 records (< 24) -> is_usable phải là False, không coi đủ điều kiện chỉ vì có 1 vài bản ghi
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(10):
        for m in ("http_traffic", "l7_attack", "bot_share", "human_share", "netflows"):
            rows.append({"ts": base + timedelta(hours=i), "metric": m, "value": 1.0})
    df = pd.DataFrame(rows)
    report = evaluate_data_quality(df)
    assert not report.is_usable
    for m in ("http_traffic", "l7_attack", "bot_share", "human_share", "netflows"):
        assert not report.metrics_summary[m].is_sufficient


def test_anomaly_distinguishes_attack_surge_from_statistical_outlier():
    # http_traffic có đột biến lớn vượt Q3 + 3*IQR -> TRAFFIC_ANOMALY_CANDIDATE (không tự kết luận tấn công)
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    # 25 bản ghi bình thường quanh 1.0, bản ghi thứ 26 là 100.0 (đột biến lớn)
    for i in range(25):
        rows.append({"ts": base + timedelta(hours=i), "metric": "http_traffic", "value": 1.0 + 0.01 * i})
    rows.append({"ts": base + timedelta(hours=25), "metric": "http_traffic", "value": 100.0})

    df = pd.DataFrame(rows)
    report = evaluate_data_quality(df)
    summary = report.metrics_summary["http_traffic"]
    assert len(summary.anomaly_samples) > 0
    surge_sample = next((s for s in summary.anomaly_samples if s["value"] == 100.0), None)
    assert surge_sample is not None
    assert surge_sample["category"] == "TRAFFIC_ANOMALY_CANDIDATE"
    assert surge_sample["metric"] == "http_traffic"
    assert "detection_method" in surge_sample
    assert surge_sample["detection_method"] in ("ROBUST_Z", "IQR", "ROBUST_Z+IQR")


def test_anomaly_statistical_outlier_not_labeled_attack():
    # Outlier trên bot_share (tỷ lệ bot) chỉ được coi là biến động thống kê ngoại lai,
    # không được tự ý gán nhãn là cuộc tấn công mạng
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(25):
        rows.append({"ts": base + timedelta(hours=i), "metric": "bot_share", "value": 10.0 + 0.1 * i})
    rows.append({"ts": base + timedelta(hours=25), "metric": "bot_share", "value": 85.0})

    df = pd.DataFrame(rows)
    report = evaluate_data_quality(df)
    summary = report.metrics_summary["bot_share"]
    assert len(summary.anomaly_samples) > 0
    sample = next((s for s in summary.anomaly_samples if s["value"] == 85.0), None)
    assert sample is not None
    assert sample["category"] == "STATISTICAL_OUTLIER"
    assert sample["metric"] == "bot_share"
    assert sample["detection_method"] in ("ROBUST_Z", "IQR", "ROBUST_Z+IQR")


def test_quality_partial_status_when_one_metric_insufficient():
    # 4 metrics đủ điều kiện (>= 24 bản ghi), 1 metric (netflows) chỉ có 5 bản ghi (< 24)
    # -> status phải là 'partial', is_usable là True (không chặn toàn bộ pipeline)
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(25):
        ts = base + timedelta(hours=i)
        rows.append({"ts": ts, "metric": "http_traffic", "value": 1.0 + float(i)})
        rows.append({"ts": ts, "metric": "l7_attack", "value": 0.5})
        rows.append({"ts": ts, "metric": "bot_share", "value": 20.0})
        rows.append({"ts": ts, "metric": "human_share", "value": 80.0})
    for i in range(5):
        rows.append({"ts": base + timedelta(hours=i), "metric": "netflows", "value": 100.0})

    df = pd.DataFrame(rows)
    report = evaluate_data_quality(df)

    assert report.status == "partial"
    assert report.is_usable is True
    assert report.metrics_summary["http_traffic"].is_sufficient is True
    assert report.metrics_summary["netflows"].is_sufficient is False
    assert any("netflows" in issue for issue in report.issues_detected)


def test_quality_temporal_coverage_calculation():
    # 00:00, 01:00, 03:00 -> expected = 4 giờ, actual = 3 giờ -> coverage = 3/4 = 0.75
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    df = pd.DataFrame([
        {"ts": base + timedelta(hours=0), "metric": "http_traffic", "value": 1.0},
        {"ts": base + timedelta(hours=1), "metric": "http_traffic", "value": 2.0},
        {"ts": base + timedelta(hours=3), "metric": "http_traffic", "value": 3.0},
    ])
    report = evaluate_data_quality(df)
    s = report.metrics_summary["http_traffic"]
    assert s.missing_hours_count == 1
    assert s.temporal_coverage == 0.75


def test_algorithm_fitness_evaluation():
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    # 24 giờ cho 5 metrics: đủ resampling, seasonal, correlation; chưa đủ trend (cần >= 8 tuần)
    rows = []
    for i in range(24):
        ts = base + timedelta(hours=i)
        rows.append({"ts": ts, "metric": "http_traffic", "value": 1.0 + float(i % 5)})
        rows.append({"ts": ts, "metric": "l7_attack", "value": 0.5 + float(i % 3)})
        rows.append({"ts": ts, "metric": "bot_share", "value": 20.0})
        rows.append({"ts": ts, "metric": "human_share", "value": 80.0})
        rows.append({"ts": ts, "metric": "netflows", "value": 10.0 + float(i)})
    df = pd.DataFrame(rows)
    report = evaluate_data_quality(df)

    assert report.algorithm_fitness["resampling"] is True
    assert report.algorithm_fitness["histogram"] is True
    assert report.algorithm_fitness["seasonal"] is True
    assert report.algorithm_fitness["correlation"] is True
    assert report.algorithm_fitness["trend"] is False  # 24 giờ < 8 tuần -> False
