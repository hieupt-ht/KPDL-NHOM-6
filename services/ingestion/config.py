"""Cấu hình và hằng số của dịch vụ ingestion."""

import os

BACKFILL_TARGET_DAYS = 365
CHUNK_DAYS = 28
OVERLAP_DAYS = 2


class ConfigError(RuntimeError):
    """Cấu hình thiếu hoặc sai (không bao giờ chứa giá trị bí mật)."""


def get_token() -> str:
    token = os.environ.get("CF_API_TOKEN", "").strip()
    if not token or token.startswith("replace-with"):
        raise ConfigError("CF_API_TOKEN chưa được cấu hình (thiếu hoặc còn giá trị mẫu)")
    return token
