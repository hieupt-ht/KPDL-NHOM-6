from datetime import datetime, timedelta, timezone

import pytest

from bronze import purge_old, save_raw_response
from runs import finish_run, start_run
from silver import earliest_ts, read_range, upsert_metrics

pytestmark = pytest.mark.integration

T0 = datetime(2000, 1, 1, tzinfo=timezone.utc)


def test_upsert_is_idempotent_and_updates_value(db_conn):
    pts = {T0 + timedelta(hours=i): float(i) / 10 for i in range(3)}
    assert upsert_metrics("t_metric", pts, conn=db_conn) == 3
    pts2 = {**pts, T0: 0.99}
    upsert_metrics("t_metric", pts2, conn=db_conn)
    rows = db_conn.execute("SELECT ts, value, source FROM silver.metrics_hourly WHERE metric='t_metric' ORDER BY ts").fetchall()
    assert len(rows) == 3
    assert rows[0][1] == 0.99 and rows[0][2] == "radar"


def test_read_range_and_earliest_ts(db_conn):
    assert earliest_ts("t_metric", conn=db_conn) is None
    pts = {T0 + timedelta(hours=i): float(i) for i in range(5)}
    upsert_metrics("t_metric", pts, conn=db_conn)
    assert earliest_ts("t_metric", conn=db_conn) == T0
    got = read_range("t_metric", T0 + timedelta(hours=1), T0 + timedelta(hours=3), conn=db_conn)
    assert got == {T0 + timedelta(hours=h): float(h) for h in (1, 2, 3)}


def test_bronze_saves_verbatim_payload_and_status(db_conn):
    payload = {"success": False, "errors": [{"code": 1000, "message": "x"}], "nested": {"a": [1, 2, None]}}
    save_raw_response("http_traffic", {"location": "VN"}, 429, payload, conn=db_conn)
    row = db_conn.execute(
        "SELECT params, status_code, payload FROM bronze.raw_api_responses WHERE endpoint='http_traffic' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row == ({"location": "VN"}, 429, payload)


def test_purge_old_deletes_only_older_than_30_days(db_conn):
    db_conn.execute("DELETE FROM bronze.raw_api_responses")
    db_conn.execute("INSERT INTO bronze.raw_api_responses (endpoint, fetched_at) VALUES ('old', now() - interval '31 days')")
    db_conn.execute("INSERT INTO bronze.raw_api_responses (endpoint, fetched_at) VALUES ('new', now() - interval '29 days')")
    assert purge_old(30, conn=db_conn) == 1
    left = [r[0] for r in db_conn.execute("SELECT endpoint FROM bronze.raw_api_responses").fetchall()]
    assert left == ["new"]


def test_run_log_start_finish(db_conn):
    rid = start_run(conn=db_conn)
    finish_run(rid, "partial", 7, "boom", conn=db_conn)
    row = db_conn.execute("SELECT status, rows_upserted, error, finished_at FROM silver.ingestion_runs WHERE id=%s", (rid,)).fetchone()
    assert row[:3] == ("partial", 7, "boom") and row[3] is not None
