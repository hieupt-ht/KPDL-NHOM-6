"""Kiểm thử phân tích mẫu hình theo thời gian (Temporal Pattern Analysis) toàn diện."""

from datetime import datetime, timezone
import pandas as pd

from temporal_patterns import (
    assess_temporal_cycle_completeness,
    compute_temporal_pattern_records,
)


def test_temporal_pattern_hour_of_day_and_day_of_week(sample_silver_df):
    records = compute_temporal_pattern_records(sample_silver_df)
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


def test_temporal_pattern_exact_mean_calculation():
    # 3 quan sát cùng rơi vào giờ 15:00 VN (08:00 UTC) vào các ngày khác nhau
    df = pd.DataFrame([
        {"ts": datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 10.0},
        {"ts": datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 20.0},
        {"ts": datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 30.0},
    ])
    records = compute_temporal_pattern_records(df)
    hour_15 = [r for r in records if r["period_type"] == "hour_of_day" and r["bucket"] == 15]
    assert len(hour_15) == 1
    assert hour_15[0]["value"] == 20.0


def test_temporal_pattern_timezone_bucket_mapping():
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
    records = compute_temporal_pattern_records(df)

    hour_recs = {r["bucket"] for r in records if r["period_type"] == "hour_of_day"}
    assert 0 in hour_recs  # 00:00 giờ VN

    dow_rec = next(r for r in records if r["period_type"] == "day_of_week")
    assert dow_rec["bucket"] == 0   # Thứ Hai giờ VN (dayofweek = 0)

    month_rec = next(r for r in records if r["period_type"] == "month")
    assert month_rec["bucket"] == 11  # Tháng 11


def test_temporal_pattern_single_record():
    # 1 bản ghi đơn lẻ không đủ để tính mẫu hình theo bucket -> an toàn trả về rỗng
    ts = datetime(2026, 7, 10, 3, 0, tzinfo=timezone.utc)
    df = pd.DataFrame([{"ts": ts, "metric": "bot_share", "value": 45.0}])
    records = compute_temporal_pattern_records(df)
    assert len(records) == 0


def test_temporal_pattern_two_records_insufficient():
    # 2 bản ghi vẫn chưa đủ MIN_TEMPORAL_PATTERN_OBSERVATIONS (>= 3) -> trả về rỗng
    df = pd.DataFrame([
        {"ts": datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 1.0},
        {"ts": datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 2.0},
    ])
    records = compute_temporal_pattern_records(df)
    assert len(records) == 0


def test_temporal_pattern_cycle_assessment_single_day(sample_silver_df):
    """Dữ liệu 24 giờ trải 2 ngày VN: đủ 24 bucket giờ nhưng mỗi giờ chỉ ở 1 ngày
    -> hour_of_day cycle_complete=True nhưng confirmed=False (chưa lặp lại)."""
    comp = assess_temporal_cycle_completeness(sample_silver_df)
    assert "http_traffic" in comp
    assert comp["http_traffic"]["hour_of_day"] is True
    # day_of_week và month chưa đủ bucket -> False
    assert comp["http_traffic"]["day_of_week"] is False
    assert comp["http_traffic"]["month"] is False

    details = comp["http_traffic"]["cycle_details"]
    assert details["hour_of_day"]["cycle_complete"] is True
    # cycle_count = số NGÀY VN khác nhau có quan sát (2), không phải len/24
    assert details["hour_of_day"]["cycle_count"] == 2
    assert details["hour_of_day"]["min_repetitions"] == 1
    assert details["hour_of_day"]["confirmed"] is False
    assert details["day_of_week"]["confirmed"] is False
    assert details["month"]["confirmed"] is False
    assert details["month"]["limitation"] is not None


def test_temporal_pattern_hour_confirmed_with_two_days():
    """48 giờ (2 ngày UTC -> 3 ngày VN) -> mỗi giờ xuất hiện ở >= 2 ngày -> confirmed."""
    base = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(48):
        rows.append({
            "ts": base + pd.Timedelta(hours=i),
            "metric": "http_traffic",
            "value": 10.0 + float(i % 24),
        })
    df = pd.DataFrame(rows)
    comp = assess_temporal_cycle_completeness(df)
    hour_info = comp["http_traffic"]["cycle_details"]["hour_of_day"]
    assert hour_info["cycle_complete"] is True
    assert hour_info["cycle_count"] >= 2
    assert hour_info["min_repetitions"] >= 2
    assert hour_info["confirmed"] is True


def test_temporal_pattern_dow_single_week_not_confirmed():
    """7 ngày hourly: đủ 7 bucket thứ nhưng phần lớn thứ chỉ ở 1 tuần ISO -> confirmed=False.

    Lưu ý: 168 giờ từ Thứ Hai 00:00 UTC = 07:00 VN tràn sang rạng sáng Thứ Hai
    tuần ISO kế tiếp, nên cycle_count (số tuần ISO distinct) = 2 chứ không phải 1.
    """
    base = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # Thứ Hai
    rows = [
        {"ts": base + pd.Timedelta(hours=h), "metric": "http_traffic", "value": 1.0}
        for h in range(7 * 24)
    ]
    comp = assess_temporal_cycle_completeness(pd.DataFrame(rows))
    dow_info = comp["http_traffic"]["cycle_details"]["day_of_week"]
    assert dow_info["cycle_complete"] is True
    assert dow_info["cycle_count"] == 2
    assert dow_info["min_repetitions"] == 1
    assert dow_info["confirmed"] is False


def test_temporal_pattern_dow_two_weeks_confirmed():
    """14 ngày hourly: mỗi thứ xuất hiện trong >= 2 tuần ISO khác nhau -> confirmed=True."""
    base = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # Thứ Hai
    rows = [
        {"ts": base + pd.Timedelta(hours=h), "metric": "http_traffic", "value": 1.0}
        for h in range(14 * 24)
    ]
    comp = assess_temporal_cycle_completeness(pd.DataFrame(rows))
    dow_info = comp["http_traffic"]["cycle_details"]["day_of_week"]
    assert dow_info["cycle_complete"] is True
    assert dow_info["min_repetitions"] >= 2
    assert dow_info["confirmed"] is True


def test_temporal_pattern_month_single_year_not_confirmed():
    """12 điểm, mỗi tháng một điểm trong cùng năm 2025: đủ 12 bucket nhưng mỗi tháng
    chỉ xuất hiện trong 1 năm -> chưa đủ 2 chu kỳ năm -> confirmed = False"""
    rows = []
    for m in range(12):
        rows.append({
            "ts": datetime(2025, m + 1, 15, 0, 0, tzinfo=timezone.utc),
            "metric": "http_traffic",
            "value": float(m),
        })
    comp = assess_temporal_cycle_completeness(pd.DataFrame(rows))
    month_info = comp["http_traffic"]["cycle_details"]["month"]
    assert month_info["cycle_complete"] is True
    assert month_info["cycle_count"] == 1
    assert month_info["min_repetitions"] == 1
    assert month_info["confirmed"] is False
    assert month_info["limitation"] is not None


def test_temporal_pattern_month_two_years_confirmed():
    """24 điểm, mỗi tháng một điểm trong 2 năm liên tiếp: mỗi tháng xuất hiện trong
    2 năm -> confirmed = True"""
    rows = []
    for year in (2024, 2025):
        for m in range(12):
            rows.append({
                "ts": datetime(year, m + 1, 15, 0, 0, tzinfo=timezone.utc),
                "metric": "http_traffic",
                "value": float(m),
            })
    comp = assess_temporal_cycle_completeness(pd.DataFrame(rows))
    month_info = comp["http_traffic"]["cycle_details"]["month"]
    assert month_info["cycle_complete"] is True
    assert month_info["cycle_count"] == 2
    assert month_info["min_repetitions"] == 2
    assert month_info["confirmed"] is True
    assert month_info["limitation"] is None


def test_temporal_pattern_empty_buckets_not_created():
    # 3 quan sát rơi vào giờ 10 và 11 (giờ VN)
    # 2026-11-01 03:00 UTC = 10:00 VN
    # 2026-11-01 04:00 UTC = 11:00 VN
    # 2026-11-02 03:00 UTC = 10:00 VN
    df = pd.DataFrame([
        {"ts": datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 1.0},
        {"ts": datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 2.0},
        {"ts": datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": 3.0},
    ])
    records = compute_temporal_pattern_records(df)
    hour_buckets = {r["bucket"] for r in records if r["period_type"] == "hour_of_day"}
    assert hour_buckets == {10, 11}
    assert 0 not in hour_buckets
    assert 23 not in hour_buckets


def test_temporal_pattern_cycle_count_uses_distinct_cycles_not_row_count():
    """cycle_count phải đếm chu kỳ quan sát độc lập, không phải obs ÷ độ dài chu kỳ.

    Dữ liệu thưa: 3 ngày khác nhau, mỗi ngày chỉ 8 giờ (giờ 0..7) -> 24 quan sát.
    Công thức cũ len//24 = 1 sẽ báo sai; số ngày distinct thực tế = 3.
    """
    base = datetime(2026, 11, 1, 17, 0, tzinfo=timezone.utc)  # 00:00 VN ngày 2/11
    rows = []
    for d in range(3):
        for h in range(8):
            rows.append({
                "ts": base + pd.Timedelta(days=d, hours=h),
                "metric": "http_traffic",
                "value": 1.0,
            })
    comp = assess_temporal_cycle_completeness(pd.DataFrame(rows))
    hour_info = comp["http_traffic"]["cycle_details"]["hour_of_day"]
    # 24 quan sát nhưng chỉ 3 ngày distinct -> cycle_count = 3 (không phải 1)
    assert hour_info["cycle_count"] == 3
    # Chỉ có 8 giờ -> chưa đủ 24 bucket -> cycle_complete = False
    assert hour_info["cycle_complete"] is False
    assert hour_info["confirmed"] is False
