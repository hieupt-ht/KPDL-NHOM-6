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
         patch("tasks.get_latest_silver_ts", return_value=None), \
         patch("tasks.write_all_analysis_results") as mock_write:
        tasks.run_all()
        mock_write.assert_not_called()


def test_run_all_skips_when_silver_all_nan():
    # Dữ liệu có dòng nhưng toàn bộ là NaN
    df = pd.DataFrame([
        {"ts": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": np.nan},
        {"ts": datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), "metric": "http_traffic", "value": np.nan},
    ])
    with patch("tasks.fetch_silver_metrics", return_value=df), \
         patch("tasks.get_latest_silver_ts", return_value=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)), \
         patch("tasks.write_all_analysis_results") as mock_write:
        tasks.run_all()
        # Không được ghi đè Mart khi dữ liệu unusable
        mock_write.assert_not_called()


def test_run_all_success_flow(sample_silver_df):
    latest_ts = datetime(2026, 11, 1, 23, 0, tzinfo=timezone.utc)
    with patch("tasks.fetch_silver_metrics", return_value=sample_silver_df), \
         patch("tasks.get_latest_silver_ts", return_value=latest_ts), \
         patch("tasks.write_all_analysis_results") as mock_write:
        tasks.run_all()
        mock_write.assert_called_once()
        kwargs = mock_write.call_args[1]
        assert len(kwargs["resampled_records"]) > 0
        assert len(kwargs["histogram_records"]) > 0
        assert len(kwargs["seasonal_records"]) > 0
        assert len(kwargs["correlation_records"]) > 0
        assert kwargs["latest_silver_ts"] == latest_ts


def test_run_all_database_error_propagates():
    # Lỗi kết nối DB không được nuốt chửng
    with patch("tasks.fetch_silver_metrics", side_effect=psycopg.OperationalError("Connection failed")):
        with pytest.raises(psycopg.OperationalError, match="Connection failed"):
            tasks.run_all()


def test_individual_compute_tasks(sample_silver_df):
    with patch("tasks.fetch_silver_metrics", return_value=sample_silver_df), \
         patch("tasks.write_resampled") as mock_resampled, \
         patch("tasks.write_histogram") as mock_hist, \
         patch("tasks.write_trend"), \
         patch("tasks.write_seasonal") as mock_seasonal, \
         patch("tasks.write_correlation") as mock_corr:

        tasks.compute_resampled()
        mock_resampled.assert_called_once()

        tasks.compute_histogram()
        mock_hist.assert_called_once()

        tasks.compute_trend()
        # sample_silver_df có 24h, không đủ 8 tuần nên trend rỗng, không gọi write_trend

        tasks.compute_seasonal()
        mock_seasonal.assert_called_once()

        tasks.compute_correlation()
        mock_corr.assert_called_once()
