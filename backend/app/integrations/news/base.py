from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


class NewsProviderError(RuntimeError):
    """A sanitized provider failure safe for logs and background-job handling."""


@dataclass(frozen=True, slots=True)
class ProviderNewsItem:
    external_id: str
    ticker: str
    headline: str
    summary: str | None
    source: str
    image_url: str | None
    published_at: datetime
    url: str


@dataclass(frozen=True, slots=True)
class ProviderCalendarEvent:
    external_id: str
    ticker: str
    event_type: str
    event_date: date
    title: str
    details: dict[str, Any]
    source_url: str | None = None


class NewsProvider(ABC):
    @abstractmethod
    async def company_news(self, ticker: str, since: datetime) -> list[ProviderNewsItem]: ...

    @abstractmethod
    async def calendar_events(
        self, ticker: str, start: date, end: date
    ) -> list[ProviderCalendarEvent]: ...
