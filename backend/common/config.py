"""Đọc cấu hình từ biến môi trường."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    warehouse_dsn: str = ""
    mart_dsn: str = ""
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    db_statement_timeout_ms: int = Field(default=10000, ge=1)
    auth_enabled: bool = False
    scheduler_enabled: bool = True
    tz_local: str = "Asia/Ho_Chi_Minh"
    ingestion_interval_seconds: int = 300
    analysis_interval_seconds: int = 300
    prediction_interval_seconds: int = 300
    clustering_cron_hour: int = 0
    clustering_cron_minute: int = 30


settings = Settings()
