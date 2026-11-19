"""Điểm vào dịch vụ phân tích."""

from common.config import settings
from common.runner import create_service_app
from tasks import run_all

app = create_service_app("analysis", run_all, {"trigger": "interval", "seconds": settings.analysis_interval_seconds})
