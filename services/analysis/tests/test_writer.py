"""Kiểm thử mô-đun ghi Database (Writer) toàn diện."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest

from writer import (
    write_all_analysis_results,
    write_correlation,
    write_freshness,
    write_histogram,
    write_resampled,
    write_seasonal,
    write_trend,
)


def test_write_all_analysis_results_transaction_and_params():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.transaction.return_value.__enter__.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    latest_ts = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

    resampled = [{"granularity": "day", "ts": latest_ts, "metric": "http_traffic", "mean": 1.0, "min": 0.5, "max": 1.5}]
    histogram = [{"metric": "http_traffic", "bin_start": 0.0, "bin_end": 1.0, "count": 10}]
    trend = [{"granularity": "week", "ts": latest_ts, "metric": "http_traffic", "trend_value": 0.9}]
    seasonal = [{"period_type": "hour_of_day", "bucket": 10, "metric": "http_traffic", "value": 1.1}]
    correlation = [{"var_x": "http_traffic", "var_y": "l7_attack", "coef": 0.75}]

    write_all_analysis_results(
        resampled_records=resampled,
        histogram_records=histogram,
        trend_records=trend,
        seasonal_records=seasonal,
        correlation_records=correlation,
        latest_silver_ts=latest_ts,
        conn=mock_conn,
    )

    mock_conn.transaction.assert_called_once()
    assert mock_cur.executemany.call_count >= 5

    # Đảm bảo có cập nhật gold.data_freshness
    execute_calls = [c[0][0] for c in mock_cur.execute.call_args_list]
    assert any("gold.data_freshness" in q for q in execute_calls)

    # Đảm bảo tuyệt đối không ghi vào gold.service_runs
    all_sql_queries = [c[0][0] for c in mock_cur.execute.call_args_list] + \
                      [c[0][0] for c in mock_cur.executemany.call_args_list]
    for q in all_sql_queries:
        assert "gold.service_runs" not in q.lower()


def test_parameterized_queries_verification():
    # Xác minh tất cả các lệnh INSERT đều sử dụng parameterized SQL (%s)
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.transaction.return_value.__enter__.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    latest_ts = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    resampled = [{"granularity": "day", "ts": latest_ts, "metric": "http_traffic", "mean": 1.0, "min": 0.5, "max": 1.5}]

    write_all_analysis_results(
        resampled_records=resampled,
        histogram_records=[],
        trend_records=[],
        seasonal_records=[],
        correlation_records=[],
        latest_silver_ts=latest_ts,
        conn=mock_conn,
    )

    for call_args in mock_cur.executemany.call_args_list:
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "%s" in sql
        assert isinstance(params, list)


def test_write_rollback_on_failure():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    # Giả lập lỗi ở cursor.executemany khi ghi bảng histogram
    mock_cur.executemany.side_effect = RuntimeError("Database disk full simulation")

    mock_tx = MagicMock()
    mock_conn.transaction.return_value = mock_tx
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    latest_ts = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    resampled = [{"granularity": "day", "ts": latest_ts, "metric": "http_traffic", "mean": 1.0, "min": 0.5, "max": 1.5}]

    with pytest.raises(RuntimeError, match="Database disk full simulation"):
        write_all_analysis_results(
            resampled_records=resampled,
            histogram_records=[],
            trend_records=[],
            seasonal_records=[],
            correlation_records=[],
            latest_silver_ts=latest_ts,
            conn=mock_conn,
        )

    # Đảm bảo transaction context manager đã được kích hoạt
    mock_conn.transaction.assert_called_once()


def test_idempotent_rerun_deletes_old_data():
    # Khi chạy lại, tất cả 5 bảng Gold phải được thực thi lệnh DELETE trước khi INSERT
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.transaction.return_value.__enter__.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    latest_ts = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    write_all_analysis_results([], [], [], [], [], latest_silver_ts=latest_ts, conn=mock_conn)

    deleted_tables = [c[0][0].strip() for c in mock_cur.execute.call_args_list if "DELETE FROM" in c[0][0]]
    assert "DELETE FROM gold.timeseries_resampled" in deleted_tables
    assert "DELETE FROM gold.histogram" in deleted_tables
    assert "DELETE FROM gold.trend" in deleted_tables
    assert "DELETE FROM gold.seasonal" in deleted_tables
    assert "DELETE FROM gold.correlation" in deleted_tables


def test_write_all_analysis_results_rejects_none_silver_ts():
    mock_conn = MagicMock()
    with pytest.raises(ValueError, match="latest_silver_ts không được rỗng"):
        write_all_analysis_results([], [], [], [], [], latest_silver_ts=None, conn=mock_conn)


def test_individual_writers():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.transaction.return_value.__enter__.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    now = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    write_resampled(
        [{"granularity": "day", "ts": now, "metric": "http_traffic", "mean": 1.0, "min": 0.5, "max": 1.5}],
        conn=mock_conn,
    )
    write_histogram([{"metric": "http_traffic", "bin_start": 0.0, "bin_end": 1.0, "count": 10}], conn=mock_conn)
    write_trend([{"granularity": "week", "ts": now, "metric": "http_traffic", "trend_value": 0.9}], conn=mock_conn)
    write_seasonal(
        [{"period_type": "hour_of_day", "bucket": 10, "metric": "http_traffic", "value": 1.1}],
        conn=mock_conn,
    )
    write_correlation([{"var_x": "http_traffic", "var_y": "l7_attack", "coef": 0.75}], conn=mock_conn)
    write_freshness(now, conn=mock_conn)

    assert mock_conn.transaction.call_count == 6
    assert mock_cur.executemany.call_count >= 5
