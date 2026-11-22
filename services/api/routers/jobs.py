"""Endpoint kích hoạt công việc thủ công."""

from typing import Annotated, Literal

import httpx
from common.config import settings
from fastapi import APIRouter, Depends, HTTPException, Path
from psycopg import Connection
from pydantic import BaseModel, ValidationError

from dependencies import get_mart
from schemas import ServiceRun

router = APIRouter(tags=["Jobs"])


class AcceptedJob(BaseModel):
    service: Literal["analysis", "clustering", "prediction"]
    run_id: int
    status: Literal["accepted"]


@router.get("/jobs/runs/{run_id}", response_model=ServiceRun)
def get_job_run(
    run_id: Annotated[int, Path(ge=1)],
    connection: Annotated[Connection, Depends(get_mart)],
):
    row = connection.execute(
        "SELECT id, service, started_at, finished_at, status, error FROM gold.service_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Job run was not found")
    return row


@router.post("/jobs/{service}/run", status_code=202, response_model=AcceptedJob)
def run_job(service: Literal["analysis", "clustering", "prediction"]) -> AcceptedJob:
    """Only trigger a fixed service URL; the service owns execution and Gold writes."""
    token = settings.job_trigger_token.get_secret_value()
    if not token:
        raise HTTPException(503, "Internal job authentication is not configured")
    url = {
        "analysis": settings.analysis_url,
        "clustering": settings.clustering_url,
        "prediction": settings.prediction_url,
    }[service]
    try:
        # No automatic retry: a timed-out request might already have started a job.
        with httpx.Client(
            timeout=settings.job_request_timeout_seconds, trust_env=False
        ) as client:
            response = client.post(
                url.rstrip("/") + "/run",
                headers={"X-Job-Token": token} if token else {},
            )
    except httpx.TimeoutException:
        raise HTTPException(
            504, "Job request timed out; check status before retrying"
        ) from None
    except httpx.RequestError:
        raise HTTPException(503, "Job service is unavailable") from None
    if response.status_code == 409:
        raise HTTPException(409, "This service already has a running job")
    if response.status_code == 503:
        raise HTTPException(503, "Job service is not ready")
    if response.status_code != 202:
        raise HTTPException(502, "Job service rejected the request")
    try:
        result = AcceptedJob.model_validate(response.json())
        if result.service != service or result.run_id <= 0:
            raise ValueError("Unexpected job identity")
        return result
    except (ValueError, ValidationError):
        raise HTTPException(502, "Job service returned an invalid response") from None
