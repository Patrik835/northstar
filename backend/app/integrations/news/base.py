from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ProviderNewsItem:
    external_id: str
    ticker: str
    headline: str
    source: str
    published_at: datetime
    url: str


class NewsProvider(ABC):
    @abstractmethod
    async def company_news(self, ticker: str, since: datetime) -> list[ProviderNewsItem]: ...

