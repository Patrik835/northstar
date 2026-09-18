import hashlib
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.integrations.news.base import (
    NewsProvider,
    NewsProviderError,
    ProviderCalendarEvent,
    ProviderNewsItem,
)


class FinnhubNewsProvider(NewsProvider):
    """Small read-only Finnhub adapter for company news and held-symbol events."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str = "https://finnhub.io/api/v1",
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=15)
        self._earnings_available = True
        self._dividends_available = True

    async def _get(self, path: str, params: dict[str, str]) -> Any:
        try:
            response = await self._client.get(
                path,
                params=params,
                headers={"X-Finnhub-Token": self._api_key},
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise NewsProviderError("Finnhub is temporarily unavailable") from exc
        if response.status_code == 429:
            raise NewsProviderError("Finnhub request limit reached")
        if response.status_code in {401, 403}:
            raise NewsProviderError("Finnhub rejected this endpoint or API key")
        if response.status_code >= 400:
            raise NewsProviderError("Finnhub could not provide market content")
        try:
            return response.json()
        except ValueError as exc:
            raise NewsProviderError("Finnhub returned invalid data") from exc

    async def company_news(self, ticker: str, since: datetime) -> list[ProviderNewsItem]:
        now = datetime.now(timezone.utc)
        payload = await self._get(
            "/company-news",
            {
                "symbol": ticker,
                "from": since.date().isoformat(),
                "to": now.date().isoformat(),
            },
        )
        if not isinstance(payload, list):
            return []
        items: list[ProviderNewsItem] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            headline = _text(raw.get("headline"), 500)
            url = _safe_url(raw.get("url"))
            published_at = _timestamp(raw.get("datetime"))
            if not headline or not url or not published_at or published_at < since:
                continue
            identifier = str(raw.get("id") or _digest(f"{ticker}|{url}|{published_at.isoformat()}"))
            items.append(
                ProviderNewsItem(
                    external_id=f"finnhub:news:{identifier}"[:160],
                    ticker=ticker,
                    headline=headline,
                    summary=_text(raw.get("summary"), 1200) or None,
                    source=_text(raw.get("source"), 120) or "Finnhub",
                    image_url=_safe_url(raw.get("image")),
                    published_at=published_at,
                    url=url,
                )
            )
        return items

    async def calendar_events(
        self, ticker: str, start: date, end: date
    ) -> list[ProviderCalendarEvent]:
        result: list[ProviderCalendarEvent] = []
        if self._earnings_available:
            try:
                result.extend(await self._earnings(ticker, start, end))
            except NewsProviderError as exc:
                if "rejected" not in str(exc).casefold():
                    raise
                self._earnings_available = False
        if self._dividends_available:
            try:
                result.extend(await self._dividends(ticker, start, end))
            except NewsProviderError as exc:
                # Calendar endpoints depend on the subscription. Stop retrying a denied
                # endpoint for every ticker while keeping company news available.
                if "rejected" not in str(exc).casefold():
                    raise
                self._dividends_available = False
        return result

    async def _earnings(self, ticker: str, start: date, end: date) -> list[ProviderCalendarEvent]:
        payload = await self._get(
            "/calendar/earnings",
            {
                "symbol": ticker,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "international": "true",
            },
        )
        rows = payload.get("earningsCalendar", []) if isinstance(payload, dict) else []
        events: list[ProviderCalendarEvent] = []
        for raw in rows:
            if (
                not isinstance(raw, dict)
                or str(raw.get("symbol", ticker)).upper() != ticker.upper()
            ):
                continue
            event_date = _date(raw.get("date"))
            if event_date is None or not start <= event_date <= end:
                continue
            quarter = raw.get("quarter")
            year = raw.get("year")
            identity = f"{ticker}|earnings|{event_date}|{quarter}|{year}"
            events.append(
                ProviderCalendarEvent(
                    external_id=f"finnhub:event:{_digest(identity)}",
                    ticker=ticker,
                    event_type="earnings",
                    event_date=event_date,
                    title=f"{ticker} earnings",
                    details={
                        key: raw.get(key)
                        for key in (
                            "hour",
                            "quarter",
                            "year",
                            "epsEstimate",
                            "epsActual",
                            "revenueEstimate",
                            "revenueActual",
                        )
                        if raw.get(key) is not None
                    },
                )
            )
        return events

    async def _dividends(self, ticker: str, start: date, end: date) -> list[ProviderCalendarEvent]:
        payload = await self._get(
            "/stock/dividend",
            {"symbol": ticker, "from": start.isoformat(), "to": end.isoformat()},
        )
        if not isinstance(payload, list):
            return []
        events: list[ProviderCalendarEvent] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            event_date = _date(raw.get("date"))
            if event_date is None or not start <= event_date <= end:
                continue
            identity = f"{ticker}|dividend|{event_date}|{raw.get('amount')}|{raw.get('currency')}"
            events.append(
                ProviderCalendarEvent(
                    external_id=f"finnhub:event:{_digest(identity)}",
                    ticker=ticker,
                    event_type="dividend",
                    event_date=event_date,
                    title=f"{ticker} ex-dividend date",
                    details={
                        key: raw.get(key)
                        for key in ("amount", "adjustedAmount", "currency", "payDate", "recordDate")
                        if raw.get(key) is not None
                    },
                )
            )
        return events


def _text(value: object, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _safe_url(value: object) -> str | None:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    return candidate if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _timestamp(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]
