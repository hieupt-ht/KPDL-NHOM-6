import pandas as pd

from features import build_features


def _hourly(days: int) -> pd.DataFrame:
    ts = pd.date_range("2026-01-01", periods=days * 24, freq="h", tz="UTC")
    return pd.DataFrame({"ts": ts, "value": [float(t.day) for t in ts]})


def test_daily_and_lags():
    df = build_features(_hourly(12))
    assert df.index[0] == pd.Timestamp("2026-01-08", tz="UTC")  # cần 7 ngày lịch sử
    row = df.loc["2026-01-10"]
    assert row["value"] == 10 and row["lag_1"] == 9 and row["lag_7"] == 3
    assert row["roll_mean_3"] == 8.0  # mean(7,8,9), không gồm ngày 10
    assert row["dow"] == pd.Timestamp("2026-01-10").dayofweek


def test_empty():
    assert build_features(pd.DataFrame(columns=["ts", "value"])).empty


def test_gap_day_is_nan_not_shifted():
    h = _hourly(12)
    h = h[h["ts"].dt.day != 5]
    df = build_features(h, dropna=False)
    assert pd.isna(df.loc["2026-01-05", "value"])
    assert pd.isna(df.loc["2026-01-06", "lag_1"])
