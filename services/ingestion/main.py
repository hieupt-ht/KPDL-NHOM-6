"""Điểm vào dịch vụ thu thập dữ liệu."""

from common.config import settings
from common.runner import create_service_app


def run_cycle() -> None:
    """Gọi các endpoint Radar rồi ghi phản hồi vào Bronze và dữ liệu sạch vào Silver."""
    raise NotImplementedError


def backfill_if_empty() -> None:
    """Nạp lại 12 tháng dữ liệu theo lô 7 ngày khi Silver còn trống."""
    raise NotImplementedError


app = create_service_app("ingestion", run_cycle, {"trigger": "interval", "seconds": settings.ingestion_interval_seconds})
