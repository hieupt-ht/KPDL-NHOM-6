"""Điểm vào dịch vụ phân cụm."""

from common.config import settings
from common.runner import create_service_app
from tasks import run_all

app = create_service_app("clustering", run_all, {
    "trigger": "cron", "hour": settings.clustering_cron_hour,
    "minute": settings.clustering_cron_minute, "timezone": settings.tz_local,
})
