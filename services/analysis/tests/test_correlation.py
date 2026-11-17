"""Kiểm thử tính tương quan Pearson (Correlation Analysis) toàn diện."""

from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
from scipy.stats import pearsonr

from correlation import compute_correlation_records, compute_pearson_r


def test_pearson_r_bounds_and_accuracy():
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([2.0, 4.0, 6.0, 8.0, 10.0])  # r = 1.0
    r = compute_pearson_r(x, y)
    assert r is not None
    assert abs(r - 1.0) < 1e-6

    y_neg = np.array([10.0, 8.0, 6.0, 4.0, 2.0])  # r = -1.0
    r_neg = compute_pearson_r(x, y_neg)
    assert r_neg is not None
    assert abs(r_neg - (-1.0)) < 1e-6


def test_pearson_hand_calculated_general_case():
    x = np.array([1.0, 3.0, 4.0, 6.0, 7.0])
    y = np.array([2.0, 5.0, 5.0, 8.0, 9.0])
    r_computed = compute_pearson_r(x, y)
    r_scipy, _ = pearsonr(x, y)
    assert r_computed is not None
    assert abs(r_computed - r_scipy) < 1e-6


def test_pearson_zero_variance():
    x = np.array([3.0, 3.0, 3.0, 3.0])  # Zero variance
    y = np.array([1.0, 2.0, 3.0, 4.0])
    r = compute_pearson_r(x, y)
    # Không xác định, phải trả về None, không được thay bằng 0.0
    assert r is None


def test_pearson_single_observation():
    x = np.array([1.0])
    y = np.array([2.0])
    r = compute_pearson_r(x, y)
    assert r is None


def test_correlation_matrix_symmetry_and_self(sample_silver_df):
    records = compute_correlation_records(sample_silver_df)
    assert len(records) > 0

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
    # Biến A có 3 điểm, Biến B chỉ có ở điểm 0 và 1
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = [
        {"ts": base + timedelta(hours=0), "metric": "http_traffic", "value": 1.0},
        {"ts": base + timedelta(hours=1), "metric": "http_traffic", "value": 2.0},
        {"ts": base + timedelta(hours=2), "metric": "http_traffic", "value": 3.0},
        {"ts": base + timedelta(hours=0), "metric": "l7_attack", "value": 2.0},
        {"ts": base + timedelta(hours=1), "metric": "l7_attack", "value": 4.0},
    ]
    df = pd.DataFrame(rows)
    records = compute_correlation_records(df, variables=("http_traffic", "l7_attack"))
    corr_map = {(r["var_x"], r["var_y"]): r["coef"] for r in records}
    assert ("http_traffic", "l7_attack") in corr_map
    assert abs(corr_map[("http_traffic", "l7_attack")] - 1.0) < 1e-6


def test_correlation_disjoint_timestamps():
    # Hai metric có mốc thời gian hoàn toàn lệch nhau, không có điểm giao
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = [
        {"ts": base + timedelta(hours=0), "metric": "http_traffic", "value": 1.0},
        {"ts": base + timedelta(hours=1), "metric": "http_traffic", "value": 2.0},
        {"ts": base + timedelta(hours=10), "metric": "l7_attack", "value": 10.0},
        {"ts": base + timedelta(hours=11), "metric": "l7_attack", "value": 20.0},
    ]
    df = pd.DataFrame(rows)
    records = compute_correlation_records(df, variables=("http_traffic", "l7_attack"))
    # Cặp (http_traffic, l7_attack) không có điểm chung nên không được xuất hiện
    pair_keys = [(r["var_x"], r["var_y"]) for r in records]
    assert ("http_traffic", "l7_attack") not in pair_keys
    assert ("l7_attack", "http_traffic") not in pair_keys
    # Nhưng mỗi biến tự tương quan với chính nó thì vẫn tồn tại
    assert ("http_traffic", "http_traffic") in pair_keys
    assert ("l7_attack", "l7_attack") in pair_keys


def test_correlation_constant_series_skipped():
    # Một metric có giá trị không đổi (zero variance)
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    for h in range(5):
        ts = base + timedelta(hours=h)
        rows.append({"ts": ts, "metric": "http_traffic", "value": 5.0})  # constant
        rows.append({"ts": ts, "metric": "l7_attack", "value": float(h)})
    df = pd.DataFrame(rows)
    records = compute_correlation_records(df, variables=("http_traffic", "l7_attack"))
    pair_keys = [(r["var_x"], r["var_y"]) for r in records]
    # Cả tự tương quan của http_traffic và tương quan chéo đều bị loại bỏ an toàn
    assert ("http_traffic", "http_traffic") not in pair_keys
    assert ("http_traffic", "l7_attack") not in pair_keys
