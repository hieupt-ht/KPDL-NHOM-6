"""Kiểm thử tính toán biểu đồ tần suất (Histogram)."""

import numpy as np
import pandas as pd

from histogram import compute_histogram_records, compute_metric_histogram


def test_histogram_20_bins_and_count_sum():
    np.random.seed(42)
    # 500 quan sát ngẫu nhiên với dải không cố định (từ 0.2 tới 1.35)
    values = np.random.uniform(0.2, 1.35, size=500)
    records = compute_metric_histogram("http_traffic", values, num_bins=20)

    assert len(records) == 20
    total_count = sum(r["count"] for r in records)
    assert total_count == 500

    # Kiểm tra bin_start < bin_end cho mọi bin
    for r in records:
        assert r["bin_start"] < r["bin_end"]
        assert r["count"] >= 0


def test_histogram_identical_values_edge_case():
    # Trường hợp 100 quan sát đều bằng 0.5
    values = np.full(100, 0.5)
    records = compute_metric_histogram("l7_attack", values, num_bins=20)

    assert len(records) == 20
    total_count = sum(r["count"] for r in records)
    assert total_count == 100

    # Kiểm tra các bin không bị trùng nhau (bin_start < bin_end)
    for r in records:
        assert r["bin_start"] < r["bin_end"]


def test_histogram_filters_nan_and_inf():
    values = np.array([0.1, 0.2, np.nan, 0.4, np.inf, 0.5, -np.inf])
    records = compute_metric_histogram("bot_share", values, num_bins=20)
    assert len(records) == 20
    total_count = sum(r["count"] for r in records)
    # Chỉ có 4 giá trị hợp lệ: 0.1, 0.2, 0.4, 0.5
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

