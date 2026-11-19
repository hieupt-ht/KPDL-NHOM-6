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
    # Cung cấp 3 quan sát để đủ điều kiện quan sát tối thiểu (>= 3)
    ts1 = datetime(2026, 11, 1, 17, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 11, 1, 18, 0, 0, tzinfo=timezone.utc)
    ts3 = datetime(2026, 11, 1, 19, 0, 0, tzinfo=timezone.utc)
    df = pd.DataFrame([
        {"ts": ts1, "metric": "l7_attack", "value": 0.05},
        {"ts": ts2, "metric": "l7_attack", "value": 0.06},
        {"ts": ts3, "metric": "l7_attack", "value": 0.07},
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


def test_seasonal_two_records_insufficient():
    # 2 bản ghi vẫn chưa đủ MIN_SEASONAL_OBSERVATIONS (>= 3) -> trả về rỗng
    df = pd.DataFrame([
        {"ts": datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 1.0},
        {"ts": datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 2.0},
    ])
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

    # Kiểm tra cycle_details
    details = comp["http_traffic"]["cycle_details"]
    assert details["hour_of_day"]["cycle_complete"] is True
    assert details["hour_of_day"]["cycle_count"] == 1
    # 1 ngày chưa đủ để khẳng định tính mùa vụ lặp lại (confirmed = False)
    assert details["hour_of_day"]["confirmed"] is False
    assert details["day_of_week"]["confirmed"] is False
    assert details["month"]["confirmed"] is False
    assert details["month"]["limitation"] is not None


def test_seasonal_confirmed_with_two_full_cycles():
    from seasonal import check_seasonal_cycle_completeness

    # Tạo 48 giờ (2 ngày đầy đủ) -> hour_of_day có 24 buckets lặp lại 2 lần -> confirmed = True
    base = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(48):
        rows.append({
            "ts": base + pd.Timedelta(hours=i),
            "metric": "http_traffic",
            "value": 10.0 + float(i % 24),
        })
    df = pd.DataFrame(rows)
    comp = check_seasonal_cycle_completeness(df)
    hour_info = comp["http_traffic"]["cycle_details"]["hour_of_day"]
    assert hour_info["cycle_complete"] is True
    assert hour_info["cycle_count"] >= 2
    assert hour_info["min_repetitions"] >= 2
    assert hour_info["confirmed"] is True


def test_seasonal_dow_single_week_not_confirmed():
    from seasonal import check_seasonal_cycle_completeness

    # 7 ngày hourly = đúng 1 chu kỳ tuần: đủ 7 bucket nhưng chu kỳ chưa lặp lại -> confirmed = False
    base = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # Thứ Hai
    rows = [
        {"ts": base + pd.Timedelta(hours=h), "metric": "http_traffic", "value": 1.0}
        for h in range(7 * 24)
    ]
    comp = check_seasonal_cycle_completeness(pd.DataFrame(rows))
    dow_info = comp["http_traffic"]["cycle_details"]["day_of_week"]
    assert dow_info["cycle_complete"] is True
    assert dow_info["cycle_count"] == 1
    assert dow_info["min_repetitions"] == 1
    assert dow_info["confirmed"] is False


def test_seasonal_dow_two_weeks_confirmed():
    from seasonal import check_seasonal_cycle_completeness

    # 14 ngày hourly = 2 chu kỳ tuần: mỗi thứ xuất hiện trong 2 tuần ISO khác nhau -> confirmed = True
    base = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # Thứ Hai
    rows = [
        {"ts": base + pd.Timedelta(hours=h), "metric": "http_traffic", "value": 1.0}
        for h in range(14 * 24)
    ]
    comp = check_seasonal_cycle_completeness(pd.DataFrame(rows))
    dow_info = comp["http_traffic"]["cycle_details"]["day_of_week"]
    assert dow_info["cycle_complete"] is True
    assert dow_info["min_repetitions"] >= 2
    assert dow_info["confirmed"] is True


def test_seasonal_month_single_year_not_confirmed():
    from seasonal import check_seasonal_cycle_completeness

    # 12 điểm, mỗi tháng một điểm trong cùng năm 2025: đủ 12 bucket nhưng mỗi tháng
    # chỉ xuất hiện trong 1 năm -> chưa đủ 2 chu kỳ năm -> confirmed = False
    rows = []
    for m in range(12):
        rows.append({
            "ts": datetime(2025, m + 1, 15, 0, 0, tzinfo=timezone.utc),
            "metric": "http_traffic",
            "value": float(m),
        })
    comp = check_seasonal_cycle_completeness(pd.DataFrame(rows))
    month_info = comp["http_traffic"]["cycle_details"]["month"]
    assert month_info["cycle_complete"] is True
    assert month_info["cycle_count"] == 1
    assert month_info["min_repetitions"] == 1
    assert month_info["confirmed"] is False
    assert month_info["limitation"] is not None


def test_seasonal_month_two_years_confirmed():
    from seasonal import check_seasonal_cycle_completeness

    # 24 điểm, mỗi tháng một điểm trong 2 năm liên tiếp: mỗi tháng xuất hiện trong 2 năm -> confirmed = True
    rows = []
    for year in (2024, 2025):
        for m in range(12):
            rows.append({
                "ts": datetime(year, m + 1, 15, 0, 0, tzinfo=timezone.utc),
                "metric": "http_traffic",
                "value": float(m),
            })
    comp = check_seasonal_cycle_completeness(pd.DataFrame(rows))
    month_info = comp["http_traffic"]["cycle_details"]["month"]
    assert month_info["cycle_complete"] is True
    assert month_info["cycle_count"] == 2
    assert month_info["min_repetitions"] == 2
    assert month_info["confirmed"] is True
    assert month_info["limitation"] is None


def test_seasonal_empty_buckets_not_created():
    # 3 quan sát rơi vào giờ 10 và 11 (giờ VN)
    # 2026-11-01 03:00 UTC = 10:00 VN
    # 2026-11-01 04:00 UTC = 11:00 VN
    # 2026-11-02 03:00 UTC = 10:00 VN
    df = pd.DataFrame([
        {"ts": datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 1.0},
        {"ts": datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 2.0},
        {"ts": datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 3.0},
    ])
    records = compute_seasonal_records(df)
    hour_buckets = {r["bucket"] for r in records if r["period_type"] == "hour_of_day"}
    assert hour_buckets == {10, 11}
    assert 0 not in hour_buckets
    assert 23 not in hour_buckets
