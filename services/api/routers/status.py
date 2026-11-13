"""Endpoint trạng thái dữ liệu và service."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from auth import require_user

router = APIRouter(dependencies=[Depends(require_user)])


@router.get("/status")
def get_status(start: datetime | None = None, end: datetime | None = None) -> None:
    """Đọc độ mới dữ liệu và lần chạy cuối của từng service từ Gold."""
    raise HTTPException(status_code=501, detail="Not implemented yet")
