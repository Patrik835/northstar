import csv
import hashlib
import io
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import CredentialCipher
from app.integrations.connectors.base import ConnectorPosition
from app.integrations.market_data import (
    BinanceCryptoPriceProvider,
    CryptoPriceError,
    EcbFxRateProvider,
    FxRateError,
    FxRateProvider,
)
from app.models.broker import BrokerConnection
from app.models.enums import AssetType, Broker, ConnectionStatus, TransactionType
from app.models.portfolio import PortfolioSnapshot, Position, Transaction
from app.repositories.connections import ConnectionRepository
from app.services.instrument_resolver import InstrumentResolver

MAX_CSV_BYTES = 10 * 1024 * 1024


class CryptoCsvImportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedCryptoTransaction:
    external_id: str
    transaction_type: TransactionType
    ticker: str
    quantity: Decimal | None
    price: Decimal | None
    value: Decimal
    currency: str
    executed_at: datetime


@dataclass(frozen=True, slots=True)
class ParsedCryptoCsv:
    rows_read: int
    transactions: list[ParsedCryptoTransaction]
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class CryptoImportSummary:
    connection: BrokerConnection
    rows_read: int
    transactions_added: int
    duplicates_skipped: int
    positions_imported: int
    warnings: list[str]


HEADER_ALIASES = {
    "type": {"type", "action", "transactiontype", "recordtype", "operation"},
    "status": {"status", "state"},
    "ticker": {
        "coin",
        "coinname",
        "asset",
        "crypto",
        "cryptocurrency",
        "symbol",
        "ticker",
    },
    "date": {
        "date",
        "time",
        "datetime",
        "dateandtime",
        "executedat",
        "timestamp",
        "createdat",
    },
    "quantity": {
        "quantity",
        "coinamount",
        "cryptoamount",
        "amountofcoin",
        "noofcoins",
        "units",
        "volume",
    },
    "price": {
        "price",
        "executionprice",
        "pricepercoin",
        "pricecoin",
        "rate",
        "filledprice",
    },
    "value": {
        "value",
        "total",
        "totalvalue",
        "totalamount",
        "fiatamount",
        "netamount",
        "amount",
    },
    "currency": {
        "currency",
        "fiatcurrency",
        "accountcurrency",
        "totalcurrency",
        "currencytotal",
    },
    "id": {"id", "transactionid", "reference", "orderid", "eventid"},
}


class Trading212CryptoCsvParser:
    def parse(self, content: bytes) -> ParsedCryptoCsv:
        if not content:
            raise CryptoCsvImportError("The selected CSV file is empty.")
        if len(content) > MAX_CSV_BYTES:
            raise CryptoCsvImportError("The CSV file is larger than the 10 MB import limit.")
        text = self._decode(content)
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            raise CryptoCsvImportError("The CSV has no header row.")
        fields = self._resolve_fields(reader.fieldnames)
        missing = [key for key in ("type", "date") if key not in fields]
        if missing:
            raise CryptoCsvImportError(
                "This does not look like a Trading 212 Crypto export. Missing columns for "
                f"{', '.join(missing)}. Export History as CSV and try again."
            )

        parsed: list[ParsedCryptoTransaction] = []
        warnings: list[str] = []
        occurrence: dict[str, int] = {}
        rows_read = 0
        for line_number, row in enumerate(reader, start=2):
            if not any(str(value or "").strip() for value in row.values()):
                continue
            rows_read += 1
            try:
                item = self._parse_row(row, fields, occurrence)
            except CryptoCsvImportError as exc:
                raise CryptoCsvImportError(f"CSV row {line_number}: {exc}") from exc
            if item is None:
                warnings.append(
                    f"Row {line_number} was skipped because it is not completed activity."
                )
            else:
                parsed.append(item)
        if not parsed:
            raise CryptoCsvImportError("The CSV contains no completed supported transactions.")
        return ParsedCryptoCsv(rows_read, parsed, warnings)

    @staticmethod
    def _decode(content: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-16"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise CryptoCsvImportError("The CSV must use UTF-8 or UTF-16 text encoding.")

    @staticmethod
    def _resolve_fields(headers: list[str]) -> dict[str, str]:
        normalized = {_normalize_header(header): header for header in headers}
        return {
            field: original
            for field, aliases in HEADER_ALIASES.items()
            if (
                original := next(
                    (normalized[item] for item in aliases if item in normalized), None
                )
            )
        }

    def _parse_row(
        self,
        row: dict[str, str | None],
        fields: dict[str, str],
        occurrence: dict[str, int],
    ) -> ParsedCryptoTransaction | None:
        status = self._value(row, fields, "status").lower()
        if status and not any(word in status for word in ("complete", "execut", "filled")):
            return None
        raw_type = self._value(row, fields, "type").lower()
        transaction_type = _transaction_type(raw_type)
        if transaction_type is None:
            return None

        executed_at = _parse_datetime(self._value(row, fields, "date"))
        ticker = self._value(row, fields, "ticker").upper().replace(" ", "")
        currency_value = self._value(row, fields, "currency").upper()
        raw_value = self._value(row, fields, "value")
        currency = currency_value or _currency_from_value(raw_value) or "EUR"
        quantity = _decimal(self._value(row, fields, "quantity"))
        price = _decimal(self._value(row, fields, "price"))
        value = _decimal(raw_value)

        if transaction_type in {TransactionType.BUY, TransactionType.SELL}:
            if not ticker:
                raise CryptoCsvImportError("a Buy or Sell row has no Coin/Symbol value")
            if quantity is None and price and value is not None:
                quantity = value / price
            if quantity is None or quantity == 0:
                raise CryptoCsvImportError("a Buy or Sell row has no usable quantity")
            quantity = abs(quantity)
            if value is None and price is not None:
                value = quantity * price
            if price is None and value is not None:
                price = value / quantity
            if value is None:
                raise CryptoCsvImportError("a Buy or Sell row has no usable price or total value")
        else:
            ticker = ticker or currency
            value = value or Decimal(0)
            quantity = abs(quantity) if quantity is not None else None

        explicit_id = self._value(row, fields, "id")
        fingerprint = hashlib.sha256(
            "|".join(
                f"{_normalize_header(key)}={str(value or '').strip()}"
                for key, value in sorted(row.items())
            ).encode()
        ).hexdigest()[:32]
        occurrence[fingerprint] = occurrence.get(fingerprint, 0) + 1
        external_id = explicit_id or f"{fingerprint}:{occurrence[fingerprint]}"
        if len(external_id) > 120:
            external_id = hashlib.sha256(external_id.encode()).hexdigest()
        return ParsedCryptoTransaction(
            external_id=f"trading212-crypto:{external_id}",
            transaction_type=transaction_type,
            ticker=ticker,
            quantity=quantity,
            price=abs(price) if price is not None else None,
            value=abs(value),
            currency=currency,
            executed_at=executed_at,
        )

    @staticmethod
    def _value(row: dict[str, str | None], fields: dict[str, str], field: str) -> str:
        header = fields.get(field)
        return str(row.get(header) or "").strip() if header else ""


class Trading212CryptoImportService:
    def __init__(
        self,
        db: AsyncSession,
        cipher: CredentialCipher,
        prices: BinanceCryptoPriceProvider | None = None,
        fx_rates: FxRateProvider | None = None,
    ) -> None:
        self.db = db
        self.cipher = cipher
        self.prices = prices or BinanceCryptoPriceProvider()
        self.fx_rates = fx_rates or EcbFxRateProvider(db)

    async def import_csv(self, user_id: uuid.UUID, content: bytes) -> CryptoImportSummary:
        parsed = Trading212CryptoCsvParser().parse(content)
        trades = [
            item
            for item in parsed.transactions
            if item.transaction_type in {TransactionType.BUY, TransactionType.SELL}
        ]
        if not trades:
            raise CryptoCsvImportError("The CSV contains no completed crypto Buy or Sell rows.")

        connection = await ConnectionRepository(self.db).by_broker(
            user_id, Broker.TRADING212_CRYPTO
        )
        if connection is None:
            connection = BrokerConnection(
                user_id=user_id,
                broker=Broker.TRADING212_CRYPTO,
                encrypted_credentials=self.cipher.encrypt({"source": "csv"}),
                credential_hint="CSV import",
                status=ConnectionStatus.PENDING,
            )
            self.db.add(connection)
            await self.db.flush()

        existing_ids = set(
            await self.db.scalars(
                select(Transaction.external_id).where(
                    Transaction.broker_connection_id == connection.id
                )
            )
        )
        converted: list[tuple[ParsedCryptoTransaction, Decimal]] = []
        for item in parsed.transactions:
            try:
                value_eur = await self.fx_rates.convert_to_eur(item.value, item.currency)
            except FxRateError as exc:
                await self.db.rollback()
                raise CryptoCsvImportError(str(exc)) from exc
            converted.append((item, value_eur))

        new_items = [
            (item, value_eur)
            for item, value_eur in converted
            if item.external_id not in existing_ids
        ]
        self.db.add_all(
            [
                Transaction(
                    broker_connection_id=connection.id,
                    external_id=item.external_id,
                    ticker=item.ticker,
                    transaction_type=item.transaction_type,
                    quantity=item.quantity,
                    price=item.price,
                    value=item.value,
                    value_eur=value_eur,
                    currency=item.currency,
                    executed_at=item.executed_at,
                )
                for item, value_eur in new_items
            ]
        )
        await self.db.flush()

        all_transactions = list(
            await self.db.scalars(
                select(Transaction)
                .where(Transaction.broker_connection_id == connection.id)
                .order_by(Transaction.executed_at, Transaction.external_id)
            )
        )
        states = _reconstruct_holdings(all_transactions)
        assets = {ticker for ticker, state in states.items() if state.quantity > 0}
        warnings = list(parsed.warnings)
        valuation_warnings: list[str] = []
        try:
            current_rates = await self.prices.rates_to_eur(assets)
        except CryptoPriceError:
            current_rates = {}
            valuation_warnings.append(
                "Live crypto prices were unavailable; last imported trade prices were used."
            )

        await self.db.execute(
            delete(Position).where(Position.broker_connection_id == connection.id)
        )
        resolver = InstrumentResolver(self.db)
        positions: list[Position] = []
        total_value = Decimal(0)
        for ticker in sorted(assets):
            state = states[ticker]
            rate = current_rates.get(ticker) or state.last_price_eur
            if rate is None:
                await self.db.rollback()
                raise CryptoCsvImportError(
                    f"No current or imported EUR price is available for {ticker}."
                )
            if ticker not in current_rates:
                valuation_warnings.append(
                    f"{ticker} is valued using its last imported trade price."
                )
            value_eur = state.quantity * rate
            total_value += value_eur
            connector_position = ConnectorPosition(
                instrument_id=f"TRADING212_CRYPTO:{ticker}",
                ticker=ticker,
                name=ticker,
                asset_type=AssetType.CRYPTO,
                quantity=state.quantity,
                average_price=(state.cost_eur / state.quantity if state.quantity else None),
                current_value=value_eur,
                currency="EUR",
                canonical_symbol=ticker,
            )
            instrument = await resolver.resolve(Broker.TRADING212_CRYPTO, connector_position)
            positions.append(
                Position(
                    broker_connection_id=connection.id,
                    instrument_id=connector_position.instrument_id,
                    canonical_instrument_id=instrument.id,
                    ticker=ticker,
                    name=ticker,
                    asset_type=AssetType.CRYPTO,
                    quantity=state.quantity,
                    average_price=connector_position.average_price,
                    current_value=value_eur,
                    currency="EUR",
                    current_value_eur=value_eur,
                )
            )
        self.db.add_all(positions)

        snapshot = await self.db.scalar(
            select(PortfolioSnapshot).where(
                PortfolioSnapshot.broker_connection_id == connection.id,
                PortfolioSnapshot.snapshot_date == date.today(),
            )
        )
        if snapshot:
            snapshot.total_value = total_value
            snapshot.total_value_eur = total_value
            snapshot.currency = "EUR"
        else:
            self.db.add(
                PortfolioSnapshot(
                    broker_connection_id=connection.id,
                    snapshot_date=date.today(),
                    total_value=total_value,
                    total_value_eur=total_value,
                    currency="EUR",
                )
            )

        warnings.extend(valuation_warnings)
        connection.status = (
            ConnectionStatus.LIMITED if valuation_warnings else ConnectionStatus.ACTIVE
        )
        connection.last_error = " ".join(valuation_warnings[:3]) or None
        completed_at = datetime.now(timezone.utc)
        connection.last_sync_attempt_at = completed_at
        connection.last_successful_sync_at = completed_at
        connection.last_synced_at = completed_at
        await self.db.commit()
        await self.db.refresh(connection)
        return CryptoImportSummary(
            connection=connection,
            rows_read=parsed.rows_read,
            transactions_added=len(new_items),
            duplicates_skipped=len(parsed.transactions) - len(new_items),
            positions_imported=len(positions),
            warnings=warnings,
        )


@dataclass(slots=True)
class _HoldingState:
    quantity: Decimal = Decimal(0)
    cost_eur: Decimal = Decimal(0)
    last_price_eur: Decimal | None = None


def _reconstruct_holdings(transactions: list[Transaction]) -> dict[str, _HoldingState]:
    states: dict[str, _HoldingState] = {}
    for item in transactions:
        if item.transaction_type not in {TransactionType.BUY, TransactionType.SELL}:
            continue
        quantity = abs(item.quantity or Decimal(0))
        if not quantity:
            continue
        state = states.setdefault(item.ticker.upper(), _HoldingState())
        value_eur = item.value_eur
        if value_eur is None:
            raise CryptoCsvImportError(
                "An earlier import has no EUR value. Re-import the full Trading 212 Crypto history."
            )
        state.last_price_eur = value_eur / quantity
        if item.transaction_type is TransactionType.BUY:
            state.quantity += quantity
            state.cost_eur += value_eur
        else:
            if quantity > state.quantity:
                raise CryptoCsvImportError(
                    f"{item.ticker} sells exceed imported buys. Export the full available history."
                )
            average_cost = state.cost_eur / state.quantity if state.quantity else Decimal(0)
            state.quantity -= quantity
            state.cost_eur -= average_cost * quantity
    return states


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _transaction_type(value: str) -> TransactionType | None:
    if "buy" in value:
        return TransactionType.BUY
    if "sell" in value:
        return TransactionType.SELL
    if "deposit" in value:
        return TransactionType.DEPOSIT
    if "withdraw" in value:
        return TransactionType.WITHDRAWAL
    if "fee" in value or "charge" in value:
        return TransactionType.FEE
    return None


def _currency_from_value(value: str) -> str | None:
    if "€" in value:
        return "EUR"
    if "$" in value:
        return "USD"
    if "£" in value:
        return "GBP"
    match = re.search(r"\b([A-Z]{3})\b", value.upper())
    return match.group(1) if match else None


def _decimal(value: str) -> Decimal | None:
    cleaned = value.strip()
    if not cleaned or cleaned in {"-", "—", "N/A"}:
        return None
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = re.sub(r"[^0-9,.-]", "", cleaned.strip("()"))
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        result = Decimal(cleaned)
    except InvalidOperation as exc:
        raise CryptoCsvImportError(f"'{value}' is not a valid number") from exc
    return -result if negative else result


def _parse_datetime(value: str) -> datetime:
    if not value:
        raise CryptoCsvImportError("a transaction has no date")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
        for pattern in (
            "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%d.%m.%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%Y-%m-%d",
        ):
            try:
                parsed = datetime.strptime(value, pattern)
                break
            except ValueError:
                continue
        if parsed is None:
            raise CryptoCsvImportError(f"'{value}' is not a recognized date") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
