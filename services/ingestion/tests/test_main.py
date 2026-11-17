import logging

import pytest

import main
from config import ConfigError
from metrics import ENDPOINTS
from pipeline import EndpointResult
from radar_client import Window

SECRET = "cfut_SECRET_TOKEN_VALUE"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("CF_API_TOKEN", SECRET)
    log = {"finish": [], "calls": []}
    monkeypatch.setattr(main, "start_run", lambda: 1)
    monkeypatch.setattr(main, "finish_run", lambda *a, **k: log["finish"].append(a))
    monkeypatch.setattr(main, "purge_old", lambda *a, **k: 0)
    monkeypatch.setattr(main, "polling_window", lambda *a, **k: Window.recent())
    return log


def patch_ingest(monkeypatch, log, behaviour):
    def fake(spec, window, **kw):
        log["calls"].append(spec.name)
        return behaviour(spec)

    monkeypatch.setattr(main, "ingest_endpoint", fake)


def ok(spec):
    return EndpointResult(spec.name, "ok", 10)


def test_run_cycle_success_when_all_endpoints_ok(env, monkeypatch):
    patch_ingest(monkeypatch, env, ok)
    assert main.run_cycle() == "success"
    assert env["calls"] == [e.name for e in ENDPOINTS]
    assert env["finish"][0][:3] == (1, "success", 40)


def test_run_cycle_swallows_endpoint_exception_and_records_partial(env, monkeypatch):
    def behaviour(spec):
        if spec.name == "l7_attack":
            raise RuntimeError("boom")
        return ok(spec)

    patch_ingest(monkeypatch, env, behaviour)
    assert main.run_cycle() == "partial"
    assert env["calls"] == [e.name for e in ENDPOINTS]  # các endpoint khác vẫn được gọi
    assert env["finish"][0][1] == "partial"


def test_run_cycle_failed_when_nothing_ok(env, monkeypatch):
    patch_ingest(monkeypatch, env, lambda s: EndpointResult(s.name, "error", 0, "HTTP 500"))
    assert main.run_cycle() == "failed"
    assert env["finish"][0][1] == "failed"


def test_run_cycle_config_error_logged_not_raised(env, monkeypatch, caplog):
    def behaviour(spec):
        raise ConfigError("CF_API_TOKEN chưa được cấu hình")

    patch_ingest(monkeypatch, env, behaviour)
    with caplog.at_level(logging.INFO):
        assert main.run_cycle() == "failed"
    assert env["finish"][0][1] == "failed"
    assert "CF_API_TOKEN" in env["finish"][0][3]
    assert SECRET not in env["finish"][0][3]


def test_run_cycle_survives_db_failure(env, monkeypatch):
    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(main, "start_run", broken)
    patch_ingest(monkeypatch, env, ok)
    assert main.run_cycle() == "failed"  # không ném ra ngoài scheduler


def test_run_cycle_skips_while_lock_held(env, monkeypatch):
    patch_ingest(monkeypatch, env, ok)
    with main.ingest_lock:
        assert main.run_cycle() == "skipped"
    assert env["calls"] == [] and env["finish"] == []


def test_lock_released_after_cycle(env, monkeypatch):
    patch_ingest(monkeypatch, env, ok)
    main.run_cycle()
    assert not main.ingest_lock.locked()


def test_run_cycle_never_logs_token(env, monkeypatch, caplog):
    patch_ingest(monkeypatch, env, lambda s: EndpointResult(s.name, "error", 0, "HTTP 401"))
    with caplog.at_level(logging.DEBUG):
        main.run_cycle()
    assert SECRET not in caplog.text


def test_backfill_done_logic():
    done = {"a": [EndpointResult("a", "ok", 1)], "b": [], "c": [EndpointResult("c", "empty", 0)]}
    assert main.backfill_done(done)
    assert not main.backfill_done({"a": [EndpointResult("a", "error", 0)]})
    assert not main.backfill_done({"a": [EndpointResult("a", "skipped", 0)]})


def test_background_backfill_retries_until_done_and_releases_lock(monkeypatch):
    attempts = []

    def fake_run_backfill(**kw):
        attempts.append(main.ingest_lock.locked())
        status = "error" if len(attempts) < 3 else "ok"
        return {"a": [EndpointResult("a", status, 0)]}

    sleeps = []
    monkeypatch.setattr(main, "run_backfill", fake_run_backfill)
    main.run_backfill_background(sleep=sleeps.append)
    assert attempts == [True, True, True]  # giữ khóa khi đang chạy
    assert len(sleeps) == 2
    assert not main.ingest_lock.locked()


@pytest.mark.integration
def test_polling_window_widens_to_bridge_a_long_outage(db_conn, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from silver import upsert_metrics

    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    db_conn.execute("DELETE FROM silver.metrics_hourly")
    last = now - timedelta(days=5)
    upsert_metrics("http_traffic", {last: 0.5}, conn=db_conn)
    w = main.polling_window(now=now, conn=db_conn)
    assert w.date_start is not None and w.date_start <= last  # chồng lên điểm Silver cuối
    assert w.date_end == now


@pytest.mark.integration
def test_polling_window_is_recent_when_silver_is_fresh(db_conn):
    from datetime import datetime, timedelta, timezone

    from silver import upsert_metrics

    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    db_conn.execute("DELETE FROM silver.metrics_hourly")
    for m in ("http_traffic", "l7_attack", "netflows"):
        upsert_metrics(m, {now - timedelta(hours=2): 0.5}, conn=db_conn)
    assert main.polling_window(now=now, conn=db_conn).date_range == "2d"


@pytest.mark.integration
def test_polling_window_is_recent_when_silver_empty(db_conn):
    db_conn.execute("DELETE FROM silver.metrics_hourly")
    assert main.polling_window(conn=db_conn).date_range == "2d"
