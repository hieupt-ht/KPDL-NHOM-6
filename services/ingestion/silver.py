"""Chuẩn hóa dữ liệu chỉ số vào Silver."""

from datetime import datetime
from typing import Any


def parse_response(metric: str, payload: dict[str, Any]) -> list[tuple[datetime, str, float]]:
    """Tách mốc UTC và giá trị hợp lệ từ JSON Radar."""
    raise NotImplementedError


def upsert_metrics(rows: list[tuple[datetime, str, float]]) -> None:
    """Ghi các mốc chỉ số vào Silver, cập nhật bản ghi đã tồn tại."""
    raise NotImplementedError
