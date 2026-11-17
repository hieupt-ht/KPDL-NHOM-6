"""Kiểm thử mô-đun đọc dữ liệu Silver (Reader)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import pandas as pd

from reader import fetch_silver_metrics, get_latest_silver_ts


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


def test_fetch_silver_metrics():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    t1 = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    mock_cur.fetchall.return_value = [
        (t1, "http_traffic", 0.85),
        (t1, "l7_attack", 0.05),
    ]

    df = fetch_silver_metrics(metrics=["http_traffic", "l7_attack"], conn=mock_conn)
    assert len(df) == 2
    assert list(df.columns) == ["ts", "metric", "value"]
    assert df["metric"].tolist() == ["http_traffic", "l7_attack"]
    assert df["value"].tolist() == [0.85, 0.05]


def test_fetch_silver_metrics_empty():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = []

    df = fetch_silver_metrics(conn=mock_conn)
    assert df.empty
    assert list(df.columns) == ["ts", "metric", "value"]

