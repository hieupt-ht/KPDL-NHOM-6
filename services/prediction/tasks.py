"""Các tác vụ dự báo bằng mô hình đã huấn luyện."""


def predict_continuous() -> None:
    """Dự báo chỉ số lưu lượng ngày mai và ghi Gold."""
    raise NotImplementedError


def predict_discrete() -> None:
    """Phân loại rủi ro ngày mai và ghi xác suất vào Gold."""
    raise NotImplementedError


def run_all() -> None:
    """Chạy hai dự báo và ghi nhật ký service_runs."""
    raise NotImplementedError
