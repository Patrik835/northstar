from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from app.integrations.connectors.base import (
    BrokerConnector,
    BrokerPermissionError,
    BrokerUnavailableError,
    ConnectorPosition,
    ConnectorSnapshot,
    ConnectorTransaction,
    InvalidBrokerCredentials,
)
from app.models.enums import AssetType, TransactionType


class Trading212Connector(BrokerConnector):
    """Read-only adapter for Trading 212's live Invest/Stocks ISA API."""

    base_url = "https://live.trading212.com/api/v0"

    def __init__(
        self,
        credentials: dict[str, str],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(credentials)
        self._transport = transport
        self._account_summary: dict[str, Any] | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            auth=httpx.BasicAuth(
                self.credentials["api_key"], self.credentials["api_secret"]
            ),
            headers={"Accept": "application/json"},
            timeout=httpx.Timeout(15.0),
            transport=self._transport,
        )

    async def _get(
        self, path: str, params: dict[str, str | int] | None = None
    ) -> Any:
        try:
            async with self._client() as client:
                response = await client.get(path, params=params)
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
            raise BrokerPermissionError(
                "The Trading 212 key does not have the required account, portfolio, "
                "or history read permissions."
            )
        if response.status_code == 429:
            raise BrokerUnavailableError(
                "Trading 212's request limit was reached. Wait a moment and try again."
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

        positions: list[ConnectorPosition] = []
        for item in payload:
            instrument = item.get("instrument") or {}
            wallet = item.get("walletImpact") or {}
            name = instrument.get("name")
            positions.append(
                ConnectorPosition(
                    instrument_id=str(instrument.get("isin") or instrument.get("ticker")),
                    ticker=str(instrument.get("ticker") or "UNKNOWN"),
                    name=name,
                    asset_type=(
                        AssetType.ETF
                        if "ETF" in str(name).upper() or "UCITS" in str(name).upper()
                        else AssetType.STOCK
                    ),
                    quantity=Decimal(str(item.get("quantity", 0))),
                    average_price=_decimal_or_none(item.get("averagePricePaid")),
                    current_value=Decimal(str(wallet.get("currentValue", 0))),
                    currency=str(wallet.get("currency") or instrument.get("currency") or "EUR"),
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
                )
            )
        return positions

    async def fetch_transactions(self, since: datetime | None) -> list[ConnectorTransaction]:
        orders, dividends, cash_movements = await self._recent_activity()
        transactions = [
            *_map_orders(orders),
            *_map_dividends(dividends),
            *_map_cash(cash_movements),
        ]
        if since:
            transactions = [item for item in transactions if item.executed_at > since]
        return transactions

    async def fetch_snapshot(self, snapshot_date: date) -> ConnectorSnapshot:
        summary = await self._summary()
        return ConnectorSnapshot(
            snapshot_date=snapshot_date,
            total_value=Decimal(str(summary.get("totalValue", 0))),
            currency=str(summary["currency"]),
        )

    async def _summary(self) -> dict[str, Any]:
        if self._account_summary is None:
            await self.validate_credentials()
        assert self._account_summary is not None
        return self._account_summary

    async def _recent_activity(self) -> tuple[list[Any], list[Any], list[Any]]:
        # The newest page is enough for the dashboard activity feed. Pulling every page
        # during an HTTP request would violate Trading 212's six-requests/minute limit.
        orders = await self._get("/equity/history/orders", {"limit": 50})
        dividends = await self._get("/equity/history/dividends", {"limit": 50})
        cash = await self._get("/equity/history/transactions", {"limit": 50})
        return (
            list((orders or {}).get("items", [])),
            list((dividends or {}).get("items", [])),
            list((cash or {}).get("items", [])),
        )


def _decimal_or_none(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


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
                    TransactionType.BUY
                    if order.get("side") == "BUY"
                    else TransactionType.SELL
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
