"""Kiểm thử tổng hợp chuỗi thời gian (Resampling)."""

from datetime import datetime, timezone
import pandas as pd

from resampling import compute_resampling_records


def test_empty_dataframe_resampling():
    records = compute_resampling_records(pd.DataFrame())
    assert records == []


def test_resampling_aggregation_accuracy():
    # 3 điểm trong cùng một ngày theo giờ VN
    # 2026-11-01 02:00 UTC = 2026-11-01 09:00 VN
    # 2026-11-01 04:00 UTC = 2026-11-01 11:00 VN
    # 2026-11-01 06:00 UTC = 2026-11-01 13:00 VN
    df = pd.DataFrame([
        {"ts": datetime(2026, 11, 1, 2, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 10.0},
        {"ts": datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 20.0},
        {"ts": datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 30.0},
    ])
    records = compute_resampling_records(df)
    assert len(records) > 0

    day_records = [r for r in records if r["granularity"] == "day"]
    assert len(day_records) == 1
    rec = day_records[0]
    assert rec["mean"] == 20.0
    assert rec["min"] == 10.0
    assert rec["max"] == 30.0
    assert rec["metric"] == "http_traffic"


def test_resampling_week_starts_monday():
    # 2026-11-18 là Thứ Tư (Wednesday). Thứ Hai đầu tuần là 2026-11-16.
    ts = datetime(2026, 11, 18, 5, 0, tzinfo=timezone.utc)
    df = pd.DataFrame([{"ts": ts, "metric": "http_traffic", "value": 5.0}])
    records = compute_resampling_records(df)

    week_records = [r for r in records if r["granularity"] == "week"]
    assert len(week_records) == 1
    bucket_ts = week_records[0]["ts"]
    # Kiểm tra bucket_ts là Thứ Hai
    assert bucket_ts.weekday() == 0  # 0 = Monday


def test_resampling_no_artificial_missing_data():
    # Chỉ có dữ liệu cho tháng 1 và tháng 5 (thiếu tháng 2, 3, 4)
    df = pd.DataFrame([
        {"ts": datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 1.0},
        {"ts": datetime(2026, 5, 15, 0, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 2.0},
    ])
    records = compute_resampling_records(df)
    month_records = [r for r in records if r["granularity"] == "month"]
    # Không được tự tạo bucket cho tháng 2, 3, 4
    assert len(month_records) == 2


def test_resampling_filters_nan_and_inf():
    df = pd.DataFrame([
        {"ts": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 10.0},
        {"ts": datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": float("nan")},
        {"ts": datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": float("inf")},
    ])
    records = compute_resampling_records(df)
    day_records = [r for r in records if r["granularity"] == "day"]
    assert len(day_records) == 1
    assert day_records[0]["mean"] == 10.0

