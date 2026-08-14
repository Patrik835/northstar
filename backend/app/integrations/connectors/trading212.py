import hashlib
import re
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.integrations.connectors.base import (
    BrokerConnector,
    BrokerPermissionError,
    BrokerRateLimitError,
    BrokerUnavailableError,
    ConnectorPosition,
    ConnectorSnapshot,
    ConnectorTransaction,
    ConnectorTransactionPage,
    InvalidBrokerCredentials,
)
from app.integrations.connectors.retry import request_with_backoff, retry_after_seconds
from app.models.enums import AssetType, TransactionType

INSTRUMENT_METADATA_CACHE_SECONDS = 600
_instrument_type_cache: dict[str, tuple[float, dict[str, AssetType]]] = {}


class Trading212Connector(BrokerConnector):
    """Read-only adapter for Trading 212's live Invest/Stocks ISA API."""

    base_url = "https://live.trading212.com/api/v0"
    history_paths = {
        "orders": "/equity/history/orders",
        "dividends": "/equity/history/dividends",
        "cash": "/equity/history/transactions",
    }

    def __init__(
        self,
        credentials: dict[str, str],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(credentials)
        self._transport = transport
        self._account_summary: dict[str, Any] | None = None
        self._instrument_types: dict[str, AssetType] | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            auth=httpx.BasicAuth(self.credentials["api_key"], self.credentials["api_secret"]),
            headers={"Accept": "application/json"},
            timeout=httpx.Timeout(15.0),
            transport=self._transport,
        )

    async def _get(self, path: str, params: dict[str, str | int] | None = None) -> Any:
        async def send() -> httpx.Response:
            async with self._client() as client:
                return await client.get(path, params=params)

        try:
            response = await request_with_backoff(send, reset_header="x-ratelimit-reset")
        except httpx.TimeoutException as exc:
            raise BrokerUnavailableError(
                "Trading 212 did not respond in time. Please try again."
            ) from exc
        except httpx.RequestError as exc:
            raise BrokerUnavailableError(
                "Could not reach Trading 212. Please try again shortly."
            ) from exc

        if response.status_code == 401:
            raise InvalidBrokerCredentials(
                "Trading 212 rejected the API key or secret. Check both values and try again."
            )
        if response.status_code == 403:
            if "/history/" in path:
                raise BrokerPermissionError(
                    "Portfolio access works, but Trading 212 denied history access. "
                    "Recent trades and dividends cannot be imported with this key."
                )
            raise BrokerPermissionError(
                "Trading 212 denied access to this account or portfolio request. "
                "Check the key's IP restriction and read permissions."
            )
        if response.status_code == 429:
            retry_after = retry_after_seconds(response, reset_header="x-ratelimit-reset")
            suffix = (
                f" Try again in about {max(1, round(retry_after))} seconds."
                if retry_after is not None
                else " Wait a moment and try again."
            )
            raise BrokerRateLimitError(
                f"Trading 212's request limit was reached.{suffix}", retry_after
            )
        if response.status_code >= 500:
            raise BrokerUnavailableError(
                "Trading 212 is temporarily unavailable. Please try again shortly."
            )
        try:
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPStatusError, ValueError) as exc:
            raise BrokerUnavailableError(
                "Trading 212 returned an unexpected response. Please try again."
            ) from exc

    async def validate_credentials(self) -> None:
        if self._account_summary is not None:
            return
        payload = await self._get("/equity/account/summary")
        if not isinstance(payload, dict) or not payload.get("currency"):
            raise BrokerUnavailableError("Trading 212 returned incomplete account information.")
        self._account_summary = payload

    async def fetch_positions(self) -> list[ConnectorPosition]:
        payload = await self._get("/equity/positions")
        if not isinstance(payload, list):
            raise BrokerUnavailableError("Trading 212 returned invalid portfolio information.")
        instrument_types = await self._load_instrument_types()

        positions: list[ConnectorPosition] = []
        for item in payload:
            instrument = item.get("instrument") or {}
            wallet = item.get("walletImpact") or {}
            name = instrument.get("name")
            ticker = str(instrument.get("ticker") or "UNKNOWN")
            isin = str(instrument["isin"]).upper() if instrument.get("isin") else None
            positions.append(
                ConnectorPosition(
                    instrument_id=str(isin or ticker),
                    ticker=ticker,
                    name=name,
                    asset_type=instrument_types.get(ticker.upper(), AssetType.OTHER),
                    quantity=Decimal(str(item.get("quantity", 0))),
                    average_price=_decimal_or_none(item.get("averagePricePaid")),
                    current_value=Decimal(str(wallet.get("currentValue", 0))),
                    currency=str(wallet.get("currency") or instrument.get("currency") or "EUR"),
                    canonical_symbol=_canonical_symbol(ticker),
                    isin=isin,
                    reported_pnl=_decimal_or_none(wallet.get("unrealizedProfitLoss")),
                )
            )

        summary = await self._summary()
        cash = summary.get("cash") or {}
        cash_value = sum(
            Decimal(str(cash.get(field, 0)))
            for field in ("availableToTrade", "inPies", "reservedForOrders")
        )
        currency = str(summary["currency"])
        if cash_value:
            positions.append(
                ConnectorPosition(
                    instrument_id=f"CASH:{currency}",
                    ticker=currency,
                    name=f"Cash ({currency})",
                    asset_type=AssetType.CASH,
                    quantity=cash_value,
                    average_price=None,
                    current_value=cash_value,
                    currency=currency,
                    canonical_symbol=currency,
                )
            )
        return positions

    async def _load_instrument_types(self) -> dict[str, AssetType]:
        if self._instrument_types is not None:
            return self._instrument_types

        cache_key = hashlib.sha256(self.credentials["api_key"].encode()).hexdigest()
        if self._transport is None:
            cached = _instrument_type_cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < INSTRUMENT_METADATA_CACHE_SECONDS:
                self._instrument_types = cached[1]
                return self._instrument_types

        payload = await self._get("/equity/metadata/instruments")
        if not isinstance(payload, list):
            raise BrokerUnavailableError("Trading 212 returned invalid instrument metadata.")
        self._instrument_types = {
            str(item["ticker"]).upper(): _asset_type_from_metadata(item.get("type"))
            for item in payload
            if isinstance(item, dict) and item.get("ticker")
        }
        if self._transport is None:
            _instrument_type_cache[cache_key] = (time.monotonic(), self._instrument_types)
        return self._instrument_types

    async def fetch_transactions(self, since: datetime | None) -> list[ConnectorTransaction]:
        pages = [
            await self.fetch_transaction_page(stream)
            for stream in self.transaction_history_streams()
        ]
        transactions = [item for page in pages for item in page.transactions]
        if since:
            transactions = [item for item in transactions if item.executed_at > since]
        return transactions

    def transaction_history_streams(self) -> tuple[str, ...]:
        return tuple(self.history_paths)

    async def fetch_transaction_page(
        self, stream: str, page_path: str | None = None
    ) -> ConnectorTransactionPage:
        endpoint = self.history_paths.get(stream)
        if endpoint is None:
            raise ValueError(f"Unsupported Trading 212 history stream: {stream}")
        request_path = page_path or endpoint
        if page_path is not None:
            parsed = urlsplit(page_path)
            expected_path = f"/api/v0{endpoint}"
            if parsed.scheme or parsed.netloc or parsed.fragment:
                raise BrokerUnavailableError(
                    "Trading 212 returned an invalid history continuation. Please try again."
                )
            if parsed.path in {expected_path, endpoint, ""}:
                continuation_query = parsed.query
            elif "/" not in parsed.path and not parsed.query:
                # The cash-history API returns a raw query string rather than a path.
                continuation_query = parsed.path
            else:
                raise BrokerUnavailableError(
                    "Trading 212 returned an invalid history continuation. Please try again."
                )
            if not continuation_query:
                raise BrokerUnavailableError(
                    "Trading 212 returned an invalid history continuation. Please try again."
                )
            # The HTTP client base URL already contains /api/v0. Trading 212 includes
            # that prefix in some nextPagePath values, while cash history returns only
            # a query string. Always anchor continuations to the known stream endpoint.
            request_path = f"{endpoint}?{continuation_query}"
        payload = await self._get(
            request_path,
            None if page_path is not None else {"limit": 50},
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise BrokerUnavailableError(
                "Trading 212 returned invalid transaction history information."
            )
        next_page_path = payload.get("nextPagePath")
        if next_page_path is not None and not isinstance(next_page_path, str):
            raise BrokerUnavailableError(
                "Trading 212 returned an invalid history continuation. Please try again."
            )
        mappers = {
            "orders": _map_orders,
            "dividends": _map_dividends,
            "cash": _map_cash,
        }
        return ConnectorTransactionPage(
            transactions=mappers[stream](payload["items"]),
            next_page_path=next_page_path,
        )

    async def fetch_snapshot(self, snapshot_date: date) -> ConnectorSnapshot:
        summary = await self._summary()
        investments = summary.get("investments") or {}
        return ConnectorSnapshot(
            snapshot_date=snapshot_date,
            total_value=Decimal(str(summary.get("totalValue", 0))),
            currency=str(summary["currency"]),
            reported_pnl=_decimal_or_none(investments.get("unrealizedProfitLoss")),
            independent_total=True,
        )

    async def _summary(self) -> dict[str, Any]:
        if self._account_summary is None:
            await self.validate_credentials()
        assert self._account_summary is not None
        return self._account_summary


def _decimal_or_none(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _asset_type_from_metadata(value: Any) -> AssetType:
    normalized = str(value or "").upper()
    if normalized == "ETF":
        return AssetType.ETF
    if normalized == "STOCK":
        return AssetType.STOCK
    if normalized in {"CRYPTO", "CRYPTOCURRENCY"}:
        return AssetType.CRYPTO
    return AssetType.OTHER


def _canonical_symbol(ticker: str) -> str:
    parts = ticker.split("_")
    if parts and parts[-1].upper() == "EQ":
        parts.pop()
    has_explicit_market = len(parts) > 1 and parts[-1].upper() in {
        "AU",
        "CA",
        "CH",
        "DE",
        "ES",
        "FR",
        "IT",
        "NL",
        "UK",
        "US",
    }
    if has_explicit_market:
        parts.pop()
    elif len(parts) == 1 and re.search(r"[a-z]$", parts[0]):
        # Trading 212 appends a lowercase exchange marker when the market is not
        # represented by a separate segment (for example ASMLa_EQ in Amsterdam).
        # Preserve actual share-class letters on symbols such as BRKb_US_EQ,
        # which include an explicit market segment.
        parts[0] = parts[0][:-1]
    return ("_".join(parts) or ticker).upper()


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _map_orders(items: list[dict[str, Any]]) -> list[ConnectorTransaction]:
    mapped: list[ConnectorTransaction] = []
    for item in items:
        order = item.get("order") or {}
        fill = item.get("fill") or {}
        if not fill.get("filledAt"):
            continue
        wallet = fill.get("walletImpact") or {}
        quantity = _decimal_or_none(fill.get("quantity") or order.get("filledQuantity"))
        price = _decimal_or_none(fill.get("price"))
        value = _decimal_or_none(wallet.get("netValue"))
        if value is None:
            value = abs((quantity or Decimal(0)) * (price or Decimal(0)))
        mapped.append(
            ConnectorTransaction(
                external_id=f"order-fill:{fill.get('id') or order.get('id')}",
                ticker=str((order.get("instrument") or {}).get("ticker") or order.get("ticker")),
                transaction_type=(
                    TransactionType.BUY if order.get("side") == "BUY" else TransactionType.SELL
                ),
                quantity=abs(quantity) if quantity is not None else None,
                price=price,
                value=abs(value),
                currency=str(wallet.get("currency") or order.get("currency") or "EUR"),
                executed_at=_timestamp(str(fill["filledAt"])),
            )
        )
    return mapped


def _map_dividends(items: list[dict[str, Any]]) -> list[ConnectorTransaction]:
    return [
        ConnectorTransaction(
            external_id=f"dividend:{item['reference']}",
            ticker=str((item.get("instrument") or {}).get("ticker") or item.get("ticker")),
            transaction_type=TransactionType.DIVIDEND,
            quantity=_decimal_or_none(item.get("quantity")),
            price=_decimal_or_none(item.get("grossAmountPerShare")),
            value=abs(Decimal(str(item.get("amount", 0)))),
            currency=str(item.get("currency") or "EUR"),
            executed_at=_timestamp(str(item["paidOn"])),
        )
        for item in items
        if item.get("reference") and item.get("paidOn")
    ]


def _map_cash(items: list[dict[str, Any]]) -> list[ConnectorTransaction]:
    types = {
        "DEPOSIT": TransactionType.DEPOSIT,
        "WITHDRAW": TransactionType.WITHDRAWAL,
        "FEE": TransactionType.FEE,
    }
    return [
        ConnectorTransaction(
            external_id=f"cash:{item['reference']}",
            ticker=str(item.get("currency") or "CASH"),
            transaction_type=types.get(str(item.get("type")), TransactionType.OTHER),
            quantity=None,
            price=None,
            value=abs(Decimal(str(item.get("amount", 0)))),
            currency=str(item.get("currency") or "EUR"),
            executed_at=_timestamp(str(item["dateTime"])),
        )
        for item in items
        if item.get("reference") and item.get("dateTime")
    ]
