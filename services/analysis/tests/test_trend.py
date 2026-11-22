"""Kiểm thử phân tích xu hướng (Trend Analysis) toàn diện."""

from datetime import datetime, timedelta, timezone
import zoneinfo

import numpy as np
import pandas as pd

from trend import _expected_bucket_hours, _prepare_regular_series, compute_trend_records


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
    # 25 tháng liên tiếp, mỗi tháng một điểm đầu tháng (đủ >= 24 tháng cho period=12)
    base = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = []
    current_ts = base
    for m in range(25):
        rows.append({
            "ts": current_ts,
            "metric": "http_traffic",
            "value": 1.0 + 0.1 * np.sin(m),
        })
        # Nhảy sang đầu tháng tiếp theo một cách xác định
        current_ts = (current_ts.replace(day=28) + timedelta(days=6)).replace(day=1)

    df = pd.DataFrame(rows)
    records = compute_trend_records(df, metrics=["http_traffic"])
    assert len(records) > 0
    granularities = {r["granularity"] for r in records}
    assert "month" in granularities
    assert "week" not in granularities
    # Timestamp kết quả phải là đầu tháng giờ VN (00:00:00, day == 1)
    for r in records:
        assert r["ts"].day == 1
        assert r["ts"].hour == 0
        assert r["ts"].tzinfo is not None


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


def _monthly_hourly_df(specs) -> pd.DataFrame:
    """Dữ liệu theo giờ liên tiếp, mỗi phần tử specs = (năm, tháng, số giờ).

    Giờ bắt đầu từ 00:00 ngày 1 của tháng theo múi giờ Asia/Ho_Chi_Minh.
    """
    tz = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
    rows = []
    for year, month, hours in specs:
        start = datetime(year, month, 1, 0, 0, tzinfo=tz)
        for h in range(hours):
            rows.append({
                "ts": start + timedelta(hours=h),
                "metric": "http_traffic",
                "value": 1.0 + 0.001 * h,
            })
    return pd.DataFrame(rows)


def test_expected_bucket_hours_by_actual_month_length():
    """Số giờ kỳ vọng phải theo số ngày thực tế của tháng (28/29/30/31 ngày)."""
    tz = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
    assert _expected_bucket_hours(pd.Timestamp("2026-02-01", tz=tz), "M") == 672.0   # 28 ngày
    assert _expected_bucket_hours(pd.Timestamp("2024-02-01", tz=tz), "M") == 696.0   # 29 ngày (năm nhuận)
    assert _expected_bucket_hours(pd.Timestamp("2026-04-01", tz=tz), "M") == 720.0   # 30 ngày
    assert _expected_bucket_hours(pd.Timestamp("2026-01-01", tz=tz), "M") == 744.0   # 31 ngày
    assert _expected_bucket_hours(pd.Timestamp("2026-01-05", tz=tz), "W") == 168.0   # tuần luôn 168 giờ


def test_trend_month_completeness_uses_90_percent_of_actual_hours():
    """Tháng 28 ngày (T2/2026) kỳ vọng 672 giờ -> ngưỡng 90% = 604.8 -> cần >= 605 giờ.

    Trước đây dùng ngưỡng cố định 604 giờ cho mọi tháng -> tháng 31 ngày bị đánh giá
    sai (604/744 = 81%).
    """
    tz = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
    # T2 chỉ có 600 giờ (< 605) -> bucket giữa thiếu -> từ chối chuỗi
    df_short = _monthly_hourly_df([(2026, 1, 744), (2026, 2, 600), (2026, 3, 744)])
    assert _prepare_regular_series(df_short, "M", tz) is None

    # T2 có 610 giờ (>= 605) -> đủ -> chuỗi 3 điểm hợp lệ
    df_ok = _monthly_hourly_df([(2026, 1, 744), (2026, 2, 610), (2026, 3, 744)])
    series = _prepare_regular_series(df_ok, "M", tz)
    assert series is not None
    assert len(series) == 3


def test_trend_month_31days_threshold_is_not_fixed_604():
    """Tháng 31 ngày (T7/2026) kỳ vọng 744 giờ -> ngưỡng 90% = 669.6 -> cần >= 670 giờ.

    Với ngưỡng cũ 604 giờ, bucket 660 giờ (88.7%) sẽ bị coi là đầy đủ -> sai.
    """
    tz = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
    df_short = _monthly_hourly_df([(2026, 6, 720), (2026, 7, 660), (2026, 8, 744)])
    assert _prepare_regular_series(df_short, "M", tz) is None

    df_ok = _monthly_hourly_df([(2026, 6, 720), (2026, 7, 670), (2026, 8, 744)])
    assert _prepare_regular_series(df_ok, "M", tz) is not None


def test_trend_week_requires_152_distinct_hours_not_151():
    """Tuần 168 giờ: 90% = 151.2 -> cần >= 152 giờ distinct.

    151 giờ (89.88%) không còn được coi là đầy đủ như ngưỡng cũ (151).
    """
    tz = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
    base = datetime(2026, 1, 5, 0, 0, tzinfo=tz)  # Thứ Hai

    def _week_df(mid_hours: int) -> pd.DataFrame:
        rows = []
        for w, hours in [(0, 168), (1, mid_hours), (2, 168)]:
            for h in range(hours):
                rows.append({
                    "ts": base + timedelta(weeks=w, hours=h),
                    "metric": "http_traffic",
                    "value": 1.0 + 0.001 * h,
                })
        return pd.DataFrame(rows)

    assert _prepare_regular_series(_week_df(151), "W", tz) is None
    assert _prepare_regular_series(_week_df(152), "W", tz) is not None


def test_trend_duplicate_timestamps_do_not_inflate_completeness():
    """Bucket đủ số DÒNG nhưng thiếu timestamp distinct phải bị từ chối.

    Tuần giữa có 151 giờ distinct, mỗi giờ lặp 2 lần -> 302 dòng.
    Đếm theo dòng sẽ "đủ" (302 >= 151) nhưng theo distinct ts thì thiếu -> từ chối.
    """
    tz = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
    base = datetime(2026, 1, 5, 0, 0, tzinfo=tz)  # Thứ Hai
    rows = []
    for w, hours in [(0, 168), (1, 151), (2, 168)]:
        for h in range(hours):
            ts = base + timedelta(weeks=w, hours=h)
            rows.append({"ts": ts, "metric": "http_traffic", "value": 1.0})
            rows.append({"ts": ts, "metric": "http_traffic", "value": 2.0})

    df = pd.DataFrame(rows)
    assert _prepare_regular_series(df, "W", tz) is None
