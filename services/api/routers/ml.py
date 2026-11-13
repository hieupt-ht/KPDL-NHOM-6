"""Các endpoint phân cụm và dự báo."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from auth import require_user

router = APIRouter(dependencies=[Depends(require_user)])


@router.get("/clusters")
def get_clusters(start: datetime | None = None, end: datetime | None = None) -> None:
    """Đọc kết quả phân cụm từng ngày từ Gold."""
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("/forecast/continuous")
def get_forecast_continuous(start: datetime | None = None, end: datetime | None = None) -> None:
    """Đọc dự báo chỉ số lưu lượng ngày mai từ Gold."""
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("/forecast/discrete")
def get_forecast_discrete(start: datetime | None = None, end: datetime | None = None) -> None:
    """Đọc nhãn rủi ro và xác suất ngày mai từ Gold."""
    raise HTTPException(status_code=501, detail="Not implemented yet")
