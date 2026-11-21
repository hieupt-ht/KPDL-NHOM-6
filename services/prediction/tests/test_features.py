import pandas as pd
import pytest

from features import build_cluster_features, build_features, daily_agg
from ml_config import TIMEZONE


def vn_hourly(days: int, start: str = "2026-01-01", extra_hours: int = 0, value=lambda t: float(t.day)) -> pd.DataFrame:
    """Chuỗi giờ bắt đầu 00:00 giờ VN; `extra_hours` là vài giờ của ngày kế tiếp (chưa đủ ngày)."""
    ts = pd.date_range(pd.Timestamp(start, tz=TIMEZONE), periods=days * 24 + extra_hours, freq="h")
    return pd.DataFrame({"ts": ts.tz_convert("UTC"), "value": [value(t) for t in ts]})


def test_daily_uses_vietnam_day_and_requires_24_hours():
    d = daily_agg(vn_hourly(10, extra_hours=5))
    assert str(d.index.tz) == TIMEZONE and d.index[0] == pd.Timestamp("2026-01-01", tz=TIMEZONE)
    assert d.loc["2026-01-09"] == 9.0
    assert pd.isna(d.loc["2026-01-11"])  # ngày cuối mới có 5 giờ: bị loại


def test_utc_midnight_data_is_not_a_full_vietnam_day():
    ts = pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC")  # 00:00 UTC = 07:00 VN
    d = daily_agg(pd.DataFrame({"ts": ts, "value": 1.0}))
    assert d.isna().sum() == len(d) - 1 and d.dropna().index[0] == pd.Timestamp("2026-01-02", tz=TIMEZONE)


def test_daily_max_and_empty():
    h = vn_hourly(3, value=lambda t: float(t.hour))
    assert daily_agg(h, "max").dropna().tolist() == [23.0, 23.0, 23.0]
    assert daily_agg(pd.DataFrame(columns=["ts", "value"])).empty


def test_features_lags_skip_horizon():
    df = build_features(vn_hourly(14), dropna=False)  # value = ngày trong tháng
    assert list(df.columns) == ["value", "lag_2", "lag_7", "roll_mean_3", "roll_mean_7", "dow"]
    row = df.loc["2026-01-10"]
    assert row["value"] == 10 and row["lag_2"] == 8 and row["lag_7"] == 3
    assert row["roll_mean_3"] == 7.0  # mean(6,7,8): kết thúc 2 ngày trước, không gồm hôm qua
    assert row["roll_mean_7"] == 5.0  # mean(2..8)
    assert row["dow"] == pd.Timestamp("2026-01-10").day_of_week
    assert build_features(vn_hourly(14)).index[0] == pd.Timestamp("2026-01-09", tz=TIMEZONE)


def test_empty():
    assert build_features(pd.DataFrame(columns=["ts", "value"])).empty


def test_gap_day_is_nan_not_shifted():
    h = vn_hourly(14)
    h = h[pd.to_datetime(h["ts"]).dt.tz_convert(TIMEZONE).dt.day != 5]
    df = build_features(h, dropna=False)
    assert pd.isna(df.loc["2026-01-05", "value"])
    assert pd.isna(df.loc["2026-01-07", "lag_2"])


def test_risk_columns_added():
    df = build_features(vn_hourly(14), risk_hourly=vn_hourly(14, value=lambda t: 100.0 + t.day))
    assert {"risk_value", "risk_lag_2", "risk_lag_7", "risk_roll_mean_3", "risk_roll_mean_7"} <= set(df.columns)
    row = df.loc["2026-01-10"]
    assert row["risk_value"] == 110 and row["risk_lag_2"] == 108 and row["risk_roll_mean_3"] == 107


def test_cluster_features_daily_http_mean_l7_max_bot_mean():
    http = vn_hourly(5, value=lambda t: 10.0 + t.day)
    l7 = vn_hourly(5, value=lambda t: float(t.hour))
    bot = vn_hourly(5, value=lambda t: 30.0)
    df = build_cluster_features({"http_traffic": http, "l7_attack": l7, "bot_share": bot})
    assert list(df.columns) == ["http_mean", "l7_max", "bot_mean"] and len(df) == 5
    assert df.iloc[0].tolist() == [11.0, 23.0, 30.0]


def test_cluster_features_drop_day_missing_in_any_metric():
    http, l7, bot = vn_hourly(5), vn_hourly(5), vn_hourly(5)
    day = pd.to_datetime(bot["ts"]).dt.tz_convert(TIMEZONE).dt.day
    df = build_cluster_features({"http_traffic": http, "l7_attack": l7, "bot_share": bot[day != 3]})
    assert len(df) == 4 and pd.Timestamp("2026-01-03", tz=TIMEZONE) not in df.index
    assert build_cluster_features({}).empty
