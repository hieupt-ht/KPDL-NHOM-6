"""Kiểm thử tính toán biểu đồ tần suất (Histogram) toàn diện."""

import numpy as np
import pandas as pd

from histogram import compute_histogram_records, compute_metric_histogram


def test_histogram_20_bins_and_count_sum():
    np.random.seed(42)
    values = np.random.uniform(0.2, 1.35, size=500)
    records = compute_metric_histogram("http_traffic", values, num_bins=20)

    assert len(records) == 20
    total_count = sum(r["count"] for r in records)
    assert total_count == 500

    for r in records:
        assert r["bin_start"] < r["bin_end"]
        assert r["count"] >= 0


def test_histogram_exact_distribution_known_values():
    # 10 giá trị tăng dần đều từ 0.1 đến 1.0
    values = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    records = compute_metric_histogram("l7_attack", values, num_bins=20)

    assert len(records) == 20
    assert sum(r["count"] for r in records) == 10
    # Cạnh đầu tiên là 0.1, cạnh cuối cùng là 1.0
    assert abs(records[0]["bin_start"] - 0.1) < 1e-6
    assert abs(records[-1]["bin_end"] - 1.0) < 1e-6


def test_histogram_identical_values_edge_case():
    # Trường hợp 100 quan sát đều bằng 0.5
    values = np.full(100, 0.5)
    records = compute_metric_histogram("l7_attack", values, num_bins=20)

    assert len(records) == 20
    total_count = sum(r["count"] for r in records)
    assert total_count == 100

    for r in records:
        assert r["bin_start"] < r["bin_end"]

    # Đảm bảo duy nhất 1 bin chứa toàn bộ 100 count
    counts = [r["count"] for r in records]
    assert 100 in counts
    assert counts.count(0) == 19


def test_histogram_single_observation():
    # Chỉ có duy nhất 1 quan sát
    values = np.array([0.75])
    records = compute_metric_histogram("http_traffic", values, num_bins=20)

    assert len(records) == 20
    assert sum(r["count"] for r in records) == 1
    counts = [r["count"] for r in records]
    assert 1 in counts
    assert counts.count(0) == 19


def test_histogram_values_above_one():
    # Radar sau khi rescale có thể vượt 1 (ví dụ 1.2 tới 1.5)
    values = np.array([1.2, 1.25, 1.3, 1.35, 1.4, 1.45, 1.5])
    records = compute_metric_histogram("http_traffic", values, num_bins=20)

    assert len(records) == 20
    assert sum(r["count"] for r in records) == 7
    assert abs(records[0]["bin_start"] - 1.2) < 1e-6
    assert abs(records[-1]["bin_end"] - 1.5) < 1e-6


def test_histogram_large_outlier():
    # 50 điểm quanh 1.0 và 1 điểm outlier cực lớn 100.0
    values = np.concatenate([np.ones(50), [100.0]])
    records = compute_metric_histogram("l7_attack", values, num_bins=20)

    assert len(records) == 20
    assert sum(r["count"] for r in records) == 51
    assert abs(records[-1]["bin_end"] - 100.0) < 1e-6


def test_histogram_filters_nan_and_inf():
    values = np.array([0.1, 0.2, np.nan, 0.4, np.inf, 0.5, -np.inf])
    records = compute_metric_histogram("bot_share", values, num_bins=20)
    assert len(records) == 20
    total_count = sum(r["count"] for r in records)
    assert total_count == 4


def test_histogram_empty_input():
    records = compute_metric_histogram("http_traffic", np.array([]), num_bins=20)
    assert records == []


def test_compute_histogram_records_dataframe():
    df = pd.DataFrame([
        {"metric": "http_traffic", "value": 0.5},
        {"metric": "http_traffic", "value": 0.8},
        {"metric": "l7_attack", "value": 0.1},
        {"metric": "l7_attack", "value": 0.2},
        {"metric": "bot_share", "value": 30.0},
        {"metric": "human_share", "value": 70.0},  # Không thuộc 3 metric histogram
    ])
    records = compute_histogram_records(df)
    metrics_present = {r["metric"] for r in records}
    assert metrics_present == {"http_traffic", "l7_attack", "bot_share"}
    assert "human_share" not in metrics_present
