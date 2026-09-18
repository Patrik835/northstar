from base64 import urlsafe_b64decode
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Northstar Investment OS API"
    app_env: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    app_secret_key: str = Field(min_length=32)
    credential_encryption_key: str
    database_url: str = "postgresql+asyncpg://investing:investing@db:5432/investing"
    frontend_origin: str = "http://localhost:5173"
    cookie_name: str = "investment_session"
    cookie_secure: bool = False
    session_ttl_hours: int = 24 * 7
    public_signup_enabled: bool = True
    email_verification_ttl_hours: int = 24
    password_reset_ttl_minutes: int = 60
    public_web_url: str = "http://localhost:8080"

    auth_rate_limit_window_minutes: int = 15
    auth_login_ip_limit: int = 30
    auth_login_account_limit: int = 10
    auth_registration_ip_limit: int = 5
    auth_email_ip_limit: int = 10
    auth_email_account_limit: int = 3

    log_format: Literal["text", "json"] = "text"
    monitoring_token: str | None = None
    backup_status_file: str = "/backups/latest-success"
    backup_max_age_hours: int = 30

    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_start_tls: bool = False
    smtp_use_tls: bool = False
    email_from_address: str = "no-reply@northstar.local"
    email_from_name: str = "Northstar"

    ai_enabled: bool = False
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-terra"
    ai_review_cache_hours: int = 12
    ai_daily_review_limit: int = 3
    ai_daily_message_limit: int = 30
    ai_max_input_characters: int = 2000
    news_enabled: bool = False
    finnhub_api_key: str | None = None
    news_brief_candidate_limit: int = 300
    alpha_vantage_key: str | None = None
    benchmarks_enabled: bool = False

    scheduler_enabled: bool = True
    portfolio_sync_minutes: int = 120
    news_sync_hour_utc: int = 4
    notification_digest_hour_utc: int = 7
    allocation_drift_alert_points: int = 5

    initial_admin_username: str = "patrik"
    initial_admin_password: str | None = None

    @field_validator("credential_encryption_key")
    @classmethod
    def validate_encryption_key(cls, value: str) -> str:
        if value.startswith("replace-"):
            return value
        try:
            decoded = urlsafe_b64decode(value.encode())
        except ValueError as exc:
            raise ValueError("Credential encryption key must be URL-safe base64") from exc
        if len(decoded) != 32:
            raise ValueError("Credential encryption key must decode to exactly 32 bytes")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
