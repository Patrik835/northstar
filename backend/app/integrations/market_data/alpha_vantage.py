from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx


class AlphaVantageError(RuntimeError):
    """Raised when historical market data cannot be loaded safely."""


class AlphaVantageRateLimitError(AlphaVantageError):
    """Raised when Alpha Vantage asks the client to stop sending requests."""


@dataclass(frozen=True, slots=True)
class WeeklyPrice:
    price_date: date
    close: Decimal


@dataclass(frozen=True, slots=True)
class InstrumentOverview:
    sector: str | None
    industry: str | None
    country: str | None


class AlphaVantageProvider:
    base_url = "https://www.alphavantage.co"

    def __init__(
        self,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.transport = transport

    async def weekly_equity(self, symbol: str) -> list[WeeklyPrice]:
        payload = await self._get(
            {"function": "TIME_SERIES_WEEKLY", "symbol": symbol, "apikey": self.api_key}
        )
        return self._parse_series(payload, "Weekly Time Series")

    async def weekly_fx(self, source: str, target: str) -> list[WeeklyPrice]:
        payload = await self._get(
            {
                "function": "FX_WEEKLY",
                "from_symbol": source,
                "to_symbol": target,
                "apikey": self.api_key,
            }
        )
        return self._parse_series(payload, "Time Series FX (Weekly)")

    async def company_overview(self, symbol: str) -> InstrumentOverview:
        payload = await self._get(
            {"function": "OVERVIEW", "symbol": symbol, "apikey": self.api_key}
        )
        if not payload:
            raise AlphaVantageError("Alpha Vantage returned no instrument metadata.")
        return InstrumentOverview(
            sector=self._optional_text(payload.get("Sector")),
            industry=self._optional_text(payload.get("Industry")),
            country=self._optional_text(payload.get("Country")),
        )

    async def _get(self, params: dict[str, str]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(30.0),
                transport=self.transport,
            ) as client:
                response = await client.get("/query", params=params)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AlphaVantageError("Historical market data is temporarily unavailable.") from exc
        if not isinstance(payload, dict):
            raise AlphaVantageError("Alpha Vantage returned invalid historical data.")
        rate_limit_detail = payload.get("Information") or payload.get("Note")
        if rate_limit_detail:
            raise AlphaVantageRateLimitError(str(rate_limit_detail))
        detail = payload.get("Error Message")
        if detail:
            raise AlphaVantageError(str(detail))
        return payload

    @staticmethod
    def _parse_series(payload: dict[str, Any], key: str) -> list[WeeklyPrice]:
        raw_series = payload.get(key)
        if not isinstance(raw_series, dict):
            raise AlphaVantageError("Alpha Vantage returned no weekly price history.")
        points: list[WeeklyPrice] = []
        try:
            for raw_date, values in raw_series.items():
                if not isinstance(values, dict):
                    continue
                close = Decimal(str(values["4. close"]))
                if close > 0:
                    points.append(WeeklyPrice(date.fromisoformat(str(raw_date)), close))
        except (KeyError, InvalidOperation, ValueError) as exc:
            raise AlphaVantageError("Alpha Vantage returned invalid weekly prices.") from exc
        if not points:
            raise AlphaVantageError("Alpha Vantage returned no usable weekly prices.")
        return sorted(points, key=lambda point: point.price_date)

    @staticmethod
    def _optional_text(value: object) -> str | None:
        text = str(value or "").strip()
        return None if not text or text.casefold() in {"none", "n/a", "null", "-"} else text
