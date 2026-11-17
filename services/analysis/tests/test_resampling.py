"""Kiểm thử tổng hợp chuỗi thời gian (Resampling) toàn diện."""

from datetime import datetime, timezone
import numpy as np
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
    assert bucket_ts.weekday() == 0  # 0 = Monday


def test_resampling_day_boundary():
    # 2026-11-01 16:59:00 UTC = 2026-11-01 23:59:00 VN (Ngày 1)
    # 2026-11-01 17:01:00 UTC = 2026-11-02 00:01:00 VN (Ngày 2)
    df = pd.DataFrame([
        {"ts": datetime(2026, 11, 1, 16, 59, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 10.0},
        {"ts": datetime(2026, 11, 1, 17, 1, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 20.0},
    ])
    records = compute_resampling_records(df)
    day_records = sorted([r for r in records if r["granularity"] == "day"], key=lambda x: x["ts"])
    assert len(day_records) == 2
    assert day_records[0]["mean"] == 10.0
    assert day_records[0]["ts"].day == 1
    assert day_records[1]["mean"] == 20.0
    assert day_records[1]["ts"].day == 2


def test_resampling_week_boundary():
    # 2026-11-15 là Chủ Nhật (Sunday). Đầu tuần của nó là Thứ Hai 2026-11-09.
    # 2026-11-16 là Thứ Hai (Monday). Đầu tuần của nó là Thứ Hai 2026-11-16.
    # 15:00 UTC = 22:00 VN
    sun_ts = datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc)
    mon_ts = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)
    df = pd.DataFrame([
        {"ts": sun_ts, "metric": "http_traffic", "value": 100.0},
        {"ts": mon_ts, "metric": "http_traffic", "value": 200.0},
    ])
    records = compute_resampling_records(df)
    week_records = sorted([r for r in records if r["granularity"] == "week"], key=lambda x: x["ts"])
    assert len(week_records) == 2
    assert week_records[0]["ts"].day == 9   # Tuần trước: 2026-11-09
    assert week_records[0]["mean"] == 100.0
    assert week_records[1]["ts"].day == 16  # Tuần mới: 2026-11-16
    assert week_records[1]["mean"] == 200.0


def test_resampling_month_boundary():
    # 2026-01-31 16:59 UTC = 2026-01-31 23:59 VN (Tháng 1)
    # 2026-01-31 17:01 UTC = 2026-02-01 00:01 VN (Tháng 2)
    df = pd.DataFrame([
        {"ts": datetime(2026, 1, 31, 16, 59, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 1.0},
        {"ts": datetime(2026, 1, 31, 17, 1, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 2.0},
    ])
    records = compute_resampling_records(df)
    month_records = sorted([r for r in records if r["granularity"] == "month"], key=lambda x: x["ts"])
    assert len(month_records) == 2
    assert month_records[0]["ts"].month == 1
    assert month_records[0]["mean"] == 1.0
    assert month_records[1]["ts"].month == 2
    assert month_records[1]["mean"] == 2.0


def test_resampling_no_artificial_missing_data():
    # Chỉ có dữ liệu cho tháng 1 và tháng 5 (thiếu tháng 2, 3, 4)
    df = pd.DataFrame([
        {"ts": datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 1.0},
        {"ts": datetime(2026, 5, 15, 0, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 2.0},
    ])
    records = compute_resampling_records(df)
    month_records = [r for r in records if r["granularity"] == "month"]
    assert len(month_records) == 2


def test_resampling_single_point():
    ts = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
    df = pd.DataFrame([{"ts": ts, "metric": "netflows", "value": 1.25}])
    records = compute_resampling_records(df)
    assert len(records) == 3  # 1 day, 1 week, 1 month
    for r in records:
        assert r["mean"] == 1.25
        assert r["min"] == 1.25
        assert r["max"] == 1.25
        assert r["metric"] == "netflows"


def test_resampling_constant_values():
    # 5 điểm có cùng giá trị 42.0
    base = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    rows = [{"ts": base + pd.Timedelta(hours=i), "metric": "http_traffic", "value": 42.0} for i in range(5)]
    df = pd.DataFrame(rows)
    records = compute_resampling_records(df)
    day_records = [r for r in records if r["granularity"] == "day"]
    assert len(day_records) == 1
    assert day_records[0]["mean"] == 42.0
    assert day_records[0]["min"] == 42.0
    assert day_records[0]["max"] == 42.0


def test_resampling_duplicate_timestamps():
    # Trùng mốc thời gian nhưng có giá trị khác nhau
    ts = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    df = pd.DataFrame([
        {"ts": ts, "metric": "http_traffic", "value": 10.0},
        {"ts": ts, "metric": "http_traffic", "value": 30.0},
    ])
    records = compute_resampling_records(df)
    day_records = [r for r in records if r["granularity"] == "day"]
    assert len(day_records) == 1
    assert day_records[0]["mean"] == 20.0
    assert day_records[0]["min"] == 10.0
    assert day_records[0]["max"] == 30.0


def test_resampling_values_greater_than_one():
    # Giá trị rescaled từ Cloudflare có thể vượt quá 1 (ví dụ 1.35)
    ts = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    df = pd.DataFrame([
        {"ts": ts, "metric": "http_traffic", "value": 1.35},
        {"ts": ts + pd.Timedelta(hours=1), "metric": "http_traffic", "value": 1.45},
    ])
    records = compute_resampling_records(df)
    day_records = [r for r in records if r["granularity"] == "day"]
    assert len(day_records) == 1
    assert abs(day_records[0]["mean"] - 1.40) < 1e-6
    assert day_records[0]["min"] == 1.35
    assert day_records[0]["max"] == 1.45


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
