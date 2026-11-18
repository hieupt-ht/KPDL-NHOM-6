"""Đặc trưng đầu vào cho hai mô hình dự báo."""

import pandas as pd
import psycopg

DEFAULT_METRIC = "http_traffic"
LAGS = (1, 7)  # ngày
WINDOWS = (3, 7)  # ngày


def load_hourly(conn: psycopg.Connection, metric: str = DEFAULT_METRIC) -> pd.DataFrame:
    """Đọc (ts, value) theo giờ của một metric từ silver.metrics_hourly."""
    rows = conn.execute(
        "SELECT ts, value FROM silver.metrics_hourly WHERE metric = %s ORDER BY ts", (metric,)
    ).fetchall()
    return pd.DataFrame(rows, columns=["ts", "value"])


def build_features(hourly: pd.DataFrame, dropna: bool = True) -> pd.DataFrame:
    """Gộp theo ngày (UTC) rồi tạo lag, trung bình trượt, thứ trong tuần.

    Đầu vào: cột ts, value. Đầu ra: index = ngày, cột `value` (mean ngày),
    `lag_*`, `roll_mean_*`, `dow`. Đặc trưng chỉ dùng dữ liệu của các ngày TRƯỚC
    (shift 1) nên không rò rỉ giá trị ngày đang dự báo. Ngày thiếu được chèn NaN
    để lag đúng theo lịch.
    """
    cols = ["value"] + [f"lag_{n}" for n in LAGS] + [f"roll_mean_{w}" for w in WINDOWS] + ["dow"]
    if hourly.empty:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="day"))

    ts = pd.to_datetime(hourly["ts"], utc=True)
    daily = hourly["value"].astype(float).groupby(ts.dt.floor("D")).mean()
    daily = daily.asfreq("D")
    daily.index.name = "day"

    out = pd.DataFrame({"value": daily})
    for n in LAGS:
        out[f"lag_{n}"] = daily.shift(n)
    past = daily.shift(1)
    for w in WINDOWS:
        out[f"roll_mean_{w}"] = past.rolling(w, min_periods=w).mean()
    out["dow"] = out.index.day_of_week
    return out.dropna() if dropna else out
