import io
import urllib.error
from types import SimpleNamespace

import pytest

import jobs


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("JOB_TRIGGER_TOKEN", "secret-token")
    monkeypatch.setenv("ANALYSIS_URL", "https://ca-analysis.example.io/")


def test_trigger_posts_run_with_token_and_accepts_202():
    seen = {}

    def opener(request, timeout):
        seen.update(url=request.full_url, method=request.get_method(), token=request.get_header("X-job-token"), timeout=timeout)
        return FakeResponse(202)

    assert jobs.trigger("analysis", opener=opener) == 202
    assert seen == {"url": "https://ca-analysis.example.io/run", "method": "POST", "token": "secret-token", "timeout": jobs.TIMEOUT_SECONDS}


def test_busy_service_is_not_an_error():
    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 409, "busy", {}, io.BytesIO())

    assert jobs.trigger("analysis", opener=opener) == 409


@pytest.mark.parametrize("status", [401, 502, 503])
def test_other_statuses_fail_without_leaking_token(status):
    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, status, "x", {}, io.BytesIO())

    with pytest.raises(RuntimeError) as error:
        jobs.trigger("analysis", opener=opener)
    assert str(status) in str(error.value)
    assert "secret-token" not in str(error.value)


def test_missing_settings_and_unknown_service(monkeypatch):
    monkeypatch.delenv("JOB_TRIGGER_TOKEN")
    with pytest.raises(RuntimeError, match="JOB_TRIGGER_TOKEN"):
        jobs.trigger("analysis", opener=lambda *a, **k: FakeResponse(202))
    monkeypatch.setenv("JOB_TRIGGER_TOKEN", "t")
    with pytest.raises(RuntimeError, match="PREDICTION_URL"):
        jobs.trigger("prediction", opener=lambda *a, **k: FakeResponse(202))
    with pytest.raises(ValueError):
        jobs.service_url("ingestion")


def test_function_app_registers_schedules_from_the_assignment():
    pytest.importorskip("azure.functions")
    import function_app

    schedules = {f.get_function_name(): f.get_trigger().schedule for f in function_app.app.get_functions()}
    assert schedules == {
        "analysis_every_5_minutes": "0 */5 * * * *",
        "prediction_every_5_minutes": "0 */5 * * * *",
        "clustering_daily": "0 30 17 * * *",
    }
