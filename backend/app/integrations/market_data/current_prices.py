from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import httpx

from app.integrations.market_data.binance import BinanceCryptoPriceProvider, CryptoPriceError
from app.models.enums import AssetType


class CurrentPriceError(RuntimeError):
    """A current price could not be verified for the requested instrument."""


class CurrentPriceProvider:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport
        self.crypto = BinanceCryptoPriceProvider(transport)

    async def price(self, ticker: str, asset_type: AssetType) -> tuple[Decimal, str, datetime]:
        if asset_type == AssetType.CRYPTO:
            try:
                rates = await self.crypto.rates_to_eur({ticker})
                return rates[ticker], "EUR", datetime.now(timezone.utc)
            except (CryptoPriceError, KeyError) as exc:
                raise CurrentPriceError("Current crypto price unavailable") from exc
        if asset_type not in {AssetType.STOCK, AssetType.ETF}:
            raise CurrentPriceError("No market price for this asset type")
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=10) as client:
                response = await client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker, safe='')}",
                    params={"interval": "1d", "range": "1d"},
                )
                response.raise_for_status()
                metadata = response.json()["chart"]["result"][0]["meta"]
            if metadata.get("symbol") and str(metadata["symbol"]).casefold() != ticker.casefold():
                raise ValueError("Quote listing does not match requested ticker")
            price = Decimal(str(metadata["regularMarketPrice"]))
            currency = str(metadata["currency"])
            if currency in {"GBp", "GBX"}:
                price /= 100
                currency = "GBP"
            as_of = datetime.fromtimestamp(metadata["regularMarketTime"], timezone.utc)
            if not price.is_finite() or price <= 0 or not currency:
                raise ValueError("Invalid quote")
            return price, currency, as_of
        except (
            httpx.HTTPError,
            ValueError,
            InvalidOperation,
            KeyError,
            TypeError,
            IndexError,
            OverflowError,
        ) as exc:
            raise CurrentPriceError("Current stock price unavailable") from exc
