"""Behavior tests for validation/errors and real PostgreSQL query results."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest
from common.config import settings
from dependencies import get_mart
from main import app


def test_health_and_openapi(client):
    assert client.get("/health").json() == {"status": "ok", "service": "api"}
    schema = client.get("/openapi.json").json()
    assert "TimeseriesPoint" in schema["components"]["schemas"]
    assert "/run" not in schema["paths"]


@pytest.mark.parametrize(
    "query",
    [
        "metric=unknown&granularity=day",
        "metric=http_traffic&granularity=hour",
        "metric=http_traffic&granularity=day&start=2026-11-01",
        "metric=http_traffic&granularity=day&start=invalid",
        "metric=http_traffic&granularity=day&start=2026-11-02T00:00:00Z&end=2026-11-01T00:00:00Z",
        "metric=http_traffic&granularity=day&start=2026-11-01T00:00:00Z&end=2026-11-01T00:00:00Z",
        "metric=http_traffic&granularity=day&limit=0",
        "metric=http_traffic&granularity=day&limit=10001",
        "metric=http_traffic&granularity=day&offset=-1",
        "metric=http_traffic%27%3BDELETE%20FROM%20gold.trend%3B--&granularity=day",
    ],
)
def test_invalid_query(client, query):
    app.dependency_overrides[get_mart] = lambda: None
    assert client.get("/api/timeseries?" + query).status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/api/histogram?metric=l7_attack",
        "/api/seasonal?metric=http_traffic&period_type=month",
        "/api/correlation?",
        "/api/status?",
    ],
)
def test_snapshot_rejects_time_filter(client, path):
    response = client.get(path + "&start=2026-11-01T00:00:00Z")
    assert response.status_code == 422
    assert "snapshot" in response.json()["detail"]


def test_unconfigured_database(client, monkeypatch):
    monkeypatch.setattr(settings, "mart_dsn", "")
    assert client.get("/api/correlation").status_code == 503
    assert client.get("/ready").status_code == 503


def test_database_error_is_sanitized(client):
    def broken_database():
        raise psycopg.OperationalError("secret-password internal-host")

    app.dependency_overrides[get_mart] = broken_database
    response = client.get("/api/correlation")
    assert response.status_code == 503
    assert "secret-password" not in response.text
    assert "internal-host" not in response.text


def test_cors_preflight(client):
    response = client.options(
        "/api/timeseries",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_origins_default_and_env(monkeypatch):
    from main import cors_origins

    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert cors_origins() == ["http://localhost:3000"]
    monkeypatch.setenv("CORS_ORIGINS", "")
    assert cors_origins() == ["http://localhost:3000"]
    monkeypatch.setenv(
        "CORS_ORIGINS", " https://web.example.com/ , http://localhost:3000,, "
    )
    assert cors_origins() == ["https://web.example.com", "http://localhost:3000"]


@pytest.mark.integration
def test_timeseries_filters_pagination_and_utc(client, mart):
    url = "/api/timeseries?metric=http_traffic&granularity=day"
    response = client.get(url + "&limit=1&offset=1")
    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "2"
    assert response.headers["X-Offset"] == "1"
    assert response.json()[0]["mean"] == 0.6
    assert response.json()[0]["ts"].endswith("Z")
    response = client.get(
        url + "&start=2026-11-01T07:00:00%2B07:00&end=2026-11-02T00:00:00Z"
    )
    assert [row["mean"] for row in response.json()] == [0.3]
    assert client.get(url + "&offset=99").status_code == 404


@pytest.mark.integration
@pytest.mark.parametrize(
    "url,field,expected",
    [
        ("/api/histogram?metric=l7_attack", "count", [2, 3]),
        ("/api/trend?metric=http_traffic&granularity=week", "trend_value", [None, 0.6]),
        ("/api/seasonal?metric=http_traffic&period_type=hour_of_day", "bucket", [0, 1]),
        ("/api/correlation", "coef", [0.7, None]),
        ("/api/clusters", "cluster_id", [0, 1]),
    ],
)
def test_analysis_and_cluster_outputs(client, mart, url, field, expected):
    response = client.get(url)
    assert response.status_code == 200, response.text
    assert [row[field] for row in response.json()] == expected


@pytest.mark.integration
def test_cluster_calendar_dates(client, mart):
    response = client.get(
        "/api/clusters",
        params={
            "start": "2026-10-31T17:00:00Z",
            "end": "2026-11-01T17:00:00Z",
        },
    )
    assert [row["date"] for row in response.json()] == ["2026-11-01"]


@pytest.mark.integration
def test_forecasts_use_tomorrow_and_explicit_window(client, mart):
    tomorrow = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date() + timedelta(days=1)
    for kind in ("continuous", "discrete"):
        response = client.get("/api/forecast/" + kind)
        assert response.status_code == 200, response.text
        assert response.json()["target_date"] == tomorrow.isoformat()
    response = client.get(
        "/api/forecast/continuous",
        params={
            "start": "2026-11-01T00:00:00+07:00",
            "end": "2026-11-03T00:00:00+07:00",
        },
    )
    assert response.json()["target_date"] == "2026-11-02"
    mart.execute(
        "DELETE FROM gold.forecast_continuous WHERE model_name='fixture-tomorrow'"
    )
    assert client.get("/api/forecast/continuous").status_code == 404


@pytest.mark.integration
def test_status_latest_run_and_empty_state(client, mart):
    response = client.get("/api/status")
    assert response.status_code == 200
    runs = response.json()["service_runs"]
    assert len(runs) == 2
    assert runs[0]["status"] == "failed"
    assert response.json()["data_freshness"]["latest_silver_ts"].startswith(
        "2026-11-02"
    )
    mart.execute("TRUNCATE gold.service_runs, gold.data_freshness")
    assert client.get("/api/status").json() == {
        "service_runs": [],
        "data_freshness": None,
    }


@pytest.mark.integration
def test_empty_gold_and_readiness(client, mart):
    mart.execute("TRUNCATE gold.histogram")
    assert client.get("/api/histogram?metric=l7_attack").status_code == 404
    assert client.get("/ready").status_code == 200


@pytest.mark.integration
def test_database_user_cannot_write(client, mart):
    with psycopg.connect(settings.mart_dsn, autocommit=True) as connection:
        assert (
            connection.execute("SELECT count(*) FROM gold.histogram").fetchone()[0] == 2
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("DELETE FROM gold.histogram")


@pytest.mark.integration
def test_dependency_transaction_is_read_only(client, mart):
    iterator = get_mart()
    connection = next(iterator)
    try:
        assert (
            connection.execute("SHOW transaction_read_only").fetchone()[
                "transaction_read_only"
            ]
            == "on"
        )
    finally:
        iterator.close()
