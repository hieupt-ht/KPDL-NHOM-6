"""Đọc cấu hình từ biến môi trường."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    warehouse_dsn: str = ""
    mart_dsn: str = ""
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    db_statement_timeout_ms: int = Field(default=10000, ge=1)
    auth_enabled: bool = False
    keycloak_issuer: str = "http://localhost:8080/realms/cyber-radar"
    keycloak_jwks_url: str = ""
    keycloak_audience: str = "cyber-radar-api"
    jwks_timeout_seconds: int = Field(default=5, ge=1, le=60)
    job_trigger_token: SecretStr = SecretStr("")
    job_request_timeout_seconds: int = Field(default=10, ge=1, le=60)
    analysis_url: str = "http://analysis:8001"
    clustering_url: str = "http://clustering:8002"
    prediction_url: str = "http://prediction:8003"
    scheduler_enabled: bool = True
    tz_local: str = "Asia/Ho_Chi_Minh"
    ingestion_interval_seconds: int = 300
    analysis_interval_seconds: int = 300
    prediction_interval_seconds: int = 300
    clustering_cron_hour: int = 0
    clustering_cron_minute: int = 30


settings = Settings()
