"""Kiểm thử phân tích tính mùa vụ (Seasonal Analysis) toàn diện."""

from datetime import datetime, timezone
import pandas as pd

from seasonal import compute_seasonal_records


def test_seasonal_hour_of_day_and_day_of_week(sample_silver_df):
    records = compute_seasonal_records(sample_silver_df)
    assert len(records) > 0

    period_types = {r["period_type"] for r in records}
    assert "hour_of_day" in period_types
    assert "day_of_week" in period_types

    for r in records:
        if r["period_type"] == "hour_of_day":
            assert 0 <= r["bucket"] <= 23
        elif r["period_type"] == "day_of_week":
            assert 0 <= r["bucket"] <= 6
        elif r["period_type"] == "month":
            assert 1 <= r["bucket"] <= 12

        assert isinstance(r["value"], float)


def test_seasonal_exact_mean_calculation():
    # 3 quan sát cùng rơi vào giờ 15:00 VN (08:00 UTC) vào các ngày khác nhau
    df = pd.DataFrame([
        {"ts": datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 10.0},
        {"ts": datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 20.0},
        {"ts": datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 30.0},
    ])
    records = compute_seasonal_records(df)
    hour_15 = [r for r in records if r["period_type"] == "hour_of_day" and r["bucket"] == 15]
    assert len(hour_15) == 1
    assert hour_15[0]["value"] == 20.0


def test_seasonal_timezone_bucket_mapping():
    # 2026-11-01 17:00:00 UTC = 2026-11-02 00:00:00 VN (Thứ Hai, ngày 2 tháng 11)
    # Cung cấp 2 quan sát để đủ điều kiện quan sát tối thiểu (>= 2)
    ts1 = datetime(2026, 11, 1, 17, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 11, 1, 18, 0, 0, tzinfo=timezone.utc)
    df = pd.DataFrame([
        {"ts": ts1, "metric": "l7_attack", "value": 0.05},
        {"ts": ts2, "metric": "l7_attack", "value": 0.06},
    ])
    records = compute_seasonal_records(df)

    hour_recs = {r["bucket"] for r in records if r["period_type"] == "hour_of_day"}
    assert 0 in hour_recs  # 00:00 giờ VN

    dow_rec = next(r for r in records if r["period_type"] == "day_of_week")
    assert dow_rec["bucket"] == 0   # Thứ Hai giờ VN (dayofweek = 0)

    month_rec = next(r for r in records if r["period_type"] == "month")
    assert month_rec["bucket"] == 11  # Tháng 11


def test_seasonal_single_record():
    # 1 bản ghi đơn lẻ không đủ để kết luận tính mùa vụ -> an toàn trả về rỗng
    ts = datetime(2026, 7, 10, 3, 0, tzinfo=timezone.utc)
    df = pd.DataFrame([{"ts": ts, "metric": "bot_share", "value": 45.0}])
    records = compute_seasonal_records(df)
    assert len(records) == 0


def test_seasonal_cycle_completeness_checker(sample_silver_df):
    from seasonal import check_seasonal_cycle_completeness

    comp = check_seasonal_cycle_completeness(sample_silver_df)
    # sample_silver_df có đủ 24 giờ cho 5 metrics
    assert "http_traffic" in comp
    assert comp["http_traffic"]["hour_of_day"] is True
    # Nhưng chỉ có 1 ngày nên day_of_week và month chưa đủ chu kỳ (False)
    assert comp["http_traffic"]["day_of_week"] is False
    assert comp["http_traffic"]["month"] is False


def test_seasonal_empty_buckets_not_created():
    # Chỉ có dữ liệu cho giờ 10 và 11 (giờ VN)
    # 2026-11-01 03:00 UTC = 10:00 VN
    # 2026-11-01 04:00 UTC = 11:00 VN
    df = pd.DataFrame([
        {"ts": datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 1.0},
        {"ts": datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 2.0},
    ])
    records = compute_seasonal_records(df)
    hour_buckets = {r["bucket"] for r in records if r["period_type"] == "hour_of_day"}
    assert hour_buckets == {10, 11}
    assert 0 not in hour_buckets
    assert 23 not in hour_buckets
