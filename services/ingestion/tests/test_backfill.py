from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backfill import backfill_endpoint, next_window
from metrics import ENDPOINTS
from silver import earliest_ts, upsert_metrics

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
TARGET = NOW - timedelta(days=365)
HTTP = next(e for e in ENDPOINTS if e.name == "http_traffic")
D = timedelta


def test_next_window_empty_silver_is_latest_28_days():
    assert next_window(None, NOW, TARGET) == (NOW - D(days=28), NOW)


def test_next_window_overlaps_earliest_by_2_days():
    earliest = NOW - D(days=28)
    start, end = next_window(earliest, NOW, TARGET)
    assert end == earliest + D(days=2)
    assert end - start == D(days=28)


def test_next_window_clamps_to_target_start():
    earliest = TARGET + D(days=5)
    start, end = next_window(earliest, NOW, TARGET)
    assert start == TARGET and end == earliest + D(days=2)


def test_next_window_none_when_target_reached():
    assert next_window(TARGET, NOW, TARGET) is None
    assert next_window(TARGET - D(days=1), NOW, TARGET) is None


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def api(floor, calls, always=None):
    """Radar giả: dữ liệu 0.5 mỗi giờ nhưng chỉ từ `floor` trở đi."""

    def handler(req):
        q = req.url.params
        start = datetime.fromisoformat(q["dateStart"])
        end = datetime.fromisoformat(q["dateEnd"])
        calls.append((start, end))
        if always is not None:
            start, end = always
        start = max(start, floor)
        ts, t = [], start
        while t <= end:
            ts.append(_iso(t))
            t += D(hours=1)
        return httpx.Response(200, json={"success": True, "result": {"serie_0": {"timestamps": ts, "values": ["0.5"] * len(ts)}}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def go(client, conn):
    return backfill_endpoint(HTTP, now=NOW, client=client, conn=conn, token="t", sleep=lambda s: None, pause_seconds=0)


@pytest.fixture
def clean(db_conn):
    db_conn.execute("DELETE FROM silver.metrics_hourly")
    db_conn.execute("DELETE FROM bronze.raw_api_responses")


@pytest.mark.integration
def test_backfill_stops_when_api_has_no_older_data(db_conn, clean):
    calls = []
    floor = NOW - D(days=60)
    results = go(api(floor, calls), db_conn)
    assert 2 <= len(calls) <= 15
    assert earliest_ts("http_traffic", conn=db_conn) == floor
    assert results[-1].status in ("ok", "empty")


@pytest.mark.integration
def test_backfill_stops_when_chunk_is_completely_empty(db_conn, clean):
    calls = []
    results = go(api(NOW - D(days=20), calls), db_conn)
    # cửa sổ 1 có dữ liệu; cửa sổ 2 chỉ chồng 2 ngày (floor nằm sau) hoặc rỗng -> dừng sớm
    assert len(calls) <= 3
    assert results[-1].status in ("ok", "empty")


@pytest.mark.integration
def test_backfill_is_resumable(db_conn, clean):
    start = NOW - D(days=10)
    pts = {start + D(hours=h): 0.5 for h in range(0, 10 * 24 + 1)}
    upsert_metrics("http_traffic", pts, conn=db_conn)
    calls = []
    go(api(NOW - D(days=40), calls), db_conn)
    first_start, first_end = calls[0]
    assert first_end == start + D(days=2)
    assert first_end - first_start == D(days=28)


@pytest.mark.integration
def test_backfill_stops_on_error_without_raising(db_conn, clean):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"success": False})))
    results = go(client, db_conn)
    assert len(results) == 1 and results[0].status == "error"


@pytest.mark.integration
def test_backfill_loop_has_hard_iteration_cap(db_conn, clean):
    calls = []
    always = (NOW - D(days=1), NOW)  # API luôn trả đúng đoạn mới nhất, earliest không lùi
    go(api(NOW - D(days=400), calls, always=always), db_conn)
    assert len(calls) <= 20
