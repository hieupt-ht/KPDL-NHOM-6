"""Shared scheduler/manual execution with one job per service and Gold run logs."""

import hmac
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from threading import Event, Lock
from typing import Annotated, Any

import psycopg
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, Header, HTTPException

from common.config import settings
from common.logging import configure_logging

log = logging.getLogger(__name__)
LOGGED_SERVICES = {"analysis", "clustering", "prediction"}


class JobBusy(Exception):
    pass


class JobUnavailable(Exception):
    pass


def require_job_token(x_job_token: Annotated[str | None, Header()] = None) -> None:
    expected = settings.job_trigger_token.get_secret_value()
    if settings.auth_enabled and not expected:
        raise HTTPException(503, "Internal job authentication is not configured")
    if expected and not hmac.compare_digest(
        expected.encode(), (x_job_token or "").encode()
    ):
        raise HTTPException(401, "Invalid internal job token")


class JobRunner:
    def __init__(self, name: str, job: Callable[[], Any]):
        self.name = name
        self.job = job
        self.lock = Lock()
        self.idle = Event()
        self.idle.set()
        self.executor: ThreadPoolExecutor | None = None

    def reserve(self) -> tuple[psycopg.Connection | None, int | None]:
        if not self.lock.acquire(blocking=False):
            raise JobBusy
        self.idle.clear()
        connection = None
        try:
            if self.name not in LOGGED_SERVICES:
                # Ingestion owns its Warehouse run log and backfill lock.
                return None, None
            if not settings.mart_dsn:
                raise JobUnavailable
            connection = psycopg.connect(
                settings.mart_dsn,
                autocommit=True,
                connect_timeout=settings.db_connect_timeout_seconds,
                options=f"-c statement_timeout={settings.db_statement_timeout_ms}",
            )
            acquired = connection.execute(
                "SELECT pg_try_advisory_lock(126006, hashtext(%s))", (self.name,)
            ).fetchone()[0]
            if not acquired:
                raise JobBusy
            # Only after obtaining the distributed lock can older running rows
            # safely be declared interrupted (e.g. after a worker/container crash).
            connection.execute(
                "UPDATE gold.service_runs SET status='interrupted', finished_at=now(), "
                "error='Previous worker stopped before completion' WHERE service=%s AND status='running'",
                (self.name,),
            )
            run_id = connection.execute(
                "INSERT INTO gold.service_runs (service, started_at, status) "
                "VALUES (%s, now(), 'running') RETURNING id",
                (self.name,),
            ).fetchone()[0]
            return connection, run_id
        except Exception as error:
            if connection is not None:
                connection.close()  # releases any session advisory lock
            self.lock.release()
            self.idle.set()
            if isinstance(error, (JobBusy, JobUnavailable)):
                raise
            log.error("Cannot reserve %s job: %s", self.name, type(error).__name__)
            raise JobUnavailable from None

    def execute(
        self, connection: psycopg.Connection | None, run_id: int | None
    ) -> None:
        status, error_message = "success", None
        try:
            result = self.job()
            if isinstance(result, str) and result in ("failed", "partial", "skipped"):
                status = result
        except NotImplementedError:
            status, error_message = "failed", "Job implementation is not available yet"
            log.warning("%s job has not been implemented", self.name)
        except Exception as error:  # noqa: BLE001 - failed jobs must not kill the scheduler
            status, error_message = (
                "failed",
                f"Job failed ({type(error).__name__}); inspect service logs",
            )
            # Never copy exception text (possibly DSNs/tokens) into public Gold logs.
            log.error("%s job failed: %s", self.name, type(error).__name__)
        finally:
            try:
                if connection is not None:
                    connection.execute(
                        "UPDATE gold.service_runs SET finished_at=now(), status=%s, error=%s WHERE id=%s",
                        (status, error_message, run_id),
                    )
            except psycopg.Error as error:
                log.error(
                    "Cannot finish %s run log: %s", self.name, type(error).__name__
                )
            finally:
                if connection is not None:
                    connection.close()
                self.lock.release()
                self.idle.set()

    def submit(self) -> int | None:
        executor = self.executor
        if executor is None:
            raise JobUnavailable
        connection, run_id = self.reserve()
        try:
            executor.submit(self.execute, connection, run_id)
        except RuntimeError:
            # Executor is shutting down; do not claim the job was accepted.
            try:
                if connection is not None:
                    connection.execute(
                        "UPDATE gold.service_runs SET finished_at=now(), status='failed', error='Worker is shutting down' WHERE id=%s",
                        (run_id,),
                    )
            except psycopg.Error:
                log.error("Cannot record cancelled submission for %s", self.name)
            finally:
                if connection is not None:
                    connection.close()
                self.lock.release()
                self.idle.set()
            raise JobUnavailable from None
        return run_id

    def scheduled(self) -> None:
        try:
            connection, run_id = self.reserve()
        except JobBusy:
            log.info("Skipping scheduled %s: a job is already running", self.name)
            return
        except JobUnavailable:
            log.warning("Skipping scheduled %s: run journal unavailable", self.name)
            return
        self.execute(connection, run_id)


def create_service_app(
    name: str, job: Callable[[], Any], schedule: dict[str, Any]
) -> FastAPI:
    configure_logging(name)
    runner = JobRunner(name, job)
    scheduler = BackgroundScheduler(timezone=settings.tz_local)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runner.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"{name}-job"
        )
        if settings.scheduler_enabled:
            scheduler.add_job(
                runner.scheduled,
                **schedule,
                id=name,
                max_instances=1,
                replace_existing=True,
                coalesce=True,
            )
            scheduler.start()
        try:
            yield
        finally:
            if scheduler.running:
                scheduler.shutdown(wait=True)
            runner.executor.shutdown(wait=True)
            runner.executor = None

    app = FastAPI(title=name, lifespan=lifespan)
    app.state.runner = runner
    app.state.scheduler = scheduler

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": name}

    @app.post("/run", status_code=202, dependencies=[Depends(require_job_token)])
    def run() -> dict[str, Any]:
        try:
            run_id = runner.submit()
        except JobBusy:
            raise HTTPException(409, "This service already has a running job") from None
        except JobUnavailable:
            raise HTTPException(
                503, "Job runner or run journal is unavailable"
            ) from None
        return {"service": name, "run_id": run_id, "status": "accepted"}

    return app
