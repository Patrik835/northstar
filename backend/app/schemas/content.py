import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class NewsRead(BaseModel):
    id: uuid.UUID
    ticker: str
    headline: str
    summary: str | None
    source: str
    image_url: str | None
    published_at: datetime
    url: str
    is_read: bool = False


class CalendarEventRead(BaseModel):
    id: uuid.UUID
    ticker: str
    event_type: Literal["earnings", "dividend"]
    event_date: date
    title: str
    details: dict[str, Any] = Field(default_factory=dict)
    source_url: str | None = None


class AlertRead(BaseModel):
    id: uuid.UUID
    alert_type: Literal["stale_connection", "sync_failure", "allocation_drift", "event"]
    severity: Literal["info", "warning", "error"]
    title: str
    message: str
    source_url: str | None
    event_at: datetime | None
    read_at: datetime | None
    created_at: datetime


class NewsHighlightRead(BaseModel):
    title: str
    summary: str
    tickers: list[str] = Field(default_factory=list)
    news_ids: list[uuid.UUID] = Field(default_factory=list)


class PortfolioNewsBriefRead(BaseModel):
    id: uuid.UUID
    brief_date: date
    generated_at: datetime
    model_used: str
    positions_count: int
    selected_news_ids: list[uuid.UUID] = Field(default_factory=list)
    highlights: list[NewsHighlightRead] = Field(default_factory=list)


class ContentSummary(BaseModel):
    news: list[NewsRead]
    events: list[CalendarEventRead]
    alerts: list[AlertRead]
    unread_news: int
    unread_alerts: int
    brief: PortfolioNewsBriefRead | None = None


class NotificationPreferenceRead(BaseModel):
    email_digest_enabled: bool
    digest_frequency: Literal["daily", "weekly"]
    email_available: bool
    email: str | None
    email_verified: bool
    last_digest_at: datetime | None


class NotificationPreferenceUpdate(BaseModel):
    email_digest_enabled: bool
    digest_frequency: Literal["daily", "weekly"] = "weekly"
