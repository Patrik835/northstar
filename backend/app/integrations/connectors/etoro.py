import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx

from app.integrations.connectors.base import (
    BrokerConnector,
    BrokerPermissionError,
    BrokerRateLimitError,
    BrokerUnavailableError,
    ConnectorPosition,
    ConnectorSnapshot,
    ConnectorTransaction,
    InvalidBrokerCredentials,
)
from app.integrations.connectors.retry import request_with_backoff, retry_after_seconds
from app.models.enums import AssetType, TransactionType


class EtoroConnector(BrokerConnector):
    """Read-only adapter for eToro's real-account public API."""

    base_url = "https://public-api.etoro.com/api/v1"

    def __init__(
        self,
        credentials: dict[str, str],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(credentials)
        self._transport = transport
        self._portfolio: dict[str, Any] | None = None
        self._metadata: dict[int, dict[str, Any]] = {}
        self._instrument_types: dict[int, str] | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Accept": "application/json"},
            timeout=httpx.Timeout(20.0),
            transport=self._transport,
        )

    async def _get(
        self, path: str, params: dict[str, str | int] | None = None
    ) -> Any:
        headers = {
            "x-api-key": self.credentials["api_key"],
            "x-user-key": self.credentials["user_key"],
            "x-request-id": str(uuid.uuid4()),
        }
        async def send() -> httpx.Response:
            async with self._client() as client:
                return await client.get(path, params=params, headers=headers)

        try:
            response = await request_with_backoff(send)
        except httpx.TimeoutException as exc:
            raise BrokerUnavailableError(
                "eToro did not respond in time. Please try again."
            ) from exc
        except httpx.RequestError as exc:
            raise BrokerUnavailableError(
                "Could not reach eToro. Please try again shortly."
            ) from exc

        if response.status_code == 401:
            raise InvalidBrokerCredentials(
                "eToro rejected the Public Key or Private Key. Check both values "
                "and use a Real, read-only key."
            )
        if response.status_code == 403:
            raise BrokerPermissionError(
                "eToro denied portfolio access. Create a Real-environment key with Read permission."
            )
        if response.status_code == 429:
            retry_after = retry_after_seconds(response)
            suffix = (
                f" Try again in about {max(1, round(retry_after))} seconds."
                if retry_after is not None
                else " Wait before synchronizing again."
            )
            raise BrokerRateLimitError(
                f"eToro's request limit was reached.{suffix}", retry_after
            )
        if response.status_code >= 500:
            raise BrokerUnavailableError(
                "eToro is temporarily unavailable. Please try again shortly."
            )
        try:
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPStatusError, ValueError) as exc:
            raise BrokerUnavailableError(
                "eToro returned an unexpected response. Please try again."
            ) from exc

    async def validate_credentials(self) -> None:
        if self._portfolio is not None:
            return
        payload = await self._get("/trading/info/aggregate-portfolio")
        if (
            not isinstance(payload, dict)
            or not payload.get("accountCurrency")
            or not isinstance(payload.get("accountTotals"), dict)
        ):
            raise BrokerUnavailableError("eToro returned incomplete portfolio information.")
        self._portfolio = payload

    async def _load_metadata(self, instrument_ids: set[int]) -> None:
        missing = instrument_ids - self._metadata.keys()
        if not missing:
            return
        payload = await self._get(
            "/market-data/instruments",
            {"instrumentIds": ",".join(str(item) for item in sorted(missing))},
        )
        items = payload.get("instrumentDisplayDatas") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise BrokerUnavailableError("eToro returned invalid instrument information.")
        for item in items:
            instrument_id = item.get("instrumentID")
            if instrument_id is not None:
                self._metadata[int(instrument_id)] = item

        if self._instrument_types is None:
            types_payload = await self._get("/market-data/instrument-types")
            type_items = (
                types_payload.get("instrumentTypes")
                if isinstance(types_payload, dict)
                else None
            )
            if not isinstance(type_items, list):
                raise BrokerUnavailableError("eToro returned invalid instrument types.")
            self._instrument_types = {
                int(item["instrumentTypeID"]): str(item["instrumentTypeDescription"])
                for item in type_items
                if item.get("instrumentTypeID") is not None
            }

    def _asset_type(self, instrument_id: int) -> AssetType:
        metadata = self._metadata.get(instrument_id, {})
        type_id = metadata.get("instrumentTypeID")
        description = (self._instrument_types or {}).get(int(type_id), "") if type_id else ""
        normalized = description.lower()
        if "crypto" in normalized:
            return AssetType.CRYPTO
        if "etf" in normalized or "exchange traded fund" in normalized:
            return AssetType.ETF
        if "stock" in normalized or "share" in normalized or "equity" in normalized:
            return AssetType.STOCK
        return AssetType.OTHER

    async def fetch_positions(self) -> list[ConnectorPosition]:
        await self.validate_credentials()
        assert self._portfolio is not None
        aggregates = list(self._portfolio.get("instrumentAggregates") or [])
        instrument_ids = {
            int(item["instrumentId"])
            for item in aggregates
            if item.get("instrumentId") is not None
        }
        await self._load_metadata(instrument_ids)

        currency = str(self._portfolio["accountCurrency"]).upper()
        positions: list[ConnectorPosition] = []
        for item in aggregates:
            instrument_id = int(item["instrumentId"])
            metadata = self._metadata.get(instrument_id, {})
            ticker = str(metadata.get("symbolFull") or f"ETORO-{instrument_id}")
            current_value = Decimal(
                str(
                    item.get("liquidationValueAccountCurrency")
                    or item.get("netCurrentExposureAccountCurrency")
                    or 0
                )
            )
            positions.append(
                ConnectorPosition(
                    instrument_id=f"ETORO:{instrument_id}",
                    ticker=ticker,
                    name=metadata.get("instrumentDisplayName"),
                    asset_type=self._asset_type(instrument_id),
                    quantity=Decimal(str(item.get("netUnits", 0))),
                    average_price=_decimal_or_none(
                        item.get("netAvgOpenRate") or item.get("avgOpenRate")
                    ),
                    current_value=current_value,
                    currency=currency,
                    canonical_symbol=ticker,
                )
            )

        totals = self._portfolio["accountTotals"]
        available_cash = Decimal(str(totals.get("accountAvailableCash", 0)))
        if available_cash:
            positions.append(
                ConnectorPosition(
                    instrument_id=f"CASH:{currency}",
                    ticker=currency,
                    name=f"Cash ({currency})",
                    asset_type=AssetType.CASH,
                    quantity=available_cash,
                    average_price=None,
                    current_value=available_cash,
                    currency=currency,
                    canonical_symbol=currency,
                )
            )

        for mirror in self._portfolio.get("mirrors") or []:
            mirror_id = mirror.get("mirrorId")
            mirror_totals = mirror.get("mirrorTotals") or {}
            value = Decimal(str(mirror_totals.get("mirrorLiquidationValue", 0)))
            if mirror_id is None or not value:
                continue
            positions.append(
                ConnectorPosition(
                    instrument_id=f"ETORO:COPY:{mirror_id}",
                    ticker=f"COPY-{mirror_id}",
                    name=f"eToro Copy Portfolio {mirror_id}",
                    asset_type=AssetType.OTHER,
                    quantity=Decimal(1),
                    average_price=None,
                    current_value=value,
                    currency=currency,
                    canonical_symbol=f"COPY-{mirror_id}",
                )
            )
        return positions

    async def fetch_transactions(self, since: datetime | None) -> list[ConnectorTransaction]:
        await self.validate_credentials()
        start = since or datetime.now(timezone.utc) - timedelta(days=365)
        page_size = 100
        raw_items: list[dict[str, Any]] = []
        for page in range(1, 21):
            payload = await self._get(
                "/trading/info/trade/history",
                {"minDate": start.date().isoformat(), "page": page, "pageSize": page_size},
            )
            if isinstance(payload, list):
                items = payload
            elif isinstance(payload, dict):
                items = payload.get("items") or payload.get("trades") or []
            else:
                raise BrokerUnavailableError("eToro returned invalid trade history.")
            if not isinstance(items, list):
                raise BrokerUnavailableError("eToro returned invalid trade history.")
            raw_items.extend(item for item in items if isinstance(item, dict))
            if len(items) < page_size:
                break

        instrument_ids = {
            int(item["instrumentId"])
            for item in raw_items
            if item.get("instrumentId") is not None
        }
        await self._load_metadata(instrument_ids)
        assert self._portfolio is not None
        currency = str(self._portfolio["accountCurrency"]).upper()
        transactions: list[ConnectorTransaction] = []
        for item in raw_items:
            if not item.get("closeTimestamp") or item.get("instrumentId") is None:
                continue
            executed_at = _timestamp(str(item["closeTimestamp"]))
            if since and executed_at <= since:
                continue
            instrument_id = int(item["instrumentId"])
            metadata = self._metadata.get(instrument_id, {})
            ticker = str(metadata.get("symbolFull") or f"ETORO-{instrument_id}")
            quantity = abs(Decimal(str(item.get("units", 0))))
            price = _decimal_or_none(item.get("closeRate"))
            investment = Decimal(str(item.get("investment", item.get("initialInvestment", 0))))
            net_profit = Decimal(str(item.get("netProfit", 0)))
            value = abs(investment + net_profit)
            position_id = item.get("positionId") or item.get("orderId")
            transactions.append(
                ConnectorTransaction(
                    external_id=f"closed-position:{position_id}:{executed_at.isoformat()}",
                    ticker=ticker,
                    transaction_type=(
                        TransactionType.SELL if item.get("isBuy") else TransactionType.BUY
                    ),
                    quantity=quantity,
                    price=price,
                    value=value,
                    currency=currency,
                    executed_at=executed_at,
                )
            )
            fees = abs(Decimal(str(item.get("fees", 0))))
            if fees:
                transactions.append(
                    ConnectorTransaction(
                        external_id=f"closed-position-fee:{position_id}:{executed_at.isoformat()}",
                        ticker=ticker,
                        transaction_type=TransactionType.FEE,
                        quantity=None,
                        price=None,
                        value=fees,
                        currency=currency,
                        executed_at=executed_at,
                    )
                )
        return sorted(transactions, key=lambda item: item.executed_at)

    async def fetch_snapshot(self, snapshot_date: date) -> ConnectorSnapshot:
        await self.validate_credentials()
        assert self._portfolio is not None
        totals = self._portfolio["accountTotals"]
        return ConnectorSnapshot(
            snapshot_date=snapshot_date,
            total_value=Decimal(str(totals.get("accountTotalValue", 0))),
            currency=str(self._portfolio["accountCurrency"]).upper(),
        )


def _decimal_or_none(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
