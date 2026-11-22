"""Kiểm thử orchestration trong tasks.py toàn diện."""

from datetime import datetime, timezone
from unittest.mock import patch
import numpy as np
import pandas as pd
import psycopg
import pytest

import tasks


def test_run_all_skips_when_silver_empty():
    with patch("tasks.fetch_silver_metrics", return_value=pd.DataFrame()), \
         patch("tasks.write_all_analysis_results") as mock_write:
        status = tasks.run_all()
        assert status == "skipped"
        mock_write.assert_not_called()


def test_run_all_skips_when_silver_all_nan():
    # Dữ liệu có dòng nhưng toàn bộ là NaN
    df = pd.DataFrame([
        {"ts": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": np.nan},
        {"ts": datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": np.nan},
    ])
    with patch("tasks.fetch_silver_metrics", return_value=df), \
         patch("tasks.write_all_analysis_results") as mock_write:
        status = tasks.run_all()
        assert status == "failed"
        mock_write.assert_not_called()


def test_run_all_latest_ts_derived_from_df(sample_silver_df):
    """latest_silver_ts phải lấy từ df["ts"].max(), không phải DB call riêng."""
    expected_ts = sample_silver_df["ts"].max().to_pydatetime()
    with patch("tasks.fetch_silver_metrics", return_value=sample_silver_df), \
         patch("tasks.write_all_analysis_results") as mock_write:
        status = tasks.run_all()
        assert status in ("success", "partial")
        mock_write.assert_called_once()
        kwargs = mock_write.call_args[1]
        assert kwargs["latest_silver_ts"] == expected_ts


def test_run_all_success_flow(sample_silver_df):
    with patch("tasks.fetch_silver_metrics", return_value=sample_silver_df), \
         patch("tasks.write_all_analysis_results") as mock_write:
        status = tasks.run_all()
        # sample_silver_df có 24h: trend rỗng nên là partial
        assert status == "partial"
        mock_write.assert_called_once()
        kwargs = mock_write.call_args[1]
        assert len(kwargs["resampled_records"]) > 0
        assert len(kwargs["histogram_records"]) > 0
        assert len(kwargs["temporal_pattern_records"]) > 0
        assert len(kwargs["correlation_records"]) > 0
        assert kwargs["latest_silver_ts"] is not None


def test_run_all_database_error_propagates():
    # Lỗi kết nối DB không được nuốt chửng
    with patch("tasks.fetch_silver_metrics", side_effect=psycopg.OperationalError("Connection failed")):
        with pytest.raises(psycopg.OperationalError, match="Connection failed"):
            tasks.run_all()


def test_run_all_uses_quality_gate_per_algorithm(sample_silver_df):
    """run_all phải dùng algorithm_fitness để bỏ qua thuật toán không đủ điều kiện.

    sample_silver_df chỉ có 24 giờ -> trend fitness = False -> compute_trend_records
    KHÔNG được gọi, trend_records = [] và run trả về 'partial'.
    """
    with patch("tasks.fetch_silver_metrics", return_value=sample_silver_df), \
         patch("tasks.compute_resampling_records", return_value=[{"ok": 1}]) as m_resample, \
         patch("tasks.compute_histogram_records", return_value=[{"ok": 1}]) as m_hist, \
         patch("tasks.compute_trend_records", return_value=[{"ok": 1}]) as m_trend, \
         patch("tasks.compute_temporal_pattern_records", return_value=[{"ok": 1}]) as m_temporal, \
         patch("tasks.compute_correlation_records", return_value=[{"ok": 1}]) as m_corr, \
         patch("tasks.write_all_analysis_results") as mock_write:
        status = tasks.run_all()

    m_resample.assert_called_once()
    m_hist.assert_called_once()
    m_trend.assert_not_called()
    m_temporal.assert_called_once()
    m_corr.assert_called_once()

    assert status == "partial"
    kwargs = mock_write.call_args[1]
    assert kwargs["trend_records"] == []
    assert len(kwargs["resampled_records"]) == 1


def test_run_all_is_single_entry_point():
    """run_all là entry point duy nhất: không còn các hàm compute_* riêng lẻ
    bypass quality gate/snapshot/freshness."""
    assert not hasattr(tasks, "compute_resampled")
    assert not hasattr(tasks, "compute_histogram")
    assert not hasattr(tasks, "compute_trend")
    assert not hasattr(tasks, "compute_temporal_patterns")
    assert not hasattr(tasks, "compute_correlation")

