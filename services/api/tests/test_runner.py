"""Job runner tests on actual PostgreSQL locks and service_runs records."""

import os
from threading import Event

import pytest
from common.config import settings
from common.runner import create_service_app
from fastapi.testclient import TestClient
from pydantic import SecretStr


@pytest.fixture
def logic(mart, monkeypatch):
    dsn = os.environ.get("TEST_MART_LOGIC_DSN")
    if not dsn:
        pytest.skip("Set TEST_MART_LOGIC_DSN to test the Business Logic writer")
    monkeypatch.setattr(settings, "mart_dsn", dsn)
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    monkeypatch.setattr(settings, "job_trigger_token", SecretStr("runner-test-token"))
    return mart


def make_app(job):
    return create_service_app("analysis", job, {"trigger": "interval", "seconds": 300})


HEADERS = {"X-Job-Token": "runner-test-token"}


@pytest.mark.integration
def test_run_is_async_logged_and_locked_against_scheduler(logic):
    started, release = Event(), Event()

    def job():
        started.set()
        assert release.wait(5)

    app = make_app(job)
    with TestClient(app) as client:
        try:
            response = client.post("/run", headers=HEADERS)
            assert response.status_code == 202
            run_id = response.json()["run_id"]
            assert started.wait(2)
            assert (
                logic.execute(
                    "SELECT status FROM gold.service_runs WHERE id=%s", (run_id,)
                ).fetchone()[0]
                == "running"
            )
            assert client.post("/run", headers=HEADERS).status_code == 409
            # Same execution path used by the scheduler, not another local lock.
            app.state.runner.scheduled()
        finally:
            release.set()
        assert app.state.runner.idle.wait(3)
    row = logic.execute(
        "SELECT status, finished_at FROM gold.service_runs WHERE id=%s", (run_id,)
    ).fetchone()
    assert row[0] == "success" and row[1] is not None


@pytest.mark.integration
def test_two_workers_share_postgres_lock(logic):
    started, release = Event(), Event()

    def job():
        started.set()
        assert release.wait(5)

    first, second = make_app(job), make_app(lambda: None)
    with TestClient(first) as a, TestClient(second) as b:
        try:
            assert a.post("/run", headers=HEADERS).status_code == 202
            assert started.wait(2)
            assert b.post("/run", headers=HEADERS).status_code == 409
        finally:
            release.set()
        assert first.state.runner.idle.wait(3)
        assert b.post("/run", headers=HEADERS).status_code == 202
        assert second.state.runner.idle.wait(3)


@pytest.mark.integration
@pytest.mark.parametrize(
    "exception,expected",
    [
        (
            RuntimeError("password=private-secret"),
            "Job failed (RuntimeError); inspect service logs",
        ),
        (NotImplementedError(), "Job implementation is not available yet"),
    ],
)
def test_failed_job_is_recorded_and_unlocks(logic, exception, expected):
    def job():
        raise exception

    app = make_app(job)
    with TestClient(app) as client:
        response = client.post("/run", headers=HEADERS)
        assert response.status_code == 202
        assert app.state.runner.idle.wait(3)
        row = logic.execute(
            "SELECT status, error FROM gold.service_runs WHERE id=%s",
            (response.json()["run_id"],),
        ).fetchone()
        assert row == ("failed", expected)
        assert "private-secret" not in row[1]
        assert client.post("/run", headers=HEADERS).status_code == 202
        assert app.state.runner.idle.wait(3)


@pytest.mark.integration
def test_orphaned_running_row_marked_interrupted(logic):
    run_id = logic.execute(
        "INSERT INTO gold.service_runs (service, started_at, status) VALUES ('analysis',now(),'running') RETURNING id"
    ).fetchone()[0]
    app = make_app(lambda: None)
    with TestClient(app) as client:
        assert client.post("/run", headers=HEADERS).status_code == 202
        assert app.state.runner.idle.wait(3)
    assert (
        logic.execute(
            "SELECT status FROM gold.service_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]
        == "interrupted"
    )


@pytest.mark.integration
def test_scheduled_job_is_logged_and_returns_result(logic):
    app = make_app(lambda: "partial")
    with TestClient(app):
        app.state.runner.scheduled()
    assert (
        logic.execute(
            "SELECT status FROM gold.service_runs WHERE service='analysis' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        == "partial"
    )


def test_internal_endpoint_requires_shared_secret(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    monkeypatch.setattr(settings, "job_trigger_token", SecretStr("runner-test-token"))
    app = make_app(lambda: pytest.fail("Unauthorized job executed"))
    with TestClient(app) as client:
        assert client.post("/run").status_code == 401
        assert client.post("/run", headers={"X-Job-Token": "wrong"}).status_code == 401
        monkeypatch.setattr(settings, "job_trigger_token", SecretStr(""))
        assert client.post("/run").status_code == 503


def test_db_unavailable_does_not_accept_job(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    monkeypatch.setattr(settings, "job_trigger_token", SecretStr(""))
    monkeypatch.setattr(settings, "mart_dsn", "")
    app = make_app(lambda: pytest.fail("Job should not run without its journal"))
    with TestClient(app) as client:
        assert client.post("/run").status_code == 503
        assert app.state.runner.idle.is_set()
        assert not app.state.runner.lock.locked()


@pytest.mark.integration
def test_executor_shutdown_does_not_poison_lock(logic, monkeypatch):
    app = make_app(lambda: None)
    with TestClient(app) as client:

        def reject(*args, **kwargs):
            raise RuntimeError("executor stopped")

        monkeypatch.setattr(app.state.runner.executor, "submit", reject)
        assert client.post("/run", headers=HEADERS).status_code == 503
        assert app.state.runner.idle.is_set()
        assert not app.state.runner.lock.locked()
    assert (
        logic.execute(
            "SELECT status FROM gold.service_runs WHERE service='analysis' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        == "failed"
    )
