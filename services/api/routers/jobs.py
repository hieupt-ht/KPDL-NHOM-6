"""Endpoint kích hoạt công việc thủ công."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from auth import require_admin

router = APIRouter(dependencies=[Depends(require_admin)])


@router.post("/jobs/{service}/run")
def run_job(service: Literal["analysis", "clustering", "prediction"]) -> None:
    """Kích hoạt service Business Logic tương ứng sau khi kiểm tra admin."""
    raise HTTPException(status_code=501, detail="Not implemented yet")
