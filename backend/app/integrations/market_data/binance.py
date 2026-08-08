from collections import deque
from decimal import Decimal
from typing import Any

import httpx


class CryptoPriceError(RuntimeError):
    """Raised when public crypto market data cannot be loaded."""


class BinanceCryptoPriceProvider:
    """Public, read-only crypto conversion rates sourced from Binance Spot markets."""

    base_url = "https://api.binance.com"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._edges: dict[str, list[tuple[str, Decimal]]] | None = None

    async def rates_to_eur(self, assets: set[str]) -> dict[str, Decimal]:
        await self._load_market()
        return {
            asset: rate
            for asset in sorted(assets)
            if (rate := self._conversion_rate(asset.upper())) is not None
        }

    async def _get(self, path: str) -> Any:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(20.0),
                transport=self._transport,
            ) as client:
                response = await client.get(path)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CryptoPriceError("Current crypto market prices are unavailable.") from exc

    async def _load_market(self) -> None:
        if self._edges is not None:
            return
        exchange = await self._get("/api/v3/exchangeInfo")
        ticker_prices = await self._get("/api/v3/ticker/price")
        if not isinstance(exchange, dict) or not isinstance(exchange.get("symbols"), list):
            raise CryptoPriceError("Binance returned invalid crypto market information.")
        if not isinstance(ticker_prices, list):
            raise CryptoPriceError("Binance returned invalid crypto price information.")

        symbols = {
            str(item["symbol"]): item
            for item in exchange["symbols"]
            if item.get("status") == "TRADING"
            and item.get("symbol")
            and item.get("baseAsset")
            and item.get("quoteAsset")
        }
        prices = {
            str(item["symbol"]): Decimal(str(item["price"]))
            for item in ticker_prices
            if item.get("symbol") in symbols and Decimal(str(item.get("price", 0))) > 0
        }
        edges: dict[str, list[tuple[str, Decimal]]] = {}
        for symbol, info in symbols.items():
            price = prices.get(symbol)
            if not price:
                continue
            base = str(info["baseAsset"])
            quote = str(info["quoteAsset"])
            edges.setdefault(base, []).append((quote, price))
            edges.setdefault(quote, []).append((base, Decimal(1) / price))
        self._edges = edges

    def _conversion_rate(self, asset: str, target: str = "EUR") -> Decimal | None:
        if asset == target:
            return Decimal(1)
        assert self._edges is not None
        queue: deque[tuple[str, Decimal, int]] = deque([(asset, Decimal(1), 0)])
        visited = {asset}
        while queue:
            current, rate, depth = queue.popleft()
            if depth >= 3:
                continue
            for neighbor, edge_rate in self._edges.get(current, []):
                if neighbor in visited:
                    continue
                next_rate = rate * edge_rate
                if neighbor == target:
                    return next_rate
                visited.add(neighbor)
                queue.append((neighbor, next_rate, depth + 1))
        return None
