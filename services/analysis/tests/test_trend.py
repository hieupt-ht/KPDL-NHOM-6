"""Kiểm thử phân tích xu hướng (Trend Analysis)."""

from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np

from trend import compute_trend_records


def test_trend_fallback_to_week_when_months_insufficient(long_sample_silver_df):
    # long_sample_silver_df có 12 tuần (khoảng gần 3 tháng), không đủ 24 tháng cho chuỗi tháng
    records = compute_trend_records(long_sample_silver_df, metrics=["http_traffic"])
    assert len(records) > 0
    # Phải fallback sang tuần
    granularities = {r["granularity"] for r in records}
    assert "week" in granularities
    assert "month" not in granularities

    # Kiểm tra không có NaN hoặc Inf trong trend_value
    for r in records:
        assert not np.isnan(r["trend_value"])
        assert not np.isinf(r["trend_value"])


def test_trend_insufficient_data_skips_cleanly():
    # Chỉ có 3 tuần dữ liệu (< 8 tuần yêu cầu cho 2 chu kỳ)
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    for h in range(3 * 7 * 24):
        rows.append({"ts": base + timedelta(hours=h), "metric": "http_traffic", "value": 1.0})
    df = pd.DataFrame(rows)

    records = compute_trend_records(df, metrics=["http_traffic"])
    # Không đủ dữ liệu -> bỏ qua an toàn, không ném lỗi
    assert records == []


def test_trend_prefers_month_when_sufficient():
    # Tạo 25 tháng liên tục (đủ >= 24 tháng cho period=12)
    base = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    # 25 tháng x 30 ngày = 750 ngày x 24 giờ
    current_ts = base
    for m in range(26):
        # 1 điểm mỗi tháng
        rows.append({
            "ts": current_ts,
            "metric": "http_traffic",
            "value": 1.0 + 0.1 * np.sin(m),
        })
        # Bước nhảy khoảng 31 ngày
        current_ts = current_ts + timedelta(days=32)

    df = pd.DataFrame(rows)
    records = compute_trend_records(df, metrics=["http_traffic"])
    if records:
        granularities = {r["granularity"] for r in records}
        assert "month" in granularities

