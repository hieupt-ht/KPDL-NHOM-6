"""Điểm vào API đọc Data Mart."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from routers import analysis, jobs, ml, status, timeseries

app = FastAPI(title="Cyber Radar VN API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["GET", "POST"], allow_headers=["*"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@app.post("/run")
def run() -> None:
    """Điểm kích hoạt API dự phòng của khung dịch vụ Python."""
    raise HTTPException(status_code=501, detail="Not implemented yet")


for router in (timeseries.router, analysis.router, ml.router, jobs.router, status.router):
    app.include_router(router, prefix="/api")
