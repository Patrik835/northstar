from datetime import datetime

from app.integrations.news.base import NewsProvider, ProviderNewsItem


class FinnhubNewsProvider(NewsProvider):
    """Default v1 provider, isolated so limits or provider changes stay local."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def company_news(self, ticker: str, since: datetime) -> list[ProviderNewsItem]:
        raise NotImplementedError

