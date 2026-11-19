"""Kiểm thử mô-đun đọc dữ liệu Silver (Reader) toàn diện theo hợp đồng Ingestion."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import numpy as np
import pandas as pd

from reader import ALL_METRICS, fetch_silver_metrics, get_latest_silver_ts


def test_get_latest_silver_ts():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    latest = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)
    mock_cur.fetchone.return_value = (latest,)

    result = get_latest_silver_ts(conn=mock_conn)
    assert result == latest


def test_get_latest_silver_ts_empty():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = (None,)

    result = get_latest_silver_ts(conn=mock_conn)
    assert result is None


def test_get_latest_silver_ts_filters_invalid_and_source():
    # Kiểm tra câu lệnh SQL của get_latest_silver_ts có lọc source='radar', NOT isinf, NOT NULL
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    latest = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    mock_cur.fetchone.return_value = (latest,)

    get_latest_silver_ts(source="radar", conn=mock_conn)
    executed_sql = mock_cur.execute.call_args[0][0]
    params = mock_cur.execute.call_args[0][1]

    assert "COALESCE(source, 'radar') = %s" in executed_sql
    assert "value IS NOT NULL" in executed_sql
    assert "NOT isinf(value)" in executed_sql
    assert "radar" in params


def test_fetch_silver_metrics():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    t1 = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    mock_cur.fetchall.return_value = [
        (t1, "http_traffic", 0.85, "radar"),
        (t1, "l7_attack", 0.05, "radar"),
    ]

    df = fetch_silver_metrics(metrics=["http_traffic", "l7_attack"], conn=mock_conn)
    assert len(df) == 2
    assert {"ts", "metric", "value", "source"} <= set(df.columns)
    assert df["metric"].tolist() == ["http_traffic", "l7_attack"]
    assert df["value"].tolist() == [0.85, 0.05]
    assert df["source"].tolist() == ["radar", "radar"]


def test_fetch_silver_metrics_empty():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = []

    df = fetch_silver_metrics(conn=mock_conn)
    assert df.empty
    assert {"ts", "metric", "value", "source"} <= set(df.columns)


def test_reader_all_five_metrics():
    # Kiểm tra đọc đủ cả 5 metric theo hợp đồng
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    t = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    mock_cur.fetchall.return_value = [
        (t, "http_traffic", 1.15, "radar"),
        (t, "l7_attack", 0.08, "radar"),
        (t, "bot_share", 42.5, "radar"),
        (t, "human_share", 57.5, "radar"),
        (t, "netflows", 0.95, "radar"),
    ]

    df = fetch_silver_metrics(conn=mock_conn)
    assert len(df) == 5
    assert set(df["metric"].unique()) == set(ALL_METRICS)


def test_reader_only_radar_data():
    # Mặc định chỉ đọc nguồn radar (production contract)
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = []

    fetch_silver_metrics(conn=mock_conn)
    executed_sql = mock_cur.execute.call_args[0][0]
    params = mock_cur.execute.call_args[0][1]

    assert "COALESCE(source, 'radar') = %s" in executed_sql
    assert "radar" in params


def test_reader_separates_radar_and_demo():
    # Khi yêu cầu source='demo', query phải lọc theo 'demo', không trộn lẫn radar
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    t = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    mock_cur.fetchall.return_value = [(t, "http_traffic", 1.0, "demo")]

    df = fetch_silver_metrics(source="demo", conn=mock_conn)
    params = mock_cur.execute.call_args[0][1]
    assert "demo" in params
    assert (df["source"] == "demo").all()


def test_reader_filters_nonexistent_metrics():
    # Metric lạ/không tồn tại trong ALL_METRICS bị lọc bỏ
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    t = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    mock_cur.fetchall.return_value = [
        (t, "http_traffic", 1.0, "radar"),
        (t, "unsupported_metric_xyz", 99.0, "radar"),
    ]

    df = fetch_silver_metrics(conn=mock_conn)
    assert "unsupported_metric_xyz" not in df["metric"].values
    assert len(df) == 1


def test_reader_handles_null_nan_inf():
    # NULL, NaN, Inf trong value được giữ nguyên kiểu số (không tự tiện đổi về 0)
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    t = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    mock_cur.fetchall.return_value = [
        (t, "http_traffic", None, "radar"),
        (t, "l7_attack", np.nan, "radar"),
        (t, "netflows", np.inf, "radar"),
        (t, "bot_share", "invalid_string", "radar"),
        (t, "human_share", 50.0, "radar"),
    ]

    df = fetch_silver_metrics(conn=mock_conn)
    assert len(df) == 5
    assert pd.isna(df.loc[df["metric"] == "http_traffic", "value"].values[0])
    assert pd.isna(df.loc[df["metric"] == "l7_attack", "value"].values[0])
    assert np.isinf(df.loc[df["metric"] == "netflows", "value"].values[0])
    assert pd.isna(df.loc[df["metric"] == "bot_share", "value"].values[0])
    assert df.loc[df["metric"] == "human_share", "value"].values[0] == 50.0


def test_reader_detects_duplicate_timestamps(caplog):
    # Phát hiện timestamp trùng lặp
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    t = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    mock_cur.fetchall.return_value = [
        (t, "http_traffic", 1.0, "radar"),
        (t, "http_traffic", 1.5, "radar"),
    ]

    df = fetch_silver_metrics(conn=mock_conn)
    assert len(df) == 2
    assert any("trùng lặp" in record.message for record in caplog.records)


def test_reader_normalizes_timezone_to_utc():
    # Timestamp có timezone khác (ví dụ Asia/Ho_Chi_Minh +07:00) được chuẩn hóa sang UTC
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    # 07:00 giờ VN (+07:00) = 00:00 UTC
    vn_tz = timezone(pd.Timedelta(hours=7))
    t_vn = datetime(2026, 11, 1, 7, 0, tzinfo=vn_tz)
    mock_cur.fetchall.return_value = [(t_vn, "http_traffic", 1.0, "radar")]

    df = fetch_silver_metrics(conn=mock_conn)
    assert df["ts"].iloc[0].tzinfo == timezone.utc
    assert df["ts"].iloc[0].hour == 0


def test_reader_preserves_values_above_one_for_relative_metrics():
    # Theo hợp đồng Ingestion, http_traffic, l7_attack, netflows có thể > 1.0 (ví dụ 1.35)
    # Reader không được tự tiện cắt về [0, 1]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    t = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    mock_cur.fetchall.return_value = [
        (t, "http_traffic", 1.35, "radar"),
        (t, "l7_attack", 2.10, "radar"),
        (t, "netflows", 1.05, "radar"),
    ]

    df = fetch_silver_metrics(conn=mock_conn)
    assert df.loc[df["metric"] == "http_traffic", "value"].values[0] == 1.35
    assert df.loc[df["metric"] == "l7_attack", "value"].values[0] == 2.10
    assert df.loc[df["metric"] == "netflows", "value"].values[0] == 1.05

