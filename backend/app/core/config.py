from base64 import b64decode
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "Northstar Investment OS API"
    app_env: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    app_secret_key: str = Field(min_length=32)
    credential_encryption_key: str
    database_url: str = "postgresql+asyncpg://investing:investing@db:5432/investing"
    # Only needed when the web app is served from a different origin than PUBLIC_WEB_URL.
    frontend_origin: str | None = None
    cookie_name: str = "investment_session"
    # Defaults to secure cookies whenever PUBLIC_WEB_URL uses HTTPS.
    cookie_secure: bool | None = None
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

    # Optional features switch on automatically once their API key is set.
    ai_enabled: bool = True
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-terra"
    ai_review_cache_hours: int = 12
    ai_daily_review_limit: int = 3
    ai_daily_message_limit: int = 30
    ai_max_input_characters: int = 2000
    news_enabled: bool = True
    finnhub_api_key: str | None = None
    news_brief_candidate_limit: int = 300
    alpha_vantage_key: str | None = None
    benchmarks_enabled: bool = True

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
        try:
            decoded = b64decode(value.encode(), altchars=b"-_", validate=True)
        except ValueError as exc:
            raise ValueError("Credential encryption key must be URL-safe base64") from exc
        if len(decoded) != 32:
            raise ValueError("Credential encryption key must decode to exactly 32 bytes")
        return value

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.public_web_url.lower().startswith("https://")

    @property
    def cors_origin(self) -> str:
        return (self.frontend_origin or self.public_web_url).rstrip("/")

    @property
    def email_enabled(self) -> bool:
        """An empty SMTP_HOST means this deployment does not send email."""
        return bool(self.smtp_host.strip())

    @property
    def ai_available(self) -> bool:
        return bool(self.ai_enabled and self.openai_api_key)

    @property
    def news_available(self) -> bool:
        return bool(self.news_enabled and self.finnhub_api_key)

    @property
    def benchmarks_available(self) -> bool:
        return bool(self.benchmarks_enabled and self.alpha_vantage_key)

    @model_validator(mode="after")
    def validate_production(self) -> "Settings":
        if self.app_env == "production":
            if not self.secure_cookies:
                raise ValueError("Production requires secure cookies")
            for url in (self.public_web_url, self.cors_origin):
                parsed = urlsplit(url)
                if parsed.scheme != "https" or not parsed.hostname:
                    raise ValueError("Production public URLs must use HTTPS")
            if self.app_secret_key.startswith(("replace-", "test-", "change-")):
                raise ValueError("Production requires a non-placeholder application secret")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
