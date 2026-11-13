"""Khung FastAPI và APScheduler dùng chung."""

from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException

from common.config import settings
from common.logging import configure_logging


def create_service_app(name: str, job: Callable[[], None], schedule: dict[str, Any]) -> FastAPI:
    """Tạo ứng dụng với healthcheck, route stub và lịch chạy job."""
    configure_logging(name)
    scheduler = BackgroundScheduler(timezone=settings.tz_local)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.scheduler_enabled:
            scheduler.add_job(job, **schedule, id=name, max_instances=1)
            scheduler.start()
        try:
            yield
        finally:
            if scheduler.running:
                scheduler.shutdown(wait=False)

    app = FastAPI(title=name, lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": name}

    @app.post("/run")
    def run() -> None:
        raise HTTPException(status_code=501, detail="Not implemented yet")

    return app
