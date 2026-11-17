"""Kiểm thử tích hợp dịch vụ FastAPI và Runner (Service Integration)."""

from unittest.mock import patch
from main import app


def test_health_endpoint():
    # Kiểm tra route /health được sinh ra từ runner
    health_route = next(r for r in app.routes if getattr(r, "path", None) == "/health")
    result = health_route.endpoint()
    assert result == {"status": "ok", "service": "analysis"}


def test_trigger_run_endpoint():
    # Kiểm tra route POST /run đã được ghi đè bởi analysis để thực thi run_all
    run_route = next(
        r for r in app.routes if getattr(r, "path", None) == "/run" and "POST" in getattr(r, "methods", set())
    )
    with patch("main.run_all") as mock_run_all:
        result = run_route.endpoint()
        assert result == {"status": "ok", "service": "analysis"}
        mock_run_all.assert_called_once()
