"""Public job proxy tests: fixed destinations, no retries and sanitized failures."""

import httpx
import pytest
from common.config import settings
from pydantic import SecretStr


@pytest.fixture
def upstream(monkeypatch):
    original = httpx.Client

    def install(handler):
        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
        )

    return install


def test_any_client_can_trigger_job_and_sends_internal_token(
    client, upstream, monkeypatch
):
    monkeypatch.setattr(settings, "job_trigger_token", SecretStr("internal-test-token"))

    def handler(request):
        assert request.method == "POST"
        assert str(request.url) == "http://analysis:8001/run"
        assert request.headers["X-Job-Token"] == "internal-test-token"
        return httpx.Response(
            202, json={"service": "analysis", "run_id": 10, "status": "accepted"}
        )

    upstream(handler)
    response = client.post(
        "/api/jobs/analysis/run",
    )
    assert response.status_code == 202
    assert response.json()["run_id"] == 10


@pytest.mark.parametrize(
    "code,expected",
    [(409, 409), (503, 503), (401, 502), (500, 502), (501, 502), (200, 502)],
)
def test_upstream_errors_are_sanitized(client, upstream, code, expected):
    upstream(lambda request: httpx.Response(code, json={"detail": "private-secret"}))
    response = client.post("/api/jobs/prediction/run")
    assert response.status_code == expected
    assert "private-secret" not in response.text


@pytest.mark.parametrize(
    "kind,expected", [(httpx.ConnectError, 503), (httpx.ReadTimeout, 504)]
)
def test_connection_failure_and_timeout_not_retried(client, upstream, kind, expected):
    calls = []

    def handler(request):
        calls.append(request)
        raise kind("private-secret", request=request)

    upstream(handler)
    response = client.post("/api/jobs/clustering/run")
    assert response.status_code == expected
    assert len(calls) == 1
    assert "private-secret" not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"service": "prediction", "run_id": 1, "status": "accepted"},
        {"service": "analysis", "run_id": 0, "status": "accepted"},
    ],
)
def test_invalid_upstream_body(client, upstream, payload):
    upstream(lambda request: httpx.Response(202, json=payload))
    assert client.post("/api/jobs/analysis/run").status_code == 502


def test_missing_internal_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "job_trigger_token", SecretStr(""))
    response = client.post(
        "/api/jobs/analysis/run",
    )
    assert response.status_code == 503


def test_arbitrary_service_is_rejected(client):
    assert client.post("/api/jobs/other/run").status_code == 422


@pytest.mark.integration
def test_exact_job_run_and_missing_id(client, mart):
    response = client.get("/api/jobs/runs/1")
    assert response.status_code == 200
    assert response.json()["id"] == 1
    assert response.json()["service"] == "analysis"
    assert response.json()["status"] == "success"
    assert client.get("/api/jobs/runs/999999").status_code == 404
    assert client.get("/api/jobs/runs/0").status_code == 422
