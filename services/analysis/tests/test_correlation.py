"""Kiểm thử tính tương quan Pearson (Correlation Analysis)."""

from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd

from correlation import compute_correlation_records, compute_pearson_r


def test_pearson_r_bounds_and_accuracy():
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([2.0, 4.0, 6.0, 8.0, 10.0])  # Tương quan hoàn hảo r = 1.0
    r = compute_pearson_r(x, y)
    assert r is not None
    assert abs(r - 1.0) < 1e-6

    y_neg = np.array([10.0, 8.0, 6.0, 4.0, 2.0])  # Tương quan nghịch r = -1.0
    r_neg = compute_pearson_r(x, y_neg)
    assert r_neg is not None
    assert abs(r_neg - (-1.0)) < 1e-6


def test_pearson_zero_variance():
    x = np.array([3.0, 3.0, 3.0, 3.0])  # Zero variance
    y = np.array([1.0, 2.0, 3.0, 4.0])
    r = compute_pearson_r(x, y)
    # Không xác định, phải trả về None, không được thay bằng 0.0
    assert r is None


def test_correlation_matrix_symmetry_and_self(sample_silver_df):
    records = compute_correlation_records(sample_silver_df)
    assert len(records) > 0

    # Chuyển thành dict tra cứu (var_x, var_y) -> coef
    corr_map = {(r["var_x"], r["var_y"]): r["coef"] for r in records}

    # Kiểm tra tự tương quan bằng 1.0
    for var in ("http_traffic", "l7_attack", "bot_share", "human_share", "netflows"):
        if (var, var) in corr_map:
            assert abs(corr_map[(var, var)] - 1.0) < 1e-6

    # Kiểm tra tính đối xứng r(x, y) == r(y, x)
    for (x, y), coef_xy in corr_map.items():
        if (y, x) in corr_map:
            assert abs(coef_xy - corr_map[(y, x)]) < 1e-6

    # Kiểm tra miền [-1, 1]
    for coef in corr_map.values():
        assert -1.0 <= coef <= 1.0


def test_correlation_pairwise_missing():
    # Biến A có 5 điểm, Biến B bị thiếu ở điểm 3 và 4
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = [
        {"ts": base + timedelta(hours=0), "metric": "http_traffic", "value": 1.0},
        {"ts": base + timedelta(hours=1), "metric": "http_traffic", "value": 2.0},
        {"ts": base + timedelta(hours=2), "metric": "http_traffic", "value": 3.0},
        {"ts": base + timedelta(hours=0), "metric": "l7_attack", "value": 2.0},
        {"ts": base + timedelta(hours=1), "metric": "l7_attack", "value": 4.0},
        # Điểm 2 thiếu l7_attack
    ]
    df = pd.DataFrame(rows)
    records = compute_correlation_records(df, variables=("http_traffic", "l7_attack"))
    corr_map = {(r["var_x"], r["var_y"]): r["coef"] for r in records}
    # Chỉ có 2 cặp quan sát đồng thời: (1, 2) và (2, 4) -> tương quan hoàn hảo r = 1.0
    assert ("http_traffic", "l7_attack") in corr_map
    assert abs(corr_map[("http_traffic", "l7_attack")] - 1.0) < 1e-6

