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
    assert row["dow"] == pd.Timestamp("2026-01-10").day_of_week


def test_empty():
    assert build_features(pd.DataFrame(columns=["ts", "value"])).empty


def test_gap_day_is_nan_not_shifted():
    h = _hourly(12)
    h = h[h["ts"].dt.day != 5]
    df = build_features(h, dropna=False)
    assert pd.isna(df.loc["2026-01-05", "value"])
    assert pd.isna(df.loc["2026-01-06", "lag_1"])


def test_single_day_has_no_complete_row():
    assert build_features(_hourly(1)).empty
    assert len(build_features(_hourly(1), dropna=False)) == 1


def test_non_utc_timestamps_grouped_by_utc_day():
    # 23:00 giờ -05:00 ngày 01-01 = 04:00 UTC ngày 01-02.
    ts = pd.DatetimeIndex(["2026-01-01 23:00-05:00"])
    df = build_features(pd.DataFrame({"ts": ts, "value": [5.0]}), dropna=False)
    assert list(df.index.strftime("%Y-%m-%d")) == ["2026-01-02"]


def test_naive_timestamps_treated_as_utc():
    h = _hourly(10)
    naive = h.assign(ts=h["ts"].dt.tz_localize(None))
    pd.testing.assert_frame_equal(build_features(naive), build_features(h))


def test_integer_values_and_unsorted_input():
    h = _hourly(12).assign(value=lambda d: d["value"].astype(int)).sample(frac=1, random_state=0)
    pd.testing.assert_frame_equal(build_features(h), build_features(_hourly(12)))


def test_load_hourly_empty_and_metric_param():
    from features import load_hourly

    class Conn:
        def __init__(self, rows):
            self.rows, self.params = rows, None

        def execute(self, sql, params=None):
            self.params = params

            class R:
                fetchall = staticmethod(lambda: self.rows)

            return R

    c = Conn([])
    df = load_hourly(c, "l7_attack")
    assert list(df.columns) == ["ts", "value"] and df.empty and c.params == ("l7_attack",)
