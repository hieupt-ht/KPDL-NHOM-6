"""Cấu hình pytest và các fixtures dữ liệu giả lập cho Analysis."""

from datetime import datetime, timedelta, timezone
import pytest
import numpy as np
import pandas as pd


@pytest.fixture
def sample_timestamps() -> list[datetime]:
    """Tạo 24 mốc thời gian cách nhau 1 giờ."""
    base = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
    return [base + timedelta(hours=i) for i in range(24)]


@pytest.fixture
def sample_silver_df(sample_timestamps) -> pd.DataFrame:
    """Tạo DataFrame Silver mẫu với 5 chỉ số cho 24 giờ."""
    rows = []
    for ts in sample_timestamps:
        rows.append({"ts": ts, "metric": "http_traffic", "value": 0.8 + 0.1 * np.sin(ts.hour)})
        rows.append({"ts": ts, "metric": "l7_attack", "value": 0.05 + 0.02 * np.cos(ts.hour)})
        rows.append({"ts": ts, "metric": "bot_share", "value": 35.0 + 5.0 * np.sin(ts.hour)})
        rows.append({"ts": ts, "metric": "human_share", "value": 65.0 - 5.0 * np.sin(ts.hour)})
        rows.append({"ts": ts, "metric": "netflows", "value": 0.75 + 0.05 * np.cos(ts.hour)})
    return pd.DataFrame(rows)


@pytest.fixture
def long_sample_silver_df() -> pd.DataFrame:
    """Tạo chuỗi dữ liệu 12 tuần (84 ngày x 24 giờ = 2016 điểm) để kiểm tra tuần & trend."""
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    rows = []
    for h in range(84 * 24):
        ts = base + timedelta(hours=h)
        val = 1.0 + 0.2 * np.sin(h / 24.0) + 0.05 * (h / (84 * 24))
        rows.append({"ts": ts, "metric": "http_traffic", "value": val})
        rows.append({"ts": ts, "metric": "l7_attack", "value": 0.1 + 0.05 * np.cos(h / 24.0)})
    return pd.DataFrame(rows)
