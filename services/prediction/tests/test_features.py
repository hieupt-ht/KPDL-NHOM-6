import pandas as pd
import pytest

from features import build_cluster_features, build_features, daily_agg, load_hourly
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


def test_duplicate_hours_cannot_complete_a_missing_hour():
    h = vn_hourly(1).iloc[:-1]
    h = pd.concat([h, h.iloc[[0]]], ignore_index=True)
    assert daily_agg(h).isna().all()


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), None])
def test_non_finite_hour_cannot_complete_a_day(value):
    h = vn_hourly(1)
    h.loc[0, "value"] = value
    assert daily_agg(h).isna().all()


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
    df = build_features(vn_hourly(14), dropna=False, risk_hourly=vn_hourly(14, value=lambda t: 100.0 + t.day))
    assert {"risk_value", "risk_lag_2", "risk_lag_7", "risk_roll_mean_3", "risk_roll_mean_7"} <= set(df.columns)
    row = df.loc["2026-01-10"]
    assert row["risk_value"] == 110 and row["risk_lag_2"] == 108 and row["risk_roll_mean_3"] == 107


def test_risk_ref_is_rolling_percentile_of_known_days():
    import numpy as np

    from features import risk_reference
    from ml_config import HORIZON, RISK_PERCENTILE, RISK_ROLLING_DAYS

    s = pd.Series(np.arange(60, dtype=float), index=pd.date_range("2026-01-01", periods=60, tz=TIMEZONE))
    window = s.iloc[60 - HORIZON - RISK_ROLLING_DAYS : 60 - HORIZON]
    assert risk_reference(s).iloc[-1] == pytest.approx(np.percentile(window, RISK_PERCENTILE))
    assert "risk_ref" in build_features(vn_hourly(40), risk_hourly=vn_hourly(40)).columns
    # Không dùng giá trị của chính ngày đích hay ngày gần hơn HORIZON.
    s = pd.Series([0.0] * 30 + [1000.0], index=pd.date_range("2026-01-01", periods=31, tz="Asia/Ho_Chi_Minh"))
    assert risk_reference(s).iloc[-1] == 0.0


def test_classifier_inputs_relative_to_references():
    from features import classifier_inputs

    df = pd.DataFrame({"lag_2": [10.0], "lag_7": [12.0], "dow": [3], "risk_lag_2": [5.0], "risk_ref": [4.0]})
    X = classifier_inputs(df, ["lag_2", "lag_7", "dow", "risk_lag_2", "risk_ref"])
    assert list(X.columns) == ["lag_7", "dow", "risk_lag_2"] and X.iloc[0].tolist() == [2.0, 3, 1.0]
    assert list(classifier_inputs(df, ["lag_2", "risk_lag_2"]).columns) == ["lag_2", "risk_lag_2"]


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


def test_load_hourly_reads_only_radar_source():
    class Conn:
        def execute(self, sql, params=None):
            self.sql, self.params = sql, params
            return self

        def fetchall(self):
            return [(pd.Timestamp("2026-01-01", tz="UTC"), 1.0)]

    conn = Conn()
    df = load_hourly(conn, "l7_attack")
    assert "silver.metrics_hourly" in conn.sql and "COALESCE(source, 'radar') = 'radar'" in conn.sql
    assert conn.params == ("l7_attack",) and list(df.columns) == ["ts", "value"] and len(df) == 1


# ---- Edge case: múi giờ, kiểu dữ liệu, thứ tự đầu vào ----


def test_single_day_has_no_complete_row():
    assert build_features(vn_hourly(1)).empty
    assert len(build_features(vn_hourly(1), dropna=False)) == 1


def test_non_vietnam_timestamps_grouped_by_vietnam_day():
    # 23:00 giờ -05:00 ngày 01-01 = 04:00 UTC ngày 01-02 = 11:00 giờ VN ngày 01-02.
    ts = pd.DatetimeIndex(["2026-01-01 23:00-05:00"])
    df = build_features(pd.DataFrame({"ts": ts, "value": [5.0]}), dropna=False)
    assert list(df.index.strftime("%Y-%m-%d")) == ["2026-01-02"]


def test_naive_timestamps_treated_as_utc():
    h = vn_hourly(14)
    naive = h.assign(ts=h["ts"].dt.tz_localize(None))
    pd.testing.assert_frame_equal(build_features(naive), build_features(h))


def test_integer_values_and_unsorted_input():
    h = vn_hourly(14).assign(value=lambda d: d["value"].astype(int)).sample(frac=1, random_state=0)
    pd.testing.assert_frame_equal(build_features(h), build_features(vn_hourly(14)))


def test_load_hourly_empty_result():
    class Conn:
        def execute(self, sql, params=None):
            return self

        def fetchall(self):
            return []

    df = load_hourly(Conn(), "l7_attack")
    assert list(df.columns) == ["ts", "value"] and df.empty
