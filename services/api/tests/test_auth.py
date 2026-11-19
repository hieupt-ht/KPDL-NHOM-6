"""Signed JWT tests against a real local JWKS endpoint."""

import json

import jwt
import pytest
from common.config import settings
from cryptography.hazmat.primitives.asymmetric import rsa


def test_viewer_and_admin_can_read_identity(client, issuer):
    for role in ("viewer", "admin"):
        response = client.get(
            "/api/me", headers={"Authorization": "Bearer " + issuer["token"]([role])}
        )
        assert response.status_code == 200
        assert response.json()["roles"] == [role]
    assert issuer["keys"]["requests"] == 1  # JWKS set is cached


@pytest.mark.parametrize(
    "header", [None, "Basic invalid", "Bearer invalid", "Bearer " + "x" * 17000]
)
def test_missing_or_malformed_token(client, issuer, header):
    response = client.get(
        "/api/me", headers={"Authorization": header} if header else {}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "changes",
    [
        {"exp": 1},
        {"exp": None},
        {"iat": 9999999999},
        {"nbf": 9999999999},
        {"iss": "https://wrong.test"},
        {"aud": "dashboard"},
        {"sub": None},
        {"typ": "ID"},
        {"typ": "Refresh"},
        {"realm_access": {"roles": "admin"}},
    ],
)
def test_invalid_claims(client, issuer, changes):
    token = issuer["token"](**changes)
    assert (
        client.get("/api/me", headers={"Authorization": "Bearer " + token}).status_code
        == 401
    )


def test_wrong_signature_algorithm_and_unknown_key(client, issuer):
    token = issuer["token"]()
    claims = jwt.decode(token, options={"verify_signature": False})
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bad_tokens = [
        jwt.encode(claims, wrong_key, algorithm="RS256", headers={"kid": "first"}),
        jwt.encode(claims, "test-secret", algorithm="HS256", headers={"kid": "first"}),
        jwt.encode(
            claims, issuer["private"], algorithm="RS256", headers={"kid": "unknown"}
        ),
    ]
    for bad in bad_tokens:
        assert (
            client.get(
                "/api/me", headers={"Authorization": "Bearer " + bad}
            ).status_code
            == 401
        )


def test_unknown_role_is_forbidden(client, issuer):
    token = issuer["token"](["other"])
    assert (
        client.get("/api/me", headers={"Authorization": "Bearer " + token}).status_code
        == 403
    )


def test_viewer_cannot_trigger_job(client, issuer):
    response = client.post(
        "/api/jobs/analysis/run",
        headers={"Authorization": "Bearer " + issuer["token"]()},
    )
    assert response.status_code == 403


def test_jwks_outage_is_service_unavailable(client, issuer, monkeypatch):
    monkeypatch.setattr(settings, "keycloak_jwks_url", "http://127.0.0.1:1/certs")
    response = client.get(
        "/api/me", headers={"Authorization": "Bearer " + issuer["token"]()}
    )
    assert response.status_code == 503


def test_rotated_key_is_fetched(client, issuer):
    assert (
        client.get(
            "/api/me", headers={"Authorization": "Bearer " + issuer["token"]()}
        ).status_code
        == 200
    )
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    key.update(kid="second", alg="RS256", use="sig")
    issuer["keys"]["keys"] = [key]
    claims = jwt.decode(issuer["token"](), options={"verify_signature": False})
    rotated = jwt.encode(claims, private, algorithm="RS256", headers={"kid": "second"})
    assert (
        client.get(
            "/api/me", headers={"Authorization": "Bearer " + rotated}
        ).status_code
        == 200
    )
    assert issuer["keys"]["requests"] == 2


def test_auth_disabled_is_explicit_development_mode(client):
    assert settings.auth_enabled is False
    assert set(client.get("/api/me").json()["roles"]) == {"viewer", "admin"}


def test_invalid_provider_keyset_is_unavailable(client, issuer):
    issuer["keys"]["keys"] = []
    response = client.get(
        "/api/me", headers={"Authorization": "Bearer " + issuer["token"]()}
    )
    assert response.status_code == 503
