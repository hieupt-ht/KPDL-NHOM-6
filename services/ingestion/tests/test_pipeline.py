import copy
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from metrics import ENDPOINTS
from pipeline import ingest_endpoint
from radar_client import Window
from silver import read_range, upsert_metrics

pytestmark = pytest.mark.integration

HTTP = next(e for e in ENDPOINTS if e.name == "http_traffic")
BOT = next(e for e in ENDPOINTS if e.name == "bot_class")
WIN = Window.between(datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 11, 8, tzinfo=timezone.utc))
ALL = (datetime(2000, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc))


@pytest.fixture(autouse=True)
def clean(db_conn):
    # trong giao dịch của test, sẽ được rollback
    db_conn.execute("DELETE FROM silver.metrics_hourly")
    db_conn.execute("DELETE FROM bronze.raw_api_responses")


def client_for(*bodies, status=200):
    it = iter(bodies)
    last = {}

    def handler(req):
        nonlocal last
        try:
            last = next(it)
        except StopIteration:
            pass
        return httpx.Response(status, json=last)

    return httpx.Client(transport=httpx.MockTransport(handler))


def run(spec, client, conn):
    return ingest_endpoint(spec, WIN, client=client, conn=conn, token="t", sleep=lambda s: None)


def bronze_count(conn):
    return conn.execute("SELECT count(*) FROM bronze.raw_api_responses").fetchone()[0]


def silver_count(conn):
    return conn.execute("SELECT count(*) FROM silver.metrics_hourly").fetchone()[0]


def test_first_window_on_empty_silver_writes_with_k_1(db_conn, fixture_json):
    doc = fixture_json("winA")
    res = run(HTTP, client_for(doc), db_conn)
    assert res.status == "ok" and res.rows > 0
    got = read_range("http_traffic", *ALL, conn=db_conn)
    s = doc["result"]["serie_0"]
    first_ts = datetime.fromisoformat(s["timestamps"][0])
    assert got[first_ts] == pytest.approx(float(s["values"][0]))
    assert bronze_count(db_conn) == 1


def test_second_window_is_rescaled_to_silver(db_conn, fixture_json):
    run(HTTP, client_for(fixture_json("winA")), db_conn)
    t = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
    before = read_range("http_traffic", t, t, conn=db_conn)[t]
    assert before == pytest.approx(0.902153, abs=1e-4)
    res = run(HTTP, client_for(fixture_json("winB")), db_conn)
    assert res.status == "ok"
    after = read_range("http_traffic", *ALL, conn=db_conn)
    assert after[t] == pytest.approx(0.902153, abs=1e-4)
    # các mốc mới (sau cuối cửa sổ A) liền mạch: không nhảy so với mốc trước nó
    new = sorted(x for x in after if x > datetime(2026, 11, 8, tzinfo=timezone.utc))
    assert new
    series = [after[x] for x in sorted(after)]
    assert max(abs(a - b) for a, b in zip(series, series[1:])) < 0.35


def test_success_false_payload_writes_bronze_but_no_silver(db_conn):
    res = run(HTTP, client_for({"success": False, "errors": [{"code": 1}], "result": {}}), db_conn)
    assert res.status == "error"
    assert bronze_count(db_conn) == 1 and silver_count(db_conn) == 0


def test_empty_series_reports_empty_and_writes_nothing(db_conn):
    doc = {"success": True, "errors": [], "result": {"serie_0": {"timestamps": [], "values": []}}}
    res = run(HTTP, client_for(doc), db_conn)
    assert res.status == "empty" and silver_count(db_conn) == 0 and bronze_count(db_conn) == 1


def test_all_null_series_is_empty(db_conn):
    doc = {"success": True, "result": {"serie_0": {"timestamps": ["2026-11-01T00:00:00Z"], "values": [None]}}}
    assert run(HTTP, client_for(doc), db_conn).status == "empty"


def test_insufficient_overlap_skips_scaled_metric_but_keeps_bronze(db_conn, fixture_json):
    doc = fixture_json("winA")
    ts = doc["result"]["serie_0"]["timestamps"]
    upsert_metrics("http_traffic", {datetime.fromisoformat(t): 0.5 for t in ts[:5]}, conn=db_conn)
    res = run(HTTP, client_for(doc), db_conn)
    assert res.status == "skipped"
    assert silver_count(db_conn) == 5 and bronze_count(db_conn) == 1


def test_all_zero_overlap_skips_without_exception(db_conn, fixture_json):
    doc = fixture_json("winA")
    ts = doc["result"]["serie_0"]["timestamps"]
    upsert_metrics("http_traffic", {datetime.fromisoformat(t): 0.0 for t in ts}, conn=db_conn)
    res = run(HTTP, client_for(doc), db_conn)
    assert res.status == "skipped"


def test_percentage_metrics_not_rescaled(db_conn, fixture_json):
    doc = fixture_json("bot_class")
    res = run(BOT, client_for(doc), db_conn)
    assert res.status == "ok"
    s = doc["result"]["serie_0"]
    t0 = datetime.fromisoformat(s["timestamps"][0])
    assert read_range("bot_share", t0, t0, conn=db_conn)[t0] == pytest.approx(float(s["bot"][0]))
    assert read_range("human_share", t0, t0, conn=db_conn)[t0] == pytest.approx(float(s["human"][0]))
    # lần hai với dữ liệu khác: vẫn ghi nguyên, không quy đổi
    doc2 = copy.deepcopy(doc)
    doc2["result"]["serie_0"]["bot"] = [str(float(v) / 2) for v in s["bot"]]
    run(BOT, client_for(doc2), db_conn)
    assert read_range("bot_share", t0, t0, conn=db_conn)[t0] == pytest.approx(float(s["bot"][0]) / 2)


def test_http_500_exhausted_records_bronze_and_returns_error(db_conn):
    res = run(HTTP, client_for({"success": False}, status=500), db_conn)
    assert res.status == "error" and silver_count(db_conn) == 0
    assert db_conn.execute("SELECT status_code FROM bronze.raw_api_responses").fetchone()[0] == 500


def test_network_failure_returns_error_without_raising(db_conn):
    def boom(req):
        raise httpx.ConnectError("down", request=req)

    client = httpx.Client(transport=httpx.MockTransport(boom))
    res = run(HTTP, client, db_conn)
    assert res.status == "error"


def test_window_without_overlap_but_silver_not_empty_is_skipped_not_written_raw(db_conn, fixture_json):
    # Silver đã có dữ liệu ở nơi khác -> cửa sổ không chồng không được ghi thô (k=1) vì sẽ lệch thang
    upsert_metrics("http_traffic", {datetime(2020, 1, 1, tzinfo=timezone.utc): 0.5}, conn=db_conn)
    res = run(HTTP, client_for(fixture_json("winA")), db_conn)
    assert res.status == "skipped"
    assert silver_count(db_conn) == 1
