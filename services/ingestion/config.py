"""Cấu hình và hằng số của dịch vụ ingestion."""

import os

# Độ sâu backfill (ngày). Mặc định 365; đặt biến môi trường BACKFILL_TARGET_DAYS để lấy sâu hơn.
# Backfill tự dừng khi Radar hết dữ liệu cũ nên đặt lớn là an toàn.
BACKFILL_TARGET_DAYS = int(os.environ.get("BACKFILL_TARGET_DAYS") or 365)
CHUNK_DAYS = 28
OVERLAP_DAYS = 2


class ConfigError(RuntimeError):
    """Cấu hình thiếu hoặc sai (không bao giờ chứa giá trị bí mật)."""


def get_token() -> str:
    token = os.environ.get("CF_API_TOKEN", "").strip()
    if not token or token.startswith("replace-with"):
        raise ConfigError("CF_API_TOKEN chưa được cấu hình (thiếu hoặc còn giá trị mẫu)")
    return token
