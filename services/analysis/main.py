"""Điểm vào dịch vụ phân tích."""

import logging

from common.config import settings
from common.runner import create_service_app
from tasks import run_all

log = logging.getLogger(__name__)

app = create_service_app("analysis", run_all, {"trigger": "interval", "seconds": settings.analysis_interval_seconds})

# Ghi đè endpoint POST /run mặc định (trả về 501) bằng hàm thực thi run_all
for route in list(app.routes):
    if getattr(route, "path", None) == "/run" and "POST" in getattr(route, "methods", set()):
        app.routes.remove(route)


@app.post("/run")
def trigger_run() -> dict[str, str]:
    """Kích hoạt thủ công chu kỳ phân tích Silver -> Gold."""
    log.info("Nhận yêu cầu kích hoạt thủ công POST /run")
    run_all()
    return {"status": "ok", "service": "analysis"}
