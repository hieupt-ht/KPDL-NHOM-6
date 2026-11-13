"""Điểm vào dịch vụ dự báo."""

from common.config import settings
from common.runner import create_service_app
from tasks import run_all

app = create_service_app("prediction", run_all, {"trigger": "interval", "seconds": settings.prediction_interval_seconds})
