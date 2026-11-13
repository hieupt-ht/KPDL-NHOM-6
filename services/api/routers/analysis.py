"""Các endpoint kết quả thống kê."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from auth import require_user

router = APIRouter(dependencies=[Depends(require_user)])


@router.get("/histogram")
def get_histogram(metric: str, start: datetime | None = None, end: datetime | None = None) -> None:
    """Đọc các bin histogram từ Gold."""
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("/trend")
def get_trend(granularity: Literal["month", "week"], metric: str, start: datetime | None = None, end: datetime | None = None) -> None:
    """Đọc đường xu hướng từ Gold."""
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("/seasonal")
def get_seasonal(period_type: Literal["hour_of_day", "day_of_week", "month"], metric: str, start: datetime | None = None, end: datetime | None = None) -> None:
    """Đọc các giá trị mùa vụ theo chu kỳ từ Gold."""
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("/correlation")
def get_correlation(start: datetime | None = None, end: datetime | None = None) -> None:
    """Đọc hệ số tương quan giữa các chỉ số từ Gold."""
    raise HTTPException(status_code=501, detail="Not implemented yet")
