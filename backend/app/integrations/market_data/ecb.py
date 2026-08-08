from decimal import Decimal
from typing import Protocol
from xml.etree import ElementTree

import httpx


class FxRateError(RuntimeError):
    """Raised when a value cannot be converted safely."""


class FxRateProvider(Protocol):
    async def convert_to_eur(self, value: Decimal, currency: str) -> Decimal: ...


class EcbFxRateProvider:
    """Converts working-day ECB reference rates into EUR values."""

    rates_url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._rates: dict[str, Decimal] | None = None

    async def convert_to_eur(self, value: Decimal, currency: str) -> Decimal:
        normalized = currency.upper()
        if normalized == "EUR":
            return value
        rates = await self._load_rates()
        rate = rates.get(normalized)
        if not rate:
            raise FxRateError(f"ECB does not publish an EUR reference rate for {normalized}.")
        return value / rate

    async def _load_rates(self) -> dict[str, Decimal]:
        if self._rates is not None:
            return self._rates
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0), transport=self._transport
            ) as client:
                response = await client.get(self.rates_url)
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except (httpx.HTTPError, ElementTree.ParseError) as exc:
            raise FxRateError("ECB exchange rates are temporarily unavailable.") from exc

        rates = {"EUR": Decimal(1)}
        for element in root.iter():
            currency = element.attrib.get("currency")
            rate = element.attrib.get("rate")
            if currency and rate:
                rates[currency.upper()] = Decimal(rate)
        if len(rates) == 1:
            raise FxRateError("ECB returned no exchange rates.")
        self._rates = rates
        return rates
