"""Kiểm thử tích hợp dịch vụ FastAPI và Runner (Service Integration)."""

from unittest.mock import patch
from main import app


def _find_route(path: str, method: str):
    return next(
        r for r in app.routes
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set())
    )


def test_health_endpoint():
    # Kiểm tra route /health được sinh ra từ runner
    health_route = _find_route("/health", "GET")
    result = health_route.endpoint()
    assert result == {"status": "ok", "service": "analysis"}


def test_trigger_run_endpoint_uses_shared_runner_contract():
    # POST /run phải là endpoint của common.runner: yêu cầu JOB_TRIGGER_TOKEN,
    # trả 202 {"service", "run_id", "status": "accepted"} và ghi gold.service_runs.
    run_route = _find_route("/run", "POST")
    assert run_route.dependant.dependencies, "POST /run phải có dependency xác thực"
    with patch.object(app.state.runner, "submit", return_value=42):
        result = run_route.endpoint()
    assert result == {"service": "analysis", "run_id": 42, "status": "accepted"}
