"""Validate Keycloak access tokens against a fixed issuer, audience and JWKS."""

from functools import lru_cache
from typing import Annotated, Any

import jwt
from common.config import settings
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=8)
def jwks_client(url: str, timeout: int) -> jwt.PyJWKClient:
    # Cache the JWK set for five minutes, not individual keys indefinitely.
    return jwt.PyJWKClient(url, cache_keys=False, lifespan=300, timeout=timeout)


def unauthorized() -> HTTPException:
    return HTTPException(
        401,
        "Missing, expired or invalid access token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> dict[str, Any]:
    if not settings.auth_enabled:
        return {"username": "development", "roles": ["viewer", "admin"]}
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    token = credentials.credentials
    if len(token) > 16384:
        raise unauthorized()
    try:
        header = jwt.get_unverified_header(token)
        if (
            header.get("alg") != "RS256"
            or not isinstance(header.get("kid"), str)
            or not header["kid"]
        ):
            raise unauthorized()
    except jwt.InvalidTokenError:
        raise unauthorized() from None
    if not settings.keycloak_issuer or not settings.keycloak_audience:
        raise HTTPException(503, "Authentication is not configured")
    url = (
        settings.keycloak_jwks_url
        or settings.keycloak_issuer.rstrip("/") + "/protocol/openid-connect/certs"
    )
    try:
        key = jwks_client(url, settings.jwks_timeout_seconds).get_signing_key_from_jwt(
            token
        )
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(503, "Authentication provider is unavailable") from None
    except jwt.PyJWKClientError:
        raise unauthorized() from None
    except jwt.InvalidTokenError:
        raise unauthorized() from None
    except (jwt.PyJWKError, jwt.PyJWKSetError, ValueError, OSError):
        raise HTTPException(
            503, "Authentication provider returned invalid keys"
        ) from None
    try:
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=settings.keycloak_issuer,
            audience=settings.keycloak_audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        # ID and refresh tokens must not be accepted as API access tokens.
        if claims.get("typ") != "Bearer":
            raise unauthorized()
        realm = claims.get("realm_access", {})
        roles = realm.get("roles", []) if isinstance(realm, dict) else []
        if not isinstance(roles, list) or not all(
            isinstance(role, str) for role in roles
        ):
            raise unauthorized()
        return {
            "username": claims.get("preferred_username", claims["sub"]),
            "roles": roles,
            "sub": claims["sub"],
        }
    except (jwt.InvalidTokenError, TypeError, ValueError, OverflowError):
        raise unauthorized() from None


def require_user(
    user: Annotated[dict[str, Any], Depends(current_user)],
) -> dict[str, Any]:
    if not {"viewer", "admin"}.intersection(user["roles"]):
        raise HTTPException(403, "Viewer or Admin role is required")
    return user


def require_admin(
    user: Annotated[dict[str, Any], Depends(require_user)],
) -> dict[str, Any]:
    if "admin" not in user["roles"]:
        raise HTTPException(403, "Admin role is required")
    return user
