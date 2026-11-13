"""Các tác vụ phân tích Silver thành Gold."""


def compute_resampled() -> None:
    """Tổng hợp chỉ số theo ngày, tuần và tháng rồi ghi Gold."""
    raise NotImplementedError


def compute_histogram() -> None:
    """Chia các chỉ số cần hiển thị thành 20 khoảng histogram."""
    raise NotImplementedError


def compute_trend() -> None:
    """Tách xu hướng của chuỗi tháng hoặc chuỗi tuần nếu thiếu dữ liệu."""
    raise NotImplementedError


def compute_seasonal() -> None:
    """Tính mùa vụ theo giờ, thứ và tháng theo giờ Việt Nam."""
    raise NotImplementedError


def compute_correlation() -> None:
    """Tính tương quan Pearson giữa năm chỉ số từ Silver."""
    raise NotImplementedError


def run_all() -> None:
    """Chạy toàn bộ tác vụ phân tích và ghi thời điểm dữ liệu mới nhất."""
    raise NotImplementedError
