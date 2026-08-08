import hashlib
import hmac
import time
from collections import deque
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from app.integrations.connectors.base import (
    BrokerConnector,
    BrokerPermissionError,
    BrokerUnavailableError,
    ConnectorError,
    ConnectorPosition,
    ConnectorSnapshot,
    ConnectorTransaction,
    InvalidBrokerCredentials,
)
from app.models.enums import AssetType, TransactionType


class BinanceConnector(BrokerConnector):
    """Read-only Binance Spot adapter. Never implements order/trading endpoints."""

    base_url = "https://api.binance.com"
    quote_priority = ("EUR", "USDT", "USDC", "FDUSD", "BTC")

    def __init__(
        self,
        credentials: dict[str, str],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(credentials)
        self._transport = transport
        self._clock_offset_ms: int | None = None
        self._account: dict[str, Any] | None = None
        self._positions: list[ConnectorPosition] | None = None
        self._symbols: dict[str, dict[str, Any]] | None = None
        self._prices: dict[str, Decimal] | None = None
        self._edges: dict[str, list[tuple[str, Decimal]]] | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Accept": "application/json"},
            timeout=httpx.Timeout(20.0),
            transport=self._transport,
        )

    async def _get(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
        *,
        signed: bool = False,
    ) -> Any:
        request_params = dict(params or {})
        headers: dict[str, str] = {}
        if signed:
            request_params["timestamp"] = await self._timestamp_ms()
            request_params["recvWindow"] = 10_000
            query = urlencode(request_params)
            signature = hmac.new(
                self.credentials["secret_key"].encode(),
                query.encode(),
                hashlib.sha256,
            ).hexdigest()
            request_path = f"{path}?{query}&signature={signature}"
            headers["X-MBX-APIKEY"] = self.credentials["api_key"]
        else:
            request_path = path

        try:
            async with self._client() as client:
                response = await client.get(request_path, headers=headers)
        except httpx.TimeoutException as exc:
            raise BrokerUnavailableError(
                "Binance did not respond in time. Please try again."
            ) from exc
        except httpx.RequestError as exc:
            raise BrokerUnavailableError(
                "Could not reach Binance. Please try again shortly."
            ) from exc

        payload: Any = None
        try:
            payload = response.json()
        except ValueError:
            pass
        error_code = payload.get("code") if isinstance(payload, dict) else None
        if response.status_code == 401 or error_code in {-2014, -2015}:
            raise InvalidBrokerCredentials(
                "Binance rejected the API key or secret. Check the key, IP restrictions, "
                "and enable Reading permission only."
            )
        if response.status_code == 403:
            raise BrokerPermissionError(
                "Binance denied this request. Check the key's Reading permission "
                "and IP restriction."
            )
        if response.status_code in {418, 429}:
            raise BrokerUnavailableError(
                "Binance's request limit was reached. Wait before synchronizing again."
            )
        if error_code == -1021:
            self._clock_offset_ms = None
            raise BrokerUnavailableError(
                "Binance rejected the request timestamp. Check the server clock and try again."
            )
        if response.status_code >= 500:
            raise BrokerUnavailableError(
                "Binance is temporarily unavailable. Please try again shortly."
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise BrokerUnavailableError(
                "Binance returned an unexpected response. Please try again."
            ) from exc
        if payload is None:
            raise BrokerUnavailableError("Binance returned an invalid response.")
        return payload

    async def _timestamp_ms(self) -> int:
        if self._clock_offset_ms is None:
            payload = await self._get("/api/v3/time")
            if not isinstance(payload, dict) or "serverTime" not in payload:
                raise BrokerUnavailableError("Binance returned invalid server time information.")
            local_time = int(time.time() * 1000)
            self._clock_offset_ms = int(payload["serverTime"]) - local_time
        return int(time.time() * 1000) + self._clock_offset_ms

    async def validate_credentials(self) -> None:
        if self._account is not None:
            return
        payload = await self._get(
            "/api/v3/account", {"omitZeroBalances": "true"}, signed=True
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("balances"), list):
            raise BrokerUnavailableError("Binance returned incomplete account information.")
        self._account = payload

    async def _market(self) -> None:
        if self._symbols is not None:
            return
        exchange, ticker_prices = await self._get("/api/v3/exchangeInfo"), await self._get(
            "/api/v3/ticker/price"
        )
        if not isinstance(exchange, dict) or not isinstance(exchange.get("symbols"), list):
            raise BrokerUnavailableError("Binance returned invalid market information.")
        if not isinstance(ticker_prices, list):
            raise BrokerUnavailableError("Binance returned invalid price information.")

        self._symbols = {
            str(item["symbol"]): item
            for item in exchange["symbols"]
            if item.get("status") == "TRADING"
            and item.get("symbol")
            and item.get("baseAsset")
            and item.get("quoteAsset")
        }
        self._prices = {
            str(item["symbol"]): Decimal(str(item["price"]))
            for item in ticker_prices
            if item.get("symbol") in self._symbols and Decimal(str(item.get("price", 0))) > 0
        }
        edges: dict[str, list[tuple[str, Decimal]]] = {}
        for symbol, info in self._symbols.items():
            price = self._prices.get(symbol)
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

    async def fetch_positions(self) -> list[ConnectorPosition]:
        if self._positions is not None:
            return self._positions
        await self.validate_credentials()
        await self._market()
        assert self._account is not None

        positions: list[ConnectorPosition] = []
        unpriced: list[str] = []
        for item in self._account["balances"]:
            asset = str(item.get("asset") or "")
            quantity = Decimal(str(item.get("free", 0))) + Decimal(str(item.get("locked", 0)))
            if not asset or not quantity:
                continue
            rate = self._conversion_rate(asset)
            if rate is None:
                unpriced.append(asset)
                continue
            positions.append(
                ConnectorPosition(
                    instrument_id=f"BINANCE:{asset}",
                    ticker=asset,
                    name=asset if asset != "EUR" else "Cash (EUR)",
                    asset_type=AssetType.CASH if asset == "EUR" else AssetType.CRYPTO,
                    quantity=quantity,
                    average_price=None,
                    current_value=quantity * rate,
                    currency="EUR",
                    canonical_symbol=asset,
                )
            )
        if unpriced:
            raise ConnectorError(
                "Binance balances could not be converted to EUR: "
                f"{', '.join(sorted(unpriced))}."
            )
        self._positions = positions
        return positions

    def _preferred_trade_symbol(self, asset: str) -> str | None:
        assert self._symbols is not None
        candidates = [
            info
            for info in self._symbols.values()
            if info.get("baseAsset") == asset and info.get("symbol") in (self._prices or {})
        ]
        candidates.sort(
            key=lambda item: (
                self.quote_priority.index(str(item["quoteAsset"]))
                if item.get("quoteAsset") in self.quote_priority
                else len(self.quote_priority),
                str(item["symbol"]),
            )
        )
        return str(candidates[0]["symbol"]) if candidates else None

    async def fetch_transactions(self, since: datetime | None) -> list[ConnectorTransaction]:
        await self.fetch_positions()
        assert self._account is not None
        assert self._symbols is not None
        assets = {
            str(item["asset"])
            for item in self._account["balances"]
            if Decimal(str(item.get("free", 0))) + Decimal(str(item.get("locked", 0))) > 0
            and item.get("asset") != "EUR"
        }
        symbols = {symbol for asset in assets if (symbol := self._preferred_trade_symbol(asset))}
        transactions: list[ConnectorTransaction] = []
        for symbol in sorted(symbols):
            params: dict[str, str | int] = {"symbol": symbol, "limit": 1000}
            if since:
                params["startTime"] = int(since.timestamp() * 1000)
            payload = await self._get("/api/v3/myTrades", params, signed=True)
            if not isinstance(payload, list):
                raise BrokerUnavailableError("Binance returned invalid trade history.")
            info = self._symbols[symbol]
            base_asset = str(info["baseAsset"])
            quote_asset = str(info["quoteAsset"])
            for item in payload:
                executed_at = datetime.fromtimestamp(
                    int(item["time"]) / 1000, tz=timezone.utc
                )
                if since and executed_at <= since:
                    continue
                trade_id = str(item.get("id"))
                quantity = Decimal(str(item.get("qty", 0)))
                price = Decimal(str(item.get("price", 0)))
                value = Decimal(str(item.get("quoteQty", quantity * price)))
                transactions.append(
                    ConnectorTransaction(
                        external_id=f"trade:{symbol}:{trade_id}",
                        ticker=base_asset,
                        transaction_type=(
                            TransactionType.BUY if item.get("isBuyer") else TransactionType.SELL
                        ),
                        quantity=abs(quantity),
                        price=price,
                        value=abs(value),
                        currency=quote_asset,
                        executed_at=executed_at,
                    )
                )
                commission = Decimal(str(item.get("commission", 0)))
                if commission:
                    commission_asset = str(item.get("commissionAsset") or quote_asset)
                    transactions.append(
                        ConnectorTransaction(
                            external_id=f"trade-fee:{symbol}:{trade_id}",
                            ticker=commission_asset,
                            transaction_type=TransactionType.FEE,
                            quantity=None,
                            price=None,
                            value=abs(commission),
                            currency=commission_asset,
                            executed_at=executed_at,
                        )
                    )
        return sorted(transactions, key=lambda item: item.executed_at)

    async def fetch_snapshot(self, snapshot_date: date) -> ConnectorSnapshot:
        positions = await self.fetch_positions()
        return ConnectorSnapshot(
            snapshot_date=snapshot_date,
            total_value=sum((item.current_value for item in positions), Decimal(0)),
            currency="EUR",
        )
