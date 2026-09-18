import asyncio
import hashlib
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.integrations.connectors.base import (
    BrokerConnector,
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


class InteractiveBrokersConnector(BrokerConnector):
    """Daily, read-only IBKR Activity Flex Query adapter."""

    base_url = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
    max_report_bytes = 20 * 1024 * 1024
    user_agent = "NorthstarPortfolio/1.0"

    def __init__(
        self,
        credentials: dict[str, str],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(credentials)
        self._transport = transport
        self._root: ET.Element | None = None
        self._positions: list[ConnectorPosition] | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Accept": "application/xml,text/xml", "User-Agent": self.user_agent},
            timeout=httpx.Timeout(30.0),
            transport=self._transport,
        )

    async def _request(self, path: str, params: dict[str, str]) -> httpx.Response:
        async def send() -> httpx.Response:
            async with self._client() as client:
                return await client.get(path, params=params)

        try:
            response = await request_with_backoff(send)
        except httpx.TimeoutException as exc:
            raise BrokerUnavailableError(
                "Interactive Brokers did not respond in time. Please try again."
            ) from exc
        except httpx.RequestError as exc:
            raise BrokerUnavailableError(
                "Could not reach Interactive Brokers. Please try again shortly."
            ) from exc
        if response.status_code == 429:
            retry_after = retry_after_seconds(response)
            raise BrokerRateLimitError(
                "Interactive Brokers' Flex request limit was reached. Try again later.",
                retry_after,
            )
        if response.status_code >= 500:
            raise BrokerUnavailableError(
                "Interactive Brokers reporting is temporarily unavailable."
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise BrokerUnavailableError(
                "Interactive Brokers returned an unexpected response."
            ) from exc
        if len(response.content) > self.max_report_bytes:
            raise ConnectorError("The Interactive Brokers Flex report is too large to import.")
        return response

    async def _fetch_report(self) -> ET.Element:
        if self._root is not None:
            return self._root
        token = self.credentials["flex_token"]
        query_id = self.credentials["query_id"]
        response = await self._request("/SendRequest", {"t": token, "q": query_id, "v": "3"})
        request_root = _parse_xml(response.content)
        _raise_flex_error(request_root)
        status = _child_text(request_root, "Status")
        reference = _child_text(request_root, "ReferenceCode")
        if status.lower() != "success" or not reference:
            raise BrokerUnavailableError("Interactive Brokers could not generate the Flex report.")

        report_root: ET.Element | None = None
        for attempt, delay in enumerate((0, 1, 2, 4)):
            if delay:
                await asyncio.sleep(delay)
            report = await self._request("/GetStatement", {"t": token, "q": reference, "v": "3"})
            candidate = _parse_xml(report.content)
            error_code = _child_text(candidate, "ErrorCode")
            if error_code in {"1003", "1004", "1005", "1006", "1007", "1008", "1019"}:
                if attempt < 3:
                    continue
                raise BrokerUnavailableError(
                    "Interactive Brokers is still preparing the Flex report. Sync again shortly."
                )
            _raise_flex_error(candidate)
            report_root = candidate
            break
        if report_root is None:
            raise BrokerUnavailableError("Interactive Brokers could not retrieve the Flex report.")
        if _local_name(report_root.tag) != "FlexQueryResponse" or not list(
            _elements(report_root, "FlexStatement")
        ):
            raise InvalidBrokerCredentials(
                "Use an XML Activity Flex Query containing Open Positions, Cash Report, "
                "Change in NAV, Trades, and Cash Transactions."
            )
        self._root = report_root
        return report_root

    async def validate_credentials(self) -> None:
        await self._fetch_report()

    async def fetch_positions(self) -> list[ConnectorPosition]:
        if self._positions is not None:
            return self._positions
        root = await self._fetch_report()
        securities: dict[tuple[str, str], dict[str, Any]] = {}
        cash: dict[str, Decimal] = defaultdict(Decimal)

        for row in _elements(root, "OpenPosition"):
            attrs = _attrs(row)
            symbol = _first(attrs, "symbol", "underlyingsymbol")
            quantity = _decimal(_first(attrs, "position", "quantity"))
            current_value = _decimal(_first(attrs, "positionvalue", "value"))
            if current_value == 0:
                current_value = quantity * _decimal(_first(attrs, "markprice", "closeprice"))
            currency = _first(attrs, "currency") or "USD"
            conid = _first(attrs, "conid", "contractid")
            security_id = _first(attrs, "securityid")
            security_type = _first(attrs, "securityidtype").upper()
            instrument_id = conid or security_id or f"{symbol}:{currency}"
            if not symbol or quantity == 0:
                continue
            key = (instrument_id, currency)
            cost = _decimal(_first(attrs, "costbasismoney", "costbasis"))
            average = _optional_decimal(_first(attrs, "openprice", "costprice", "costbasisprice"))
            if average is None and quantity:
                average = abs(cost / quantity) if cost else None
            pnl = _optional_decimal(_first(attrs, "fifopnlunrealized", "unrealizedpnl", "mtmpnl"))
            existing = securities.get(key)
            if existing is None:
                securities[key] = {
                    "instrument_id": f"IBKR:{instrument_id}",
                    "ticker": symbol,
                    "name": _first(attrs, "description") or symbol,
                    "asset_type": _asset_type(
                        " ".join(
                            filter(
                                None,
                                (
                                    _first(attrs, "assetcategory"),
                                    _first(attrs, "subcategory", "assetsubcategory"),
                                ),
                            )
                        )
                    ),
                    "quantity": quantity,
                    "average_cost": abs(cost),
                    "average_price": average,
                    "current_value": current_value,
                    "currency": currency,
                    "canonical_symbol": symbol,
                    "isin": _first(attrs, "isin")
                    or (security_id if security_type == "ISIN" else None),
                    "reported_pnl": pnl,
                }
            else:
                existing["quantity"] += quantity
                existing["average_cost"] += abs(cost)
                existing["current_value"] += current_value
                if pnl is not None:
                    existing["reported_pnl"] = (existing["reported_pnl"] or Decimal(0)) + pnl

        for item in securities.values():
            if item["average_cost"] and item["quantity"]:
                item["average_price"] = item["average_cost"] / abs(item["quantity"])
            item.pop("average_cost")

        for row in _elements(root, "CashReportCurrency"):
            attrs = _attrs(row)
            currency = _first(attrs, "currency").upper()
            level = _first(attrs, "levelofdetail").lower()
            if not currency or currency in {"BASE", "BASE_SUMMARY"} or "base" in level:
                continue
            ending_cash = _decimal(_first(attrs, "endingcash", "endingsettledcash"))
            cash[currency] += ending_cash

        positions = [ConnectorPosition(**item) for item in securities.values()]
        positions.extend(
            ConnectorPosition(
                instrument_id=f"IBKR:CASH:{currency}",
                ticker=currency,
                name=f"Cash ({currency})",
                asset_type=AssetType.CASH,
                quantity=amount,
                average_price=Decimal(1),
                current_value=amount,
                currency=currency,
                canonical_symbol=currency,
            )
            for currency, amount in cash.items()
            if amount != 0
        )
        self._positions = positions
        return positions

    async def fetch_transactions(self, since: datetime | None) -> list[ConnectorTransaction]:
        root = await self._fetch_report()
        normalized_since = _utc(since)
        transactions: list[ConnectorTransaction] = []

        for row in _elements(root, "Trade"):
            attrs = _attrs(row)
            level = _first(attrs, "levelofdetail").lower()
            if level and level not in {"execution", "executions"}:
                continue
            executed_at = _row_datetime(attrs)
            if executed_at is None or (normalized_since and executed_at <= normalized_since):
                continue
            side = _first(attrs, "buysell", "side").upper()
            if side not in {"BUY", "SELL", "BOT", "SLD"}:
                continue
            symbol = _first(attrs, "symbol") or "UNKNOWN"
            quantity = abs(_decimal(_first(attrs, "quantity", "tradequantity")))
            price = abs(_decimal(_first(attrs, "tradeprice", "price")))
            proceeds = abs(_decimal(_first(attrs, "proceeds", "trademoney")))
            currency = _first(attrs, "currency") or "USD"
            account = _first(attrs, "accountid")
            trade_id = _first(
                attrs, "tradeid", "transactionid", "ibexecid", "iborderid"
            ) or _stable_id(attrs)
            prefix = f"{account}:" if account else ""
            transactions.append(
                ConnectorTransaction(
                    external_id=f"trade:{prefix}{trade_id}",
                    ticker=symbol,
                    transaction_type=(
                        TransactionType.BUY if side in {"BUY", "BOT"} else TransactionType.SELL
                    ),
                    quantity=quantity,
                    price=price,
                    value=proceeds or quantity * price,
                    currency=currency,
                    executed_at=executed_at,
                )
            )
            commission = abs(_decimal(_first(attrs, "ibcommission", "commission")))
            if commission:
                commission_currency = _first(attrs, "ibcommissioncurrency") or currency
                transactions.append(
                    ConnectorTransaction(
                        external_id=f"trade-fee:{prefix}{trade_id}",
                        ticker=commission_currency,
                        transaction_type=TransactionType.FEE,
                        quantity=None,
                        price=None,
                        value=commission,
                        currency=commission_currency,
                        executed_at=executed_at,
                    )
                )

        for row in _elements(root, "CashTransaction"):
            attrs = _attrs(row)
            executed_at = _row_datetime(attrs)
            if executed_at is None or (normalized_since and executed_at <= normalized_since):
                continue
            description = " ".join(
                filter(None, (_first(attrs, "type"), _first(attrs, "description")))
            ).lower()
            amount = _decimal(_first(attrs, "amount", "netamount"))
            transaction_type: TransactionType | None = None
            if "dividend" in description or "payment in lieu" in description:
                transaction_type = TransactionType.DIVIDEND
            elif any(word in description for word in ("deposit", "withdraw", "transfer")):
                transaction_type = (
                    TransactionType.DEPOSIT if amount >= 0 else TransactionType.WITHDRAWAL
                )
            elif any(word in description for word in ("fee", "commission")):
                transaction_type = TransactionType.FEE
            if transaction_type is None or amount == 0:
                continue
            currency = _first(attrs, "currency") or "USD"
            symbol = _first(attrs, "symbol") or currency
            account = _first(attrs, "accountid")
            transaction_id = _first(attrs, "transactionid", "cashtransactionid") or _stable_id(
                attrs
            )
            prefix = f"{account}:" if account else ""
            transactions.append(
                ConnectorTransaction(
                    external_id=f"cash:{prefix}{transaction_id}",
                    ticker=symbol,
                    transaction_type=transaction_type,
                    quantity=None,
                    price=None,
                    value=abs(amount),
                    currency=currency,
                    executed_at=executed_at,
                )
            )
        return sorted(transactions, key=lambda item: (item.executed_at, item.external_id))

    async def fetch_snapshot(self, snapshot_date: date) -> ConnectorSnapshot:
        root = await self._fetch_report()
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for statement in _elements(root, "FlexStatement"):
            statement_attrs = _attrs(statement)
            default_currency = _first(statement_attrs, "basecurrency")
            for row in _elements(statement, "ChangeInNAV"):
                attrs = _attrs(row)
                currency = _first(attrs, "currency") or default_currency or "USD"
                ending = _optional_decimal(_first(attrs, "endingvalue", "endingnav"))
                if ending is not None:
                    totals[currency] += ending
        if len(totals) != 1:
            raise ConnectorError(
                "The Interactive Brokers Flex Query must include Change in NAV "
                "in one base currency."
            )
        currency, total = next(iter(totals.items()))
        return ConnectorSnapshot(
            snapshot_date=snapshot_date,
            total_value=total,
            currency=currency,
            independent_total=True,
        )


def _parse_xml(content: bytes) -> ET.Element:
    try:
        return ET.fromstring(content)
    except ET.ParseError as exc:
        raise InvalidBrokerCredentials(
            "Interactive Brokers returned a non-XML report. "
            "Set the Activity Flex Query format to XML."
        ) from exc


def _raise_flex_error(root: ET.Element) -> None:
    code = _child_text(root, "ErrorCode")
    if not code:
        return
    if code in {"1012", "1013", "1014", "1015", "1016", "1017", "1020"}:
        messages = {
            "1012": "The Interactive Brokers Flex token has expired.",
            "1013": "Interactive Brokers rejected this server's IP address.",
            "1014": "The Interactive Brokers Flex Query ID is invalid.",
            "1015": "The Interactive Brokers Flex token is invalid.",
        }
        raise InvalidBrokerCredentials(
            messages.get(code, "Interactive Brokers rejected the Flex token or Query ID.")
        )
    if code == "1018":
        raise BrokerRateLimitError(
            "Interactive Brokers' Flex request limit was reached. Try again later."
        )
    raise BrokerUnavailableError(
        "Interactive Brokers could not prepare the Flex report. Please try again later."
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _elements(root: ET.Element, name: str):
    return (element for element in root.iter() if _local_name(element.tag) == name)


def _child_text(root: ET.Element, name: str) -> str:
    for element in root.iter():
        if _local_name(element.tag) == name:
            return (element.text or "").strip()
    return ""


def _attrs(element: ET.Element) -> dict[str, str]:
    return {key.lower(): value.strip() for key, value in element.attrib.items()}


def _first(attrs: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = attrs.get(key.lower(), "")
        if value:
            return value
    return ""


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0).replace(",", ""))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def _optional_decimal(value: Any) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _asset_type(value: str) -> AssetType:
    normalized = value.upper()
    if any(kind in normalized for kind in ("ETF", "FUND", "MUTUAL FUND")):
        return AssetType.ETF
    if normalized in {"STK", "STOCK"}:
        return AssetType.STOCK
    if normalized in {"CRYPTO", "CRYPTOCURRENCY"}:
        return AssetType.CRYPTO
    if normalized in {"CASH", "FXCASH"}:
        return AssetType.CASH
    return AssetType.OTHER


def _row_datetime(attrs: dict[str, str]) -> datetime | None:
    combined = _first(attrs, "datetime", "dateTime", "reportdatetime")
    if not combined:
        date_value = _first(attrs, "tradedate", "date", "reportdate", "settledate")
        time_value = _first(attrs, "tradetime", "time")
        combined = f"{date_value};{time_value}" if time_value else date_value
    value = combined.strip()
    if not value:
        return None
    normalized = value.replace("T", ";").replace(" ", ";", 1)
    formats = (
        "%Y%m%d;%H%M%S",
        "%Y%m%d;%H:%M:%S",
        "%Y-%m-%d;%H:%M:%S",
        "%Y%m%d",
        "%Y-%m-%d",
    )
    for date_format in formats:
        try:
            return datetime.strptime(normalized, date_format).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _stable_id(attrs: dict[str, str]) -> str:
    payload = "|".join(f"{key}={attrs[key]}" for key in sorted(attrs))
    return hashlib.sha256(payload.encode()).hexdigest()[:24]
