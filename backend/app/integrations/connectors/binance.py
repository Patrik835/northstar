import hashlib
import hmac
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from app.integrations.binance_assets import binance_valuation_asset
from app.integrations.connectors.base import (
    BrokerConnector,
    BrokerPermissionError,
    BrokerRateLimitError,
    BrokerUnavailableError,
    ConnectorError,
    ConnectorPosition,
    ConnectorSnapshot,
    ConnectorTransaction,
    InvalidBrokerCredentials,
)
from app.integrations.connectors.retry import request_with_backoff, retry_after_seconds
from app.models.enums import AssetType, TransactionType


class BinanceConnector(BrokerConnector):
    """Read-only Binance Spot adapter. Never implements order/trading endpoints."""

    base_url = "https://api.binance.com"
    quote_priority = ("EUR", "USDT", "USDC", "FDUSD", "BTC")
    capital_history_days = 89
    income_history_days = 179
    history_overlap = timedelta(minutes=5)
    max_offset_pages = 10
    max_trade_pages = 5

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

        async def send() -> httpx.Response:
            async with self._client() as client:
                return await client.get(request_path, headers=headers)

        try:
            response = await request_with_backoff(send)
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
            retry_after = retry_after_seconds(response)
            suffix = (
                f" Try again in about {max(1, round(retry_after))} seconds."
                if retry_after is not None
                else " Wait before synchronizing again."
            )
            raise BrokerRateLimitError(
                f"Binance's request limit was reached.{suffix}", retry_after
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
            valuation_asset = binance_valuation_asset(asset)
            rate = self._conversion_rate(valuation_asset)
            if rate is None:
                unpriced.append(asset)
                continue
            positions.append(
                ConnectorPosition(
                    instrument_id=f"BINANCE:{asset}",
                    ticker=asset,
                    name=(
                        "Cash (EUR)"
                        if asset == "EUR"
                        else valuation_asset
                    ),
                    asset_type=AssetType.CASH if asset == "EUR" else AssetType.CRYPTO,
                    quantity=quantity,
                    average_price=None,
                    current_value=quantity * rate,
                    currency="EUR",
                    canonical_symbol=valuation_asset,
                )
            )
        if unpriced:
            raise ConnectorError(
                "Binance balances could not be converted to EUR: "
                f"{', '.join(sorted(unpriced))}."
            )
        self._positions = positions
        return positions

    def _trade_symbols(self, assets: set[str]) -> set[str]:
        assert self._symbols is not None
        return {
            symbol
            for symbol, info in self._symbols.items()
            if str(info.get("baseAsset")) in assets
            and str(info.get("quoteAsset")) in self.quote_priority
        }

    async def fetch_transactions(self, since: datetime | None) -> list[ConnectorTransaction]:
        await self.fetch_positions()
        assert self._account is not None
        assert self._symbols is not None
        now = datetime.now(timezone.utc)
        capital_start = self._history_start(since, now, self.capital_history_days)
        income_start = self._history_start(since, now, self.income_history_days)

        deposits = await self._fetch_offset_history(
            "/sapi/v1/capital/deposit/hisrec",
            capital_start,
            now,
            "deposit history",
        )
        withdrawals = await self._fetch_offset_history(
            "/sapi/v1/capital/withdraw/history",
            capital_start,
            now,
            "withdrawal history",
        )
        income = await self._fetch_income(income_start, now)

        assets = {
            str(item["asset"])
            for item in self._account["balances"]
            if Decimal(str(item.get("free", 0))) + Decimal(str(item.get("locked", 0))) > 0
            and item.get("asset") != "EUR"
        }
        assets.update(str(item.get("coin")) for item in deposits if item.get("coin"))
        assets.update(str(item.get("coin")) for item in withdrawals if item.get("coin"))
        assets.update(str(item.get("asset")) for item in income if item.get("asset"))

        transactions = [
            *self._map_deposits(deposits, since),
            *self._map_withdrawals(withdrawals, since),
            *self._map_income(income, since),
        ]
        for symbol in sorted(self._trade_symbols(assets)):
            records = await self._fetch_trades(symbol, since)
            transactions.extend(self._map_trades(symbol, records, since))
        return sorted(transactions, key=lambda item: (item.executed_at, item.external_id))

    def _history_start(
        self, since: datetime | None, now: datetime, maximum_days: int
    ) -> datetime:
        earliest = now - timedelta(days=maximum_days)
        if since is None:
            return earliest
        normalized = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        return max(earliest, normalized.astimezone(timezone.utc) - self.history_overlap)

    async def _fetch_offset_history(
        self,
        path: str,
        start: datetime,
        end: datetime,
        label: str,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for page in range(self.max_offset_pages):
            payload = await self._get(
                path,
                {
                    "startTime": int(start.timestamp() * 1000),
                    "endTime": int(end.timestamp() * 1000),
                    "offset": page * 1000,
                    "limit": 1000,
                },
                signed=True,
            )
            if not isinstance(payload, list):
                raise BrokerUnavailableError(f"Binance returned invalid {label}.")
            records.extend(item for item in payload if isinstance(item, dict))
            if len(payload) < 1000:
                break
        return records

    async def _fetch_income(
        self, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        return await self._fetch_income_window(start, end)

    async def _fetch_income_window(
        self, start: datetime, end: datetime, depth: int = 0
    ) -> list[dict[str, Any]]:
        payload = await self._get(
            "/sapi/v1/asset/assetDividend",
            {
                "startTime": int(start.timestamp() * 1000),
                "endTime": int(end.timestamp() * 1000),
                "limit": 500,
            },
            signed=True,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            raise BrokerUnavailableError("Binance returned invalid income history.")
        rows = [item for item in payload["rows"] if isinstance(item, dict)]
        try:
            total = int(payload.get("total", len(rows)))
        except (TypeError, ValueError):
            total = len(rows)
        if total <= len(rows):
            return rows
        if depth >= 8 or end - start <= timedelta(hours=1):
            raise BrokerUnavailableError(
                "Binance income history is too large to import safely in one run."
            )
        midpoint = start + (end - start) / 2
        return [
            *await self._fetch_income_window(start, midpoint, depth + 1),
            *await self._fetch_income_window(
                midpoint + timedelta(milliseconds=1), end, depth + 1
            ),
        ]

    async def _fetch_trades(
        self, symbol: str, since: datetime | None
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for _ in range(self.max_trade_pages):
            params: dict[str, str | int] = {"symbol": symbol, "limit": 1000}
            if records:
                params["fromId"] = max(int(item["id"]) for item in records) + 1
            elif since:
                normalized = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
                params["startTime"] = int(
                    (normalized.astimezone(timezone.utc) - self.history_overlap).timestamp()
                    * 1000
                )
            payload = await self._get("/api/v3/myTrades", params, signed=True)
            if not isinstance(payload, list):
                raise BrokerUnavailableError("Binance returned invalid trade history.")
            records.extend(item for item in payload if isinstance(item, dict))
            if since is None or len(payload) < 1000:
                break
        return records

    def _map_trades(
        self,
        symbol: str,
        records: list[dict[str, Any]],
        since: datetime | None,
    ) -> list[ConnectorTransaction]:
        assert self._symbols is not None
        info = self._symbols[symbol]
        base_asset = str(info["baseAsset"])
        quote_asset = str(info["quoteAsset"])
        transactions: list[ConnectorTransaction] = []
        for item in records:
            executed_at = _timestamp_ms(item.get("time"))
            if executed_at is None or (since and executed_at <= since):
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
        return transactions

    @staticmethod
    def _map_deposits(
        records: list[dict[str, Any]], since: datetime | None
    ) -> list[ConnectorTransaction]:
        transactions: list[ConnectorTransaction] = []
        for item in records:
            if int(item.get("status", -1)) not in {1, 6}:
                continue
            executed_at = _timestamp_ms(item.get("completeTime") or item.get("insertTime"))
            if executed_at is None or (since and executed_at <= since):
                continue
            asset = str(item.get("coin") or "UNKNOWN")
            amount = abs(Decimal(str(item.get("amount", 0))))
            identifier = item.get("id") or item.get("txId") or (
                f"{asset}:{item.get('insertTime')}:{amount}"
            )
            transactions.append(
                ConnectorTransaction(
                    external_id=f"deposit:{identifier}",
                    ticker=asset,
                    transaction_type=TransactionType.DEPOSIT,
                    quantity=amount,
                    price=None,
                    value=amount,
                    currency=asset,
                    executed_at=executed_at,
                )
            )
        return transactions

    @staticmethod
    def _map_withdrawals(
        records: list[dict[str, Any]], since: datetime | None
    ) -> list[ConnectorTransaction]:
        transactions: list[ConnectorTransaction] = []
        for item in records:
            if int(item.get("status", -1)) != 6:
                continue
            executed_at = _binance_datetime(
                item.get("completeTime") or item.get("applyTime")
            )
            if executed_at is None or (since and executed_at <= since):
                continue
            asset = str(item.get("coin") or "UNKNOWN")
            amount = abs(Decimal(str(item.get("amount", 0))))
            identifier = item.get("id") or item.get("txId") or (
                f"{asset}:{item.get('applyTime')}:{amount}"
            )
            transactions.append(
                ConnectorTransaction(
                    external_id=f"withdrawal:{identifier}",
                    ticker=asset,
                    transaction_type=TransactionType.WITHDRAWAL,
                    quantity=amount,
                    price=None,
                    value=amount,
                    currency=asset,
                    executed_at=executed_at,
                )
            )
            fee = abs(Decimal(str(item.get("transactionFee", 0))))
            if fee:
                transactions.append(
                    ConnectorTransaction(
                        external_id=f"withdrawal-fee:{identifier}",
                        ticker=asset,
                        transaction_type=TransactionType.FEE,
                        quantity=None,
                        price=None,
                        value=fee,
                        currency=asset,
                        executed_at=executed_at,
                    )
                )
        return transactions

    @staticmethod
    def _map_income(
        records: list[dict[str, Any]], since: datetime | None
    ) -> list[ConnectorTransaction]:
        transactions: list[ConnectorTransaction] = []
        for item in records:
            if int(item.get("direction", 1)) != 1:
                continue
            executed_at = _timestamp_ms(item.get("divTime"))
            if executed_at is None or (since and executed_at <= since):
                continue
            asset = str(item.get("asset") or "UNKNOWN")
            amount = abs(Decimal(str(item.get("amount", 0))))
            identifier = item.get("id") or item.get("tranId") or (
                f"{asset}:{item.get('divTime')}:{amount}"
            )
            transactions.append(
                ConnectorTransaction(
                    external_id=f"income:{asset}:{identifier}",
                    ticker=asset,
                    transaction_type=TransactionType.DIVIDEND,
                    quantity=amount,
                    price=None,
                    value=amount,
                    currency=asset,
                    executed_at=executed_at,
                )
            )
        return transactions

    async def fetch_snapshot(self, snapshot_date: date) -> ConnectorSnapshot:
        positions = await self.fetch_positions()
        return ConnectorSnapshot(
            snapshot_date=snapshot_date,
            total_value=sum((item.current_value for item in positions), Decimal(0)),
            currency="EUR",
        )


def _timestamp_ms(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _binance_datetime(value: Any) -> datetime | None:
    timestamp = _timestamp_ms(value)
    if timestamp is not None:
        return timestamp
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
