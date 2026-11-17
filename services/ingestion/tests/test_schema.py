import pytest

pytestmark = pytest.mark.integration


def test_metrics_hourly_has_source_default_radar(db_conn):
    db_conn.execute("INSERT INTO silver.metrics_hourly (ts, metric, value) VALUES ('2000-01-01T00:00Z', 'x', 1)")
    row = db_conn.execute("SELECT source FROM silver.metrics_hourly WHERE metric = 'x'").fetchone()
    assert row[0] == "radar"


def test_bronze_has_fetched_at_index(db_conn):
    row = db_conn.execute(
        "SELECT 1 FROM pg_indexes WHERE schemaname='bronze' AND indexname='idx_bronze_fetched_at'"
    ).fetchone()
    assert row is not None
