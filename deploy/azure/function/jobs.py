"""Gọi POST /run của các service backend chạy trên Azure Container Apps.

Azure Functions chỉ là bộ hẹn giờ: logic, khóa chạy và nhật ký gold.service_runs vẫn do
common.runner của từng service quản lý. Token nội bộ không bao giờ được ghi log.
"""

import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable

log = logging.getLogger(__name__)

SERVICES = ("analysis", "clustering", "prediction")
# Container Apps có thể đang khởi động lạnh (nạp pandas/scikit-learn) nên chờ rộng hơn timeout của API.
TIMEOUT_SECONDS = 90


def service_url(service: str) -> str:
    if service not in SERVICES:
        raise ValueError(f"Service không hợp lệ: {service}")
    base = os.environ.get(f"{service.upper()}_URL", "").strip().rstrip("/")
    if not base:
        raise RuntimeError(f"Thiếu app setting {service.upper()}_URL")
    return base


def trigger(service: str, opener: Callable = urllib.request.urlopen) -> int:
    """Gửi lệnh chạy một lượt. 202 là đã nhận, 409 là service đang có job (bỏ qua, không lỗi).

    Không tự thử lại khi timeout: yêu cầu có thể đã được nhận (xem docs/frontend-live-integration.md).
    """
    token = os.environ.get("JOB_TRIGGER_TOKEN", "")
    if not token:
        raise RuntimeError("Thiếu app setting JOB_TRIGGER_TOKEN")
    request = urllib.request.Request(
        service_url(service) + "/run", method="POST", headers={"X-Job-Token": token}
    )
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    if status == 202:
        log.info("%s: đã nhận lệnh chạy", service)
    elif status == 409:
        log.info("%s: đang có job chạy, bỏ qua lượt này", service)
    else:
        raise RuntimeError(f"{service} trả HTTP {status}")
    return status
