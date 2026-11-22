"""Fresh HTTP clients can open the dashboard without cookies or login providers."""

import os

import httpx
import pytest


def test_dashboard_routes_open_without_session():
    frontend = os.environ.get("TEST_FRONTEND_URL")
    if not frontend:
        pytest.skip("Requires the application Compose frontend")
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        for path in ("/", "/analysis", "/forecast", "/admin"):
            response = client.get(frontend + path)
            assert response.status_code == 200, (path, response.status_code)
            assert "Vận hành hệ thống" in response.text
            assert "Đăng nhập Keycloak" not in response.text
            assert "Đăng xuất" not in response.text
            assert "Trang dành cho Admin" not in response.text
        assert client.get(frontend + "/api/auth/session").status_code == 404
        assert client.post(frontend + "/api/logout-url").status_code == 404


def test_api_reads_without_bearer_token():
    api = os.environ.get("TEST_API_URL")
    if not api or not os.environ.get("TEST_FRONTEND_URL"):
        pytest.skip("Requires application smoke stack")
    with httpx.Client(timeout=15, trust_env=False) as client:
        assert client.get(api + "/ready").status_code == 200
        assert client.get(api + "/api/status").status_code == 200
        assert client.get(api + "/api/timeseries?metric=http_traffic&granularity=day").status_code in (200, 404)
        assert client.get(api + "/api/me").status_code == 404
