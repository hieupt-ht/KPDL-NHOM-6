"""Các endpoint chuỗi thời gian."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from auth import require_user

router = APIRouter(dependencies=[Depends(require_user)])


@router.get("/timeseries")
def get_timeseries(granularity: Literal["day", "week", "month"], metric: str, start: datetime | None = None, end: datetime | None = None) -> None:
    """Đọc chuỗi đã tổng hợp theo khoảng thời gian từ Gold."""
    raise HTTPException(status_code=501, detail="Not implemented yet")
