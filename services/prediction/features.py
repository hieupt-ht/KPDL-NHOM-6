"""Đặc trưng theo ngày cho các mô hình dự báo và phân cụm.

Ngày tính theo giờ Việt Nam (ml_config.TIMEZONE); Silver vẫn lưu UTC. Một ngày chỉ hợp lệ khi đủ
MIN_HOURS_PER_DAY mốc giờ; ngày thiếu hoặc chưa đủ (thường là ngày cuối do Radar trễ) thành NaN.
"""

from __future__ import annotations

import pandas as pd
import psycopg

from ml_config import (  # noqa: F401  (cấu hình: ml_config.json)
    CLUSTER_FEATURES,
    CLUSTER_METRICS,
    CLUSTER_SPECS,
    HORIZON,
    LAGS,
    METRIC as DEFAULT_METRIC,
    MIN_HOURS_PER_DAY,
    TIMEZONE,
    WINDOWS,
)


def load_hourly(conn: psycopg.Connection, metric: str = DEFAULT_METRIC) -> pd.DataFrame:
    """Đọc (ts, value) theo giờ của một metric từ silver.metrics_hourly."""
    rows = conn.execute(
        "SELECT ts, value FROM silver.metrics_hourly WHERE metric = %s ORDER BY ts", (metric,)
    ).fetchall()
    return pd.DataFrame(rows, columns=["ts", "value"])


def _empty_daily() -> pd.Series:
    return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz=TIMEZONE, name="day"))


def daily_agg(hourly: pd.DataFrame, how: str = "mean") -> pd.Series:
    """Gộp (ts, value) theo ngày VN bằng `how` (mean | max); chỉ ngày đủ giờ mới có giá trị.

    Index = ngày (tz VN) liên tục từ ngày đầu đến ngày cuối; ngày thiếu hoặc chưa đủ giờ là NaN.
    """
    if hourly.empty:
        return _empty_daily()
    ts = pd.to_datetime(hourly["ts"], utc=True).dt.tz_convert(TIMEZONE)
    agg = hourly["value"].astype(float).groupby(ts.dt.normalize()).agg([how, "count"])
    daily = agg[how].where(agg["count"] >= MIN_HOURS_PER_DAY).asfreq("D")
    daily.index.name = "day"
    return daily


def _lagged(daily: pd.Series, prefix: str = "") -> pd.DataFrame:
    """Lag và trung bình trượt chỉ dùng các ngày <= (ngày đích - HORIZON), không rò rỉ."""
    cols = {f"{prefix}lag_{n}": daily.shift(n) for n in LAGS}
    past = daily.shift(HORIZON)
    cols.update({f"{prefix}roll_mean_{w}": past.rolling(w, min_periods=w).mean() for w in WINDOWS})
    return pd.DataFrame(cols, index=daily.index)


def feature_frame(daily: pd.Series, risk_daily: pd.Series | None = None, upto: pd.Timestamp | None = None) -> pd.DataFrame:
    """Bảng đặc trưng theo ngày từ chuỗi ngày của metric đích (và metric rủi ro nếu có).

    Cột: `value`, `lag_*`, `roll_mean_*`, `dow` (thứ của ngày đích, 0 = thứ Hai) và, khi có
    `risk_daily`, `risk_value`, `risk_lag_*`, `risk_roll_mean_*`. `upto` kéo dài index tới ngày
    đích chưa có dữ liệu (dùng lúc dự báo); các cột giá trị của ngày đó là NaN.
    """
    if daily.empty:
        cols = ["value"] + [f"lag_{n}" for n in LAGS] + [f"roll_mean_{w}" for w in WINDOWS] + ["dow"]
        if risk_daily is not None:
            cols += ["risk_value"] + [f"risk_lag_{n}" for n in LAGS] + [f"risk_roll_mean_{w}" for w in WINDOWS]
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], tz=TIMEZONE, name="day"))
    if upto is not None:
        daily = daily.reindex(pd.date_range(daily.index[0], upto, freq="D"))
        daily.index.name = "day"
    parts = [daily.rename("value"), _lagged(daily)]
    out = pd.concat(parts, axis=1)
    out["dow"] = out.index.day_of_week
    if risk_daily is not None:
        risk = risk_daily.reindex(out.index)
        out = pd.concat([out, risk.rename("risk_value"), _lagged(risk, "risk_")], axis=1)
    return out


def build_features(hourly: pd.DataFrame, dropna: bool = True, risk_hourly: pd.DataFrame | None = None) -> pd.DataFrame:
    """Đặc trưng huấn luyện từ chuỗi giờ của metric đích (và metric rủi ro nếu có).

    Đặc trưng chỉ dùng ngày <= (ngày đích - HORIZON) nên không rò rỉ giá trị ngày đang dự báo.
    Ngày thiếu được chèn NaN để lag đúng theo lịch.
    """
    risk = None if risk_hourly is None else daily_agg(risk_hourly)
    out = feature_frame(daily_agg(hourly), risk)
    return out.dropna() if dropna else out


def load_cluster_hourly(conn: psycopg.Connection) -> dict[str, pd.DataFrame]:
    """Chuỗi giờ của mọi metric dùng để phân cụm (ml_config cluster.features)."""
    return {m: load_hourly(conn, m) for m in CLUSTER_METRICS}


def build_cluster_features(hourlies: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Đặc trưng phân cụm theo ngày VN: mỗi cột = gộp ngày (mean/max) của một metric.

    Chỉ giữ ngày đủ giờ ở mọi metric. Thiếu metric (không có trong `hourlies`) thì không có ngày nào.
    """
    cols = {
        s["name"]: daily_agg(hourlies.get(s["metric"], pd.DataFrame(columns=["ts", "value"])), s["agg"])
        for s in CLUSTER_SPECS
    }
    return pd.DataFrame(cols, columns=CLUSTER_FEATURES).dropna()
