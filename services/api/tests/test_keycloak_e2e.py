"""Real Keycloak authorization-code + PKCE flow, then real container API calls."""

import base64
import hashlib
import os
import secrets
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import httpx
import pytest


class LoginForm(HTMLParser):
    action = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "form" and values.get("id") == "kc-form-login":
            self.action = values.get("action")


@pytest.fixture(scope="module")
def keycloak_stack():
    url = os.environ.get("TEST_KEYCLOAK_URL")
    if not url:
        pytest.skip("Set TEST_KEYCLOAK_URL to run real Keycloak/API checks")
    # Tests deliberately use only the explicitly configured test stack.
    api = os.environ.get("TEST_API_URL", "http://127.0.0.1:8000")
    secret = os.environ["TEST_KEYCLOAK_CLIENT_SECRET"]

    def login(username, password):
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        state = secrets.token_urlsafe(24)
        callback = "http://localhost:3000/api/auth/callback/keycloak"
        with httpx.Client(
            timeout=15, trust_env=False, follow_redirects=False
        ) as browser:
            page = browser.get(
                url + "/protocol/openid-connect/auth",
                params={
                    "client_id": "dashboard",
                    "response_type": "code",
                    "scope": "openid profile email",
                    "redirect_uri": callback,
                    "state": state,
                    "nonce": secrets.token_urlsafe(24),
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
            )
            assert page.status_code == 200, "Keycloak authorization page unavailable"
            form = LoginForm()
            form.feed(page.text)
            assert form.action, "Keycloak did not present the login form"
            # Keycloak marks localhost cookies Secure. Browsers treat localhost
            # as trustworthy, while httpx's cookie jar requires HTTPS. Emulate
            # the browser exception only for this loopback HTTP test fixture.
            if urlparse(url).scheme == "http" and urlparse(url).hostname in {
                "localhost",
                "127.0.0.1",
            }:
                for cookie in browser.cookies.jar:
                    cookie.secure = False
            result = browser.post(
                form.action,
                data={"username": username, "password": password, "credentialId": ""},
            )
            assert result.status_code == 302, (
                "Keycloak login did not issue authorization code"
            )
            query = parse_qs(urlparse(result.headers["location"]).query)
            assert query.get("state") == [state]
            assert "code" in query, "Keycloak returned an authorization error"
            exchange = browser.post(
                url + "/protocol/openid-connect/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": "dashboard",
                    "client_secret": secret,
                    "redirect_uri": callback,
                    "code": query["code"][0],
                    "code_verifier": verifier,
                },
            )
            assert exchange.status_code == 200, (
                "Keycloak authorization-code exchange failed"
            )
            return exchange.json()

    return api, login


@pytest.mark.keycloak
def test_real_viewer_and_admin_roles_and_id_token_rejection(keycloak_stack):
    api, login = keycloak_stack
    with httpx.Client(timeout=15, trust_env=False) as client:
        assert client.get(api + "/api/me").status_code == 401
        for username, variable, role in [
            ("demo", "TEST_KEYCLOAK_DEMO_PASSWORD", "viewer"),
            ("admin", "TEST_KEYCLOAK_ADMIN_PASSWORD", "admin"),
        ]:
            tokens = login(username, os.environ[variable])
            headers = {"Authorization": "Bearer " + tokens["access_token"]}
            response = client.get(api + "/api/me", headers=headers)
            assert response.status_code == 200
            assert role in response.json()["roles"]
            assert client.get(api + "/api/status", headers=headers).status_code == 200
            assert (
                client.get(
                    api + "/api/me",
                    headers={"Authorization": "Bearer " + tokens["id_token"]},
                ).status_code
                == 401
            )
            if role == "viewer":
                assert (
                    client.post(
                        api + "/api/jobs/analysis/run", headers=headers
                    ).status_code
                    == 403
                )


@pytest.mark.keycloak
def test_real_admin_triggers_service_and_reads_failed_stub_run(keycloak_stack):
    api, login = keycloak_stack
    tokens = login("admin", os.environ["TEST_KEYCLOAK_ADMIN_PASSWORD"])
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    with httpx.Client(timeout=15, trust_env=False) as client:
        for service in ("analysis", "clustering", "prediction"):
            response = client.post(api + f"/api/jobs/{service}/run", headers=headers)
            assert response.status_code == 202, f"Cannot trigger {service}"
            run_id = response.json()["run_id"]
            for _ in range(30):
                status = client.get(api + "/api/status", headers=headers)
                assert status.status_code == 200
                row = next(
                    (
                        row
                        for row in status.json()["service_runs"]
                        if row["id"] == run_id
                    ),
                    None,
                )
                if row and row["status"] != "running":
                    break
                time.sleep(0.1)
            assert row and row["status"] == "failed", (
                "Current Analysis/ML tasks are stubs and must report failure"
            )
            assert row["error"] == "Job implementation is not available yet"
        for port in (8001, 8002, 8003):
            assert client.post(f"http://127.0.0.1:{port}/run").status_code == 401
