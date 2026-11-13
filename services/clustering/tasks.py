"""Các tác vụ phân cụm trạng thái từng ngày."""

from typing import Any


def build_daily_features() -> list[dict[str, Any]]:
    """Tổng hợp đặc trưng traffic, tấn công và bot theo ngày Việt Nam."""
    raise NotImplementedError


def assign_clusters() -> None:
    """Nạp mô hình có sẵn, gán cụm và ghi kết quả Gold."""
    raise NotImplementedError


def run_all() -> None:
    """Chạy quy trình phân cụm và ghi nhật ký service_runs."""
    raise NotImplementedError
