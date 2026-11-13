"""Đặc trưng đầu vào cho hai mô hình dự báo."""

from typing import Any


def build_features() -> dict[str, Any]:
    """Tạo lag, trung bình trượt và thứ trong tuần từ Silver."""
    raise NotImplementedError
