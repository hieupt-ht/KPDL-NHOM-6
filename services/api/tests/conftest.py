"""Integration tests require an explicitly named, disposable test database."""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jwt
import psycopg
import pytest
from auth import jwks_client
from common.config import settings
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from main import app
from psycopg.conninfo import conninfo_to_dict


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    try:
        with TestClient(app) as instance:
            yield instance
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def mart(monkeypatch):
    admin_dsn = os.environ.get("TEST_MART_ADMIN_DSN")
    api_dsn = os.environ.get("TEST_MART_API_DSN")
    if not admin_dsn or not api_dsn:
        pytest.skip(
            "Set TEST_MART_ADMIN_DSN and TEST_MART_API_DSN for integration tests"
        )
    database = conninfo_to_dict(admin_dsn).get("dbname", "")
    if (
        not database.startswith("test_")
        or conninfo_to_dict(api_dsn).get("dbname") != database
    ):
        pytest.fail(
            "Integration tests only operate on the same explicitly named test_* database"
        )
    monkeypatch.setattr(settings, "mart_dsn", api_dsn)
    with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=5) as connection:
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='gold'"
        ).fetchall()
        assert len(tables) == 10, "Initialize the database with db/mart/init first"
        from psycopg import sql

        connection.execute(
            sql.SQL("TRUNCATE {} RESTART IDENTITY").format(
                sql.SQL(", ").join(sql.Identifier("gold", row[0]) for row in tables)
            )
        )
        connection.execute(
            Path(__file__).with_name("seed.sql").read_text(encoding="utf-8")
        )
        yield connection


@pytest.fixture
def issuer(client, monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    key.update(kid="first", alg="RS256", use="sig")
    state = {"keys": [key], "requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"] += 1
            body = json.dumps({"keys": state["keys"]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(
        settings, "keycloak_issuer", "https://issuer.test/realms/cyber-radar"
    )
    monkeypatch.setattr(settings, "keycloak_audience", "cyber-radar-api")
    monkeypatch.setattr(
        settings, "keycloak_jwks_url", f"http://127.0.0.1:{server.server_port}/certs"
    )
    monkeypatch.setattr(settings, "jwks_timeout_seconds", 1)
    jwks_client.cache_clear()

    def token(roles=None, **changes):
        payload = {
            "iss": settings.keycloak_issuer,
            "aud": settings.keycloak_audience,
            "sub": "test-user",
            "iat": int(time.time()) - 1,
            "exp": int(time.time()) + 60,
            "typ": "Bearer",
            "preferred_username": "demo",
            "realm_access": {"roles": roles if roles is not None else ["viewer"]},
        }
        payload.update(changes)
        return jwt.encode(payload, private, algorithm="RS256", headers={"kid": "first"})

    yield {"token": token, "keys": state, "private": private, "server": server}
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    jwks_client.cache_clear()
