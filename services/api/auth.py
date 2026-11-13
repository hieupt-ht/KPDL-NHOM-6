"""Dependency xác thực dành cho giai đoạn dựng khung."""

from typing import Any

from common.config import settings


def require_user() -> dict[str, Any]:
    """Trả user demo khi tắt auth; sau này xác minh JWT của Keycloak."""
    if not settings.auth_enabled:
        return {"username": "demo", "roles": ["viewer"]}
    raise NotImplementedError


def require_admin() -> dict[str, Any]:
    """Trả admin demo khi tắt auth; sau này kiểm tra role admin trong JWT."""
    if not settings.auth_enabled:
        return {"username": "admin", "roles": ["admin"]}
    raise NotImplementedError
