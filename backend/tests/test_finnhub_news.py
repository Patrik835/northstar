from datetime import date, datetime, timezone

import httpx
import pytest

from app.integrations.news.finnhub import FinnhubNewsProvider


@pytest.mark.asyncio
async def test_finnhub_maps_company_news_and_calendar_events() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Finnhub-Token"] == "test-key"
        if request.url.path.endswith("company-news"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 123,
                        "headline": "Apple reports results",
                        "summary": "Quarterly update",
                        "source": "Example News",
                        "datetime": 1_786_752_000,
                        "url": "https://example.com/apple",
                        "image": "javascript:bad",
                    }
                ],
            )
        if request.url.path.endswith("calendar/earnings"):
            return httpx.Response(
                200,
                json={
                    "earningsCalendar": [
                        {
                            "date": "2026-08-20",
                            "symbol": "AAPL",
                            "hour": "amc",
                            "quarter": 3,
                            "year": 2026,
                            "epsEstimate": 1.5,
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "AAPL",
                    "date": "2026-08-22",
                    "amount": 0.25,
                    "currency": "USD",
                }
            ],
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://finnhub.test/api/v1"
    ) as client:
        provider = FinnhubNewsProvider("test-key", client=client)
        news = await provider.company_news("AAPL", datetime(2026, 8, 1, tzinfo=timezone.utc))
        events = await provider.calendar_events("AAPL", date(2026, 8, 15), date(2026, 9, 15))

    assert len(news) == 1
    assert news[0].external_id == "finnhub:news:123"
    assert news[0].image_url is None
    assert {item.event_type for item in events} == {"earnings", "dividend"}
    assert next(item for item in events if item.event_type == "earnings").details == {
        "hour": "amc",
        "quarter": 3,
        "year": 2026,
        "epsEstimate": 1.5,
    }


@pytest.mark.asyncio
async def test_finnhub_keeps_earnings_when_dividends_are_not_in_plan() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("calendar/earnings"):
            return httpx.Response(
                200,
                json={"earningsCalendar": [{"date": "2026-08-20", "symbol": "MSFT"}]},
            )
        return httpx.Response(403, json={"error": "Premium required"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://finnhub.test/api/v1"
    ) as client:
        events = await FinnhubNewsProvider("test-key", client=client).calendar_events(
            "MSFT", date(2026, 8, 15), date(2026, 9, 15)
        )

    assert len(events) == 1
    assert events[0].event_type == "earnings"
