"""Exercise NextAuth cookies/callbacks against the real frontend and Keycloak."""

import os
import time
from urllib.parse import urlparse

import httpx
import pytest
from test_keycloak_e2e import LoginForm


class BrowserNetwork(httpx.BaseTransport):
    """Preserve public browser URLs/cookies while connecting inside Compose."""

    def __init__(self):
        self.transport = httpx.HTTPTransport(trust_env=False)

    def handle_request(self, request):
        targets = {3000: "frontend", 8000: "api", 8080: "keycloak"}
        target = request.url
        if target.host == "localhost" and target.port in targets:
            target = target.copy_with(host=targets[target.port])
        return self.transport.handle_request(
            httpx.Request(
                request.method,
                target,
                headers=request.headers,
                content=request.read(),
                extensions=request.extensions,
            )
        )

    def close(self):
        self.transport.close()


@pytest.mark.keycloak
@pytest.mark.parametrize("username,role", [("demo", "viewer"), ("admin", "admin")])
def test_real_frontend_session_roles_jobs_and_logout(username, role):
    frontend = os.environ.get("TEST_FRONTEND_URL")
    if not frontend:
        pytest.skip("Requires the application Compose frontend in API mode")
    password = os.environ[
        f"TEST_KEYCLOAK_{'DEMO' if role == 'viewer' else 'ADMIN'}_PASSWORD"
    ]
    with httpx.Client(
        transport=BrowserNetwork(), timeout=30, follow_redirects=False
    ) as browser:
        csrf = browser.get(frontend + "/api/auth/csrf")
        assert csrf.status_code == 200, "Frontend CSRF endpoint failed"
        signin = browser.post(
            frontend + "/api/auth/signin/keycloak",
            data={
                "csrfToken": csrf.json()["csrfToken"],
                "callbackUrl": frontend + "/",
                "json": "true",
            },
        )
        assert signin.status_code == 200, "Frontend did not start OIDC login"
        page = browser.get(signin.json()["url"])
        assert page.status_code == 200
        form = LoginForm()
        form.feed(page.text)
        assert form.action, "Keycloak login form missing"
        # Emulate browsers' localhost Secure-cookie exception for this HTTP fixture.
        for cookie in browser.cookies.jar:
            if cookie.domain in {"localhost", "localhost.local"}:
                cookie.secure = False
        authenticated = browser.post(
            form.action,
            data={"username": username, "password": password, "credentialId": ""},
        )
        assert authenticated.status_code == 302, "Keycloak login failed"
        callback = browser.get(authenticated.headers["location"])
        assert callback.status_code == 302, "NextAuth callback failed"
        assert "error=" not in callback.headers["location"], (
            "NextAuth rejected callback"
        )
        session = browser.get(frontend + "/api/auth/session")
        assert session.status_code == 200
        payload = session.json()
        assert payload.get("accessToken"), "Session lacks a validated access token"
        assert role in payload["roles"]
        for private in (
            "refreshToken",
            "refresh_token",
            "idToken",
            "id_token",
            "clientSecret",
        ):
            assert private not in payload
        headers = {"Authorization": "Bearer " + payload["accessToken"]}
        api = "http://localhost:8000"
        assert (
            browser.get(api + "/api/me", headers=headers).json()["username"] == username
        )
        admin_page = browser.get(frontend + "/admin")
        if role == "viewer":
            # App Router can stream the shell before the async session lookup.
            # In that case Next.js delivers its redirect through the HTML stream.
            if admin_page.status_code == 307:
                assert "access=denied" in admin_page.headers["location"]
            else:
                assert admin_page.status_code == 200
                assert "NEXT_REDIRECT;replace;/?access=denied;307;" in admin_page.text
            assert (
                browser.post(
                    api + "/api/jobs/analysis/run", headers=headers
                ).status_code
                == 403
            )
            assert (
                browser.get(api + "/api/jobs/runs/1", headers=headers).status_code
                == 403
            )
        else:
            assert admin_page.status_code == 200
            accepted = browser.post(api + "/api/jobs/analysis/run", headers=headers)
            assert accepted.status_code == 202
            run_id = accepted.json()["run_id"]
            deadline = time.monotonic() + 30
            while True:
                run = browser.get(api + f"/api/jobs/runs/{run_id}", headers=headers)
                assert run.status_code == 200
                assert run.json()["id"] == run_id
                if run.json()["status"] != "running" or time.monotonic() >= deadline:
                    break
                time.sleep(0.2)
            assert run.json()["status"] in {"success", "failed", "partial", "skipped"}
        assert (
            browser.post(
                frontend + "/api/logout-url",
                headers={"Origin": "https://foreign.example"},
            ).status_code
            == 403
        )
        logout = browser.post(
            frontend + "/api/logout-url", headers={"Origin": frontend}
        )
        assert logout.status_code == 200
        target = urlparse(logout.json()["url"])
        assert target.netloc == "localhost:8080"
        csrf_token = browser.get(frontend + "/api/auth/csrf").json()["csrfToken"]
        signed_out = browser.post(
            frontend + "/api/auth/signout",
            data={"csrfToken": csrf_token, "json": "true"},
        )
        assert signed_out.status_code == 200
        assert not browser.get(frontend + "/api/auth/session").json().get("accessToken")
        provider_logout = browser.get(logout.json()["url"])
        assert provider_logout.status_code == 302
        assert provider_logout.headers["location"] == frontend + "/"
