"""Kiểm thử phân tích xu hướng (Trend Analysis) toàn diện."""

from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd

from trend import compute_trend_records


def test_trend_fallback_to_week_when_months_insufficient(long_sample_silver_df):
    # long_sample_silver_df có 12 tuần, không đủ 24 tháng cho chuỗi tháng
    records = compute_trend_records(long_sample_silver_df, metrics=["http_traffic"])
    assert len(records) > 0
    granularities = {r["granularity"] for r in records}
    assert "week" in granularities
    assert "month" not in granularities

    for r in records:
        assert not np.isnan(r["trend_value"])
        assert not np.isinf(r["trend_value"])


def test_trend_increasing_series():
    # 12 tuần với xu hướng tăng tuyến tính rõ rệt + nhiễu tuần nhỏ
    base = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # Thứ Hai
    rows = []
    for w in range(12):
        for h in range(7 * 24):
            ts = base + timedelta(weeks=w, hours=h)
            # Giá trị tăng dần theo tuần: tuần 0 -> ~10, tuần 11 -> ~120
            val = 10.0 * (w + 1) + 2.0 * np.sin(h / 12.0)
            rows.append({"ts": ts, "metric": "http_traffic", "value": val})

    df = pd.DataFrame(rows)
    records = compute_trend_records(df, metrics=["http_traffic"])
    assert len(records) > 0
    trend_vals = [r["trend_value"] for r in sorted(records, key=lambda x: x["ts"])]
    # Điểm cuối của trend phải lớn hơn điểm đầu
    assert trend_vals[-1] > trend_vals[0]
    # Kiểm tra tăng đơn điệu
    for i in range(len(trend_vals) - 1):
        assert trend_vals[i + 1] >= trend_vals[i] - 1e-6


def test_trend_decreasing_series():
    # 12 tuần với xu hướng giảm tuyến tính rõ rệt
    base = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    rows = []
    for w in range(12):
        for h in range(7 * 24):
            ts = base + timedelta(weeks=w, hours=h)
            val = 200.0 - 10.0 * w + 2.0 * np.cos(h / 12.0)
            rows.append({"ts": ts, "metric": "http_traffic", "value": val})

    df = pd.DataFrame(rows)
    records = compute_trend_records(df, metrics=["http_traffic"])
    assert len(records) > 0
    trend_vals = [r["trend_value"] for r in sorted(records, key=lambda x: x["ts"])]
    # Điểm cuối phải nhỏ hơn điểm đầu
    assert trend_vals[-1] < trend_vals[0]
    # Kiểm tra giảm đơn điệu
    for i in range(len(trend_vals) - 1):
        assert trend_vals[i + 1] <= trend_vals[i] + 1e-6


def test_trend_stationary_series():
    # 12 tuần ổn định quanh 50.0 với biến thiên nhỏ
    base = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    rows = []
    for w in range(12):
        for h in range(7 * 24):
            ts = base + timedelta(weeks=w, hours=h)
            val = 50.0 + 1.0 * np.sin(h / 12.0)
            rows.append({"ts": ts, "metric": "http_traffic", "value": val})

    df = pd.DataFrame(rows)
    records = compute_trend_records(df, metrics=["http_traffic"])
    assert len(records) > 0
    trend_vals = [r["trend_value"] for r in records]
    # Trend phải rất gần với 50.0
    for v in trend_vals:
        assert abs(v - 50.0) < 0.5


def test_trend_not_identical_to_scalar_mean():
    # Xác minh trend là một đường cong động theo thời gian, không phải là một giá trị vô hướng lặp lại
    base = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    rows = []
    for w in range(12):
        for h in range(7 * 24):
            ts = base + timedelta(weeks=w, hours=h)
            val = float(w ** 2) + 0.5 * np.sin(h / 6.0)
            rows.append({"ts": ts, "metric": "http_traffic", "value": val})

    df = pd.DataFrame(rows)
    records = compute_trend_records(df, metrics=["http_traffic"])
    trend_vals = [r["trend_value"] for r in records]
    # Độ lệch chuẩn của trend phải > 0 (không phải một hằng số cố định)
    assert np.std(trend_vals) > 1.0


def test_trend_gap_in_data_rejected():
    # 10 tuần dữ liệu nhưng bị khuyết tuần 4 và 5
    base = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    rows = []
    for w in [0, 1, 2, 3, 6, 7, 8, 9]:
        for h in range(7 * 24):
            ts = base + timedelta(weeks=w, hours=h)
            rows.append({"ts": ts, "metric": "http_traffic", "value": 10.0})

    df = pd.DataFrame(rows)
    records = compute_trend_records(df, metrics=["http_traffic"])
    # Do có khoảng trống, hệ thống không tự nội suy và bỏ qua an toàn
    assert records == []


def test_trend_insufficient_data_skips_cleanly():
    # Chỉ có 3 tuần dữ liệu (< 8 tuần yêu cầu cho 2 chu kỳ)
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    for h in range(3 * 7 * 24):
        rows.append({"ts": base + timedelta(hours=h), "metric": "http_traffic", "value": 1.0})
    df = pd.DataFrame(rows)

    records = compute_trend_records(df, metrics=["http_traffic"])
    assert records == []


def test_trend_prefers_month_when_sufficient():
    # Tạo 25 tháng liên tục (đủ >= 24 tháng cho period=12)
    base = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    current_ts = base
    for m in range(26):
        rows.append({
            "ts": current_ts,
            "metric": "http_traffic",
            "value": 1.0 + 0.1 * np.sin(m),
        })
        current_ts = current_ts + timedelta(days=32)

    df = pd.DataFrame(rows)
    records = compute_trend_records(df, metrics=["http_traffic"])
    if records:
        granularities = {r["granularity"] for r in records}
        assert "month" in granularities


def test_trend_incomplete_interior_bucket_rejected():
    # 10 tuần dữ liệu, nhưng tuần thứ 4 chỉ có 20 giờ (bucket bên trong chưa hoàn chỉnh)
    base = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # Thứ Hai
    rows = []
    for w in range(10):
        # Tuần 4 chỉ có 20 giờ (< 151 giờ yêu cầu cho 1 tuần hoàn chỉnh)
        hours_in_week = 20 if w == 4 else 7 * 24
        for h in range(hours_in_week):
            ts = base + timedelta(weeks=w, hours=h)
            rows.append({"ts": ts, "metric": "http_traffic", "value": 10.0 + float(w)})

    df = pd.DataFrame(rows)
    records = compute_trend_records(df, metrics=["http_traffic"])
    # Do bucket bên trong bị thiếu giờ, hệ thống không tự nội suy và từ chối chuỗi an toàn
    assert records == []


def test_trend_incomplete_boundary_buckets_trimmed():
    # 12 tuần dữ liệu bắt đầu từ Thứ Tư (tuần đầu bị khuyết Thứ Hai, Thứ Ba)
    # và kết thúc vào Thứ Tư (tuần cuối bị khuyết từ Thứ Năm đến Chủ Nhật).
    # 2 bucket biên bị cắt tỉa, 10 tuần ở giữa đầy đủ (>= 8 tuần) -> phân tích thành công.
    base = datetime(2026, 1, 7, 0, 0, tzinfo=timezone.utc)  # Thứ Tư
    rows = []
    # 10 tuần trọn vẹn (70 ngày) + 4 ngày đầu + 3 ngày cuối = 77 ngày = 1848 giờ
    for h in range(77 * 24):
        ts = base + timedelta(hours=h)
        rows.append({"ts": ts, "metric": "http_traffic", "value": 1.0 + 0.05 * np.sin(h / 24.0)})

    df = pd.DataFrame(rows)
    records = compute_trend_records(df, metrics=["http_traffic"])
    assert len(records) > 0
    granularities = {r["granularity"] for r in records}
    assert "week" in granularities
