import hashlib
import hmac
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import httpx

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


class BybitConnector(BrokerConnector):
    """Read-only Bybit EU V5 adapter. Trading endpoints are intentionally absent."""

    base_url = "https://api.bybit.eu"
    receive_window_ms = 10_000
    initial_history_days = 90
    history_overlap = timedelta(minutes=5)
    fiat_assets = {"EUR", "USD", "GBP", "CHF", "CZK", "PLN"}
    usd_targets = ("USD", "USDT", "USDC")

    def __init__(
        self,
        credentials: dict[str, str],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(credentials)
        self._transport = transport
        self._validated = False
        self._positions: list[ConnectorPosition] | None = None
        self._symbols: dict[str, dict[str, Any]] | None = None
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
        query = urlencode(sorted(request_params.items()))
        request_path = f"{path}?{query}" if query else path
        headers: dict[str, str] = {}
        if signed:
            timestamp = str(int(time.time() * 1000))
            receive_window = str(self.receive_window_ms)
            api_key = self.credentials["api_key"]
            signature_payload = f"{timestamp}{api_key}{receive_window}{query}"
            signature = hmac.new(
                self.credentials["secret_key"].encode(),
                signature_payload.encode(),
                hashlib.sha256,
            ).hexdigest()
            headers.update(
                {
                    "X-BAPI-API-KEY": api_key,
                    "X-BAPI-TIMESTAMP": timestamp,
                    "X-BAPI-RECV-WINDOW": receive_window,
                    "X-BAPI-SIGN": signature,
                }
            )

        async def send() -> httpx.Response:
            async with self._client() as client:
                return await client.get(request_path, headers=headers)

        try:
            response = await request_with_backoff(send)
        except httpx.TimeoutException as exc:
            raise BrokerUnavailableError(
                "Bybit EU did not respond in time. Please try again."
            ) from exc
        except httpx.RequestError as exc:
            raise BrokerUnavailableError(
                "Could not reach Bybit EU. Please try again shortly."
            ) from exc

        payload: Any = None
        try:
            payload = response.json()
        except ValueError:
            pass
        code = payload.get("retCode") if isinstance(payload, dict) else None
        if response.status_code == 401 or code in {10003, 10004, 33004}:
            raise InvalidBrokerCredentials(
                "Bybit EU rejected the API key or secret. Check that this is a Bybit EU "
                "system-generated API key and that any IP restriction includes this server."
            )
        if response.status_code == 403 or code in {10005, 10007, 10010}:
            raise BrokerPermissionError(
                "Bybit EU denied this request. Enable read access for the Unified account, "
                "assets/wallet, and trade history, and check the key's IP restriction."
            )
        if response.status_code == 429 or code == 10006:
            retry_after = retry_after_seconds(response)
            raise BrokerRateLimitError(
                "Bybit EU's request limit was reached. Wait before synchronizing again.",
                retry_after,
            )
        if code == 10002:
            raise BrokerUnavailableError(
                "Bybit EU rejected the request time. Check the server clock and try again."
            )
        if response.status_code >= 500:
            raise BrokerUnavailableError(
                "Bybit EU is temporarily unavailable. Please try again shortly."
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise BrokerUnavailableError(
                "Bybit EU returned an unexpected response. Please try again."
            ) from exc
        if not isinstance(payload, dict) or code != 0:
            raise BrokerUnavailableError(
                "Bybit EU returned an unexpected response. Please try again."
            )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise BrokerUnavailableError("Bybit EU returned incomplete account information.")
        return result

    async def validate_credentials(self) -> None:
        if self._validated:
            return
        result = await self._get("/v5/user/query-api", signed=True)
        try:
            read_only = int(result.get("readOnly"))
        except (TypeError, ValueError):
            raise BrokerUnavailableError(
                "Bybit EU returned incomplete API-key information."
            ) from None
        if read_only != 1:
            raise BrokerPermissionError(
                "For safety, Northstar accepts only a read-only Bybit EU API key. "
                "Create a read-only key and try again."
            )
        self._validated = True

    async def _market(self) -> None:
        if self._symbols is not None:
            return
        instruments = await self._get(
            "/v5/market/instruments-info", {"category": "spot"}
        )
        tickers = await self._get("/v5/market/tickers", {"category": "spot"})
        instrument_list = instruments.get("list")
        ticker_list = tickers.get("list")
        if not isinstance(instrument_list, list) or not isinstance(ticker_list, list):
            raise BrokerUnavailableError("Bybit EU returned invalid market information.")

        self._symbols = {
            str(item["symbol"]): item
            for item in instrument_list
            if isinstance(item, dict)
            and item.get("status") == "Trading"
            and item.get("symbol")
            and item.get("baseCoin")
            and item.get("quoteCoin")
        }
        prices: dict[str, Decimal] = {}
        for item in ticker_list:
            if not isinstance(item, dict) or item.get("symbol") not in self._symbols:
                continue
            price = _decimal(item.get("lastPrice"))
            if price > 0:
                prices[str(item["symbol"])] = price

        edges: dict[str, list[tuple[str, Decimal]]] = {}
        for symbol, info in self._symbols.items():
            price = prices.get(symbol)
            if price is None:
                continue
            base = str(info["baseCoin"])
            quote = str(info["quoteCoin"])
            edges.setdefault(base, []).append((quote, price))
            edges.setdefault(quote, []).append((base, Decimal(1) / price))
        self._edges = edges

    def _usd_rate(self, asset: str) -> Decimal | None:
        if asset in self.usd_targets:
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
                if neighbor in self.usd_targets:
                    return next_rate
                visited.add(neighbor)
                queue.append((neighbor, next_rate, depth + 1))
        return None

    async def fetch_positions(self) -> list[ConnectorPosition]:
        if self._positions is not None:
            return self._positions
        await self.validate_credentials()
        unified = await self._get(
            "/v5/account/wallet-balance", {"accountType": "UNIFIED"}, signed=True
        )
        funding = await self._get(
            "/v5/asset/transfer/query-account-coins-balance",
            {"accountType": "FUND"},
            signed=True,
        )
        unified_accounts = unified.get("list")
        funding_balances = funding.get("balance")
        if not isinstance(unified_accounts, list) or not unified_accounts:
            raise BrokerUnavailableError("Bybit EU returned invalid Unified account balances.")
        if not isinstance(funding_balances, list):
            raise BrokerUnavailableError("Bybit EU returned invalid Funding account balances.")

        quantities: dict[str, Decimal] = {}
        values: dict[str, Decimal] = {}
        unpriced_quantities: dict[str, Decimal] = {}
        coins = unified_accounts[0].get("coin")
        if not isinstance(coins, list):
            raise BrokerUnavailableError("Bybit EU returned invalid Unified account balances.")
        for item in coins:
            if not isinstance(item, dict):
                continue
            asset = str(item.get("coin") or "").upper()
            quantity = _decimal(item.get("equity"))
            if not asset or quantity == 0:
                continue
            quantities[asset] = quantities.get(asset, Decimal(0)) + quantity
            usd_value = _decimal(item.get("usdValue"))
            if usd_value != 0:
                values[asset] = values.get(asset, Decimal(0)) + usd_value
            else:
                unpriced_quantities[asset] = (
                    unpriced_quantities.get(asset, Decimal(0)) + quantity
                )

        for item in funding_balances:
            if not isinstance(item, dict):
                continue
            asset = str(item.get("coin") or "").upper()
            quantity = _decimal(item.get("walletBalance"))
            if not asset or quantity == 0:
                continue
            quantities[asset] = quantities.get(asset, Decimal(0)) + quantity
            unpriced_quantities[asset] = unpriced_quantities.get(asset, Decimal(0)) + quantity

        if unpriced_quantities:
            await self._market()
            unpriced: list[str] = []
            for asset, quantity in unpriced_quantities.items():
                rate = self._usd_rate(asset)
                if rate is None:
                    unpriced.append(asset)
                    continue
                values[asset] = values.get(asset, Decimal(0)) + quantity * rate
            if unpriced:
                raise ConnectorError(
                    "Bybit EU balances could not be converted to USD: "
                    f"{', '.join(sorted(unpriced))}."
                )

        self._positions = [
            ConnectorPosition(
                instrument_id=f"BYBIT:{asset}",
                ticker=asset,
                name="Cash" if asset in self.fiat_assets else asset,
                asset_type=(
                    AssetType.CASH if asset in self.fiat_assets else AssetType.CRYPTO
                ),
                quantity=quantity,
                average_price=None,
                current_value=values.get(asset, Decimal(0)),
                currency="USD",
                canonical_symbol=asset,
            )
            for asset, quantity in sorted(quantities.items())
        ]
        return self._positions

    async def fetch_transactions(self, since: datetime | None) -> list[ConnectorTransaction]:
        await self.validate_credentials()
        await self._market()
        now = datetime.now(timezone.utc)
        normalized_since = (
            since.astimezone(timezone.utc)
            if since and since.tzinfo
            else since.replace(tzinfo=timezone.utc)
            if since
            else now - timedelta(days=self.initial_history_days)
        )
        start = max(
            now - timedelta(days=self.initial_history_days),
            normalized_since - self.history_overlap,
        )
        trades = await self._windowed_history(
            "/v5/execution/list", start, now, timedelta(days=7), {"category": "spot"}
        )
        deposits = await self._windowed_history(
            "/v5/asset/deposit/query-record",
            start,
            now,
            timedelta(days=30),
            limit=50,
        )
        withdrawals = await self._windowed_history(
            "/v5/asset/withdraw/query-record",
            start,
            now,
            timedelta(days=30),
            {"withdrawType": 2},
            limit=50,
        )
        transactions = [
            *self._map_trades(trades, normalized_since if since else None),
            *self._map_deposits(deposits, normalized_since if since else None),
            *self._map_withdrawals(withdrawals, normalized_since if since else None),
        ]
        return sorted(transactions, key=lambda item: (item.executed_at, item.external_id))

    async def _windowed_history(
        self,
        path: str,
        start: datetime,
        end: datetime,
        window: timedelta,
        extra_params: dict[str, str | int] | None = None,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        window_start = start
        while window_start < end:
            window_end = min(window_start + window - timedelta(milliseconds=1), end)
            cursor: str | None = None
            for _ in range(20):
                params: dict[str, str | int] = {
                    **(extra_params or {}),
                    "startTime": int(window_start.timestamp() * 1000),
                    "endTime": int(window_end.timestamp() * 1000),
                    "limit": limit,
                }
                if cursor:
                    params["cursor"] = cursor
                result = await self._get(path, params, signed=True)
                rows = result.get("list")
                if rows is None:
                    rows = result.get("rows")
                if not isinstance(rows, list):
                    raise BrokerUnavailableError(
                        "Bybit EU returned invalid account activity."
                    )
                records.extend(item for item in rows if isinstance(item, dict))
                next_cursor = str(result.get("nextPageCursor") or "")
                if not next_cursor:
                    cursor = None
                    break
                if next_cursor == cursor:
                    raise BrokerUnavailableError(
                        "Bybit EU repeated an activity continuation. Please try again."
                    )
                cursor = next_cursor
            if cursor:
                raise BrokerUnavailableError(
                    "Bybit EU returned too much activity for one time window. "
                    "Narrow the synchronization period and try again."
                )
            window_start = window_end + timedelta(milliseconds=1)
        return records

    def _map_trades(
        self, records: list[dict[str, Any]], since: datetime | None
    ) -> list[ConnectorTransaction]:
        assert self._symbols is not None
        transactions: list[ConnectorTransaction] = []
        for item in records:
            executed_at = _timestamp_ms(item.get("execTime"))
            if executed_at is None or (since and executed_at <= since):
                continue
            symbol = str(item.get("symbol") or "")
            info = self._symbols.get(symbol, {})
            base = str(info.get("baseCoin") or symbol or "UNKNOWN")
            quote = str(info.get("quoteCoin") or item.get("feeCurrency") or "USD")
            quantity = abs(_decimal(item.get("execQty")))
            price = abs(_decimal(item.get("execPrice")))
            value = abs(_decimal(item.get("execValue"))) or quantity * price
            identifier = str(
                item.get("execId")
                or f"{symbol}:{item.get('orderId')}:{item.get('execTime')}"
            )
            transactions.append(
                ConnectorTransaction(
                    external_id=f"trade:{identifier}",
                    ticker=base,
                    transaction_type=(
                        TransactionType.BUY
                        if str(item.get("side")).casefold() == "buy"
                        else TransactionType.SELL
                    ),
                    quantity=quantity,
                    price=price,
                    value=value,
                    currency=quote,
                    executed_at=executed_at,
                )
            )
            fee = abs(_decimal(item.get("execFee")))
            if fee:
                fee_asset = str(item.get("feeCurrency") or quote)
                transactions.append(
                    ConnectorTransaction(
                        external_id=f"trade-fee:{identifier}",
                        ticker=fee_asset,
                        transaction_type=TransactionType.FEE,
                        quantity=None,
                        price=None,
                        value=fee,
                        currency=fee_asset,
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
            if str(item.get("status")) != "3":
                continue
            executed_at = _timestamp_ms(item.get("successAt") or item.get("createTime"))
            if executed_at is None or (since and executed_at <= since):
                continue
            asset = str(item.get("coin") or "UNKNOWN")
            amount = abs(_decimal(item.get("amount")))
            identifier = item.get("id") or item.get("txID") or (
                f"{asset}:{item.get('successAt')}:{amount}"
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
            status = str(item.get("status") or "").casefold()
            if status not in {"success", "blockchainconfirmed"}:
                continue
            executed_at = _timestamp_ms(item.get("updateTime") or item.get("createTime"))
            if executed_at is None or (since and executed_at <= since):
                continue
            asset = str(item.get("coin") or "UNKNOWN")
            amount = abs(_decimal(item.get("amount")))
            identifier = item.get("withdrawId") or item.get("txID") or (
                f"{asset}:{item.get('createTime')}:{amount}"
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
            fee = abs(_decimal(item.get("withdrawFee")))
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

    async def fetch_snapshot(self, snapshot_date: date) -> ConnectorSnapshot:
        positions = await self.fetch_positions()
        return ConnectorSnapshot(
            snapshot_date=snapshot_date,
            total_value=sum((item.current_value for item in positions), Decimal(0)),
            currency="USD",
        )


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def _timestamp_ms(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
