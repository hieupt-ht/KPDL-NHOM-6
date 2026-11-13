"""Ghi dữ liệu thô vào Warehouse."""

from typing import Any


def save_raw_response(endpoint: str, params: dict[str, Any], status_code: int, payload: dict[str, Any]) -> None:
    """Lưu nguyên văn JSON và metadata của phản hồi API vào Bronze."""
    raise NotImplementedError
