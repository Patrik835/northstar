import csv
import hashlib
import io
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import CredentialCipher
from app.integrations.connectors.base import ConnectorPosition
from app.integrations.market_data import EcbFxRateProvider, FxRateError, FxRateProvider
from app.models.broker import BrokerConnection
from app.models.enums import AssetType, Broker, ConnectionStatus, TransactionType
from app.models.portfolio import PortfolioSnapshot, Position, Transaction
from app.repositories.connections import ConnectionRepository
from app.services.instrument_resolver import InstrumentResolver

MAX_BROKER_CSV_BYTES = 15 * 1024 * 1024
SUPPORTED_BROKERS = frozenset({Broker.TRADE_REPUBLIC, Broker.SCALABLE_CAPITAL})
ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


class BrokerCsvImportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedBrokerTransaction:
    external_id: str
    ticker: str
    name: str
    isin: str | None
    asset_type: AssetType
    transaction_type: TransactionType
    quantity: Decimal | None
    price: Decimal | None
    value: Decimal
    currency: str
    executed_at: datetime


@dataclass(frozen=True, slots=True)
class ParsedBrokerCsv:
    rows_read: int
    transactions: list[ParsedBrokerTransaction]
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class BrokerCsvImportSummary:
    connection: BrokerConnection
    rows_read: int
    transactions_added: int
    duplicates_skipped: int
    positions_imported: int
    warnings: list[str]


HEADER_ALIASES = {
    "datetime": {"datetime", "dateandtime", "timestamp", "executedat", "buchungszeit"},
    "date": {"date", "datum", "bookingdate", "transactiondate", "trade_date"},
    "time": {"time", "zeit", "trade_time"},
    "type": {
        "type",
        "typ",
        "ordertype",
        "transactiontype",
        "transaction_type",
        "operation",
        "action",
    },
    "status": {"status", "state", "zustand"},
    "asset_type": {
        "assetclass",
        "asset_class",
        "assettype",
        "instrumenttype",
        "producttype",
        "anlageklasse",
        "wertpapierart",
    },
    "name": {
        "name",
        "security",
        "securityname",
        "product",
        "productname",
        "instrument",
        "description",
        "wertpapier",
        "bezeichnung",
    },
    "symbol": {
        "symbol",
        "ticker",
        "isin",
        "securityid",
        "securityidentifier",
        "instrumentid",
        "wkn",
    },
    "isin": {"isin", "isincode", "isin_code"},
    "quantity": {
        "shares",
        "quantity",
        "units",
        "pieces",
        "numberofshares",
        "stuck",
        "stueck",
        "anzahl",
    },
    "price": {"price", "unitprice", "pricepershare", "quote", "kurs"},
    "amount": {
        "amount",
        "totalamount",
        "transactionvalue",
        "nettransactionvalue",
        "value",
        "betrag",
        "gesamtbetrag",
    },
    "fee": {"fee", "fees", "commission", "orderfee", "gebuhr", "gebuehr"},
    "tax": {"tax", "taxes", "withholdingtax", "steuer", "steuern"},
    "currency": {"currency", "curr", "transactioncurrency", "wahrung", "waehrung"},
    "id": {
        "transactionid",
        "transaction_id",
        "reference",
        "referenceid",
        "id",
        "orderid",
        "referenz",
    },
    "category": {"category", "kategorie"},
}


class BrokerCsvParser:
    """Parse native Trade Republic and Scalable Capital transaction exports."""

    def parse(self, broker: Broker, content: bytes) -> ParsedBrokerCsv:
        if broker not in SUPPORTED_BROKERS:
            raise BrokerCsvImportError("This broker CSV format is not supported.")
        if not content:
            raise BrokerCsvImportError("The selected CSV file is empty.")
        if len(content) > MAX_BROKER_CSV_BYTES:
            raise BrokerCsvImportError("The CSV file is larger than the 15 MB import limit.")

        text = _decode(content)
        try:
            dialect = csv.Sniffer().sniff(text[:16384], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            raise BrokerCsvImportError("The CSV has no header row.")
        fields = _resolve_fields(reader.fieldnames)
        missing = [field for field in ("type",) if field not in fields]
        if "datetime" not in fields and "date" not in fields:
            missing.append("date")
        if missing:
            display_name = _broker_name(broker)
            raise BrokerCsvImportError(
                f"This does not look like a {display_name} transaction export. "
                f"Missing columns for {', '.join(missing)}."
            )

        parsed: list[ParsedBrokerTransaction] = []
        warnings: list[str] = []
        skipped_investment_rows = 0
        rows_read = 0
        occurrence: dict[str, int] = {}
        for line_number, row in enumerate(reader, start=2):
            if not any(str(value or "").strip() for value in row.values()):
                continue
            rows_read += 1
            try:
                items, skipped_investment = self._parse_row(broker, row, fields, occurrence)
            except BrokerCsvImportError as exc:
                raise BrokerCsvImportError(f"CSV row {line_number}: {exc}") from exc
            parsed.extend(items)
            skipped_investment_rows += int(skipped_investment)

        if not parsed:
            raise BrokerCsvImportError(
                f"The CSV contains no supported {_broker_name(broker)} investment activity."
            )
        if skipped_investment_rows:
            warnings.append(
                f"{skipped_investment_rows} unsupported or incomplete security rows were "
                "ignored; review the resulting quantities if the export contains transfers "
                "or corporate actions."
            )
        return ParsedBrokerCsv(rows_read, _deduplicate(parsed), warnings)

    def _parse_row(
        self,
        broker: Broker,
        row: dict[str, str | None],
        fields: dict[str, str],
        occurrence: dict[str, int],
    ) -> tuple[list[ParsedBrokerTransaction], bool]:
        status = _value(row, fields, "status").casefold()
        raw_type = _value(row, fields, "type")
        category = _value(row, fields, "category")
        if any(token in status for token in ("cancel", "pending", "reject", "expired")):
            return [], False
        if any(token in raw_type.casefold() for token in ("cancelled", "canceled", "created")):
            return [], False

        quantity_hint = _decimal(_value(row, fields, "quantity"))
        amount_hint = _decimal(_value(row, fields, "amount"))
        transaction_type = _transaction_type(broker, raw_type, category, quantity_hint, amount_hint)
        if transaction_type is None:
            has_security_reference = any(
                ISIN_PATTERN.fullmatch(value)
                for value in (
                    _value(row, fields, "isin").upper().replace(" ", ""),
                    _value(row, fields, "symbol").upper().replace(" ", ""),
                )
            )
            return [], bool(quantity_hint) or has_security_reference

        executed_at = _parse_datetime(
            _value(row, fields, "datetime"),
            _value(row, fields, "date"),
            _value(row, fields, "time"),
        )
        name = _value(row, fields, "name") or "Unknown instrument"
        raw_symbol = _value(row, fields, "symbol").upper().replace(" ", "")
        explicit_isin = _value(row, fields, "isin").upper().replace(" ", "")
        isin = next(
            (value for value in (explicit_isin, raw_symbol) if ISIN_PATTERN.fullmatch(value)),
            None,
        )
        ticker = (raw_symbol or isin or _name_key(name))[:32]
        currency = _currency(_value(row, fields, "currency"))
        quantity = quantity_hint
        price = _decimal(_value(row, fields, "price"))
        amount = amount_hint
        fee = _decimal(_value(row, fields, "fee"))
        tax = _decimal(_value(row, fields, "tax"))
        asset_type = _asset_type(_value(row, fields, "asset_type"))

        investment_type = transaction_type in {TransactionType.BUY, TransactionType.SELL}
        if investment_type:
            if not ticker or quantity is None or quantity == 0:
                return [], True
            quantity = abs(quantity)
            if price is None and amount is not None:
                price = abs(amount) / quantity
            if amount is None and price is not None:
                amount = quantity * abs(price)
            if amount is None:
                return [], True
        else:
            amount = amount or Decimal(0)
            quantity = abs(quantity) if quantity is not None else None

        fingerprint = hashlib.sha256(
            "|".join(
                f"{_normalize_header(key)}={str(value or '').strip()}"
                for key, value in sorted(row.items())
            ).encode()
        ).hexdigest()[:32]
        occurrence[fingerprint] = occurrence.get(fingerprint, 0) + 1
        explicit_id = _value(row, fields, "id")
        row_id = explicit_id or f"{fingerprint}:{occurrence[fingerprint]}"
        row_id = row_id if len(row_id) <= 120 else hashlib.sha256(row_id.encode()).hexdigest()
        prefix = broker.value
        base = ParsedBrokerTransaction(
            external_id=f"{prefix}:{row_id}",
            ticker=ticker,
            name=name[:200],
            isin=isin,
            asset_type=asset_type,
            transaction_type=transaction_type,
            quantity=quantity,
            price=abs(price) if price is not None else None,
            value=abs(amount),
            currency=currency,
            executed_at=executed_at,
        )
        items = [base]
        for label, charge in (("fee", fee), ("tax", tax)):
            if charge is None or charge == 0:
                continue
            items.append(
                ParsedBrokerTransaction(
                    external_id=f"{prefix}:{row_id}:{label}",
                    ticker=ticker,
                    name=name[:200],
                    isin=isin,
                    asset_type=asset_type,
                    transaction_type=TransactionType.FEE,
                    quantity=None,
                    price=None,
                    value=abs(charge),
                    currency=currency,
                    executed_at=executed_at,
                )
            )
        return items, False


@dataclass(slots=True)
class _HoldingState:
    quantity: Decimal = Decimal(0)
    cost: Decimal = Decimal(0)
    last_price: Decimal | None = None
    currency: str = "EUR"


class BrokerCsvImportService:
    def __init__(
        self,
        db: AsyncSession,
        cipher: CredentialCipher,
        fx_rates: FxRateProvider | None = None,
    ) -> None:
        self.db = db
        self.cipher = cipher
        self.fx_rates = fx_rates or EcbFxRateProvider(db)

    async def import_csv(
        self, user_id: uuid.UUID, broker: Broker, content: bytes
    ) -> BrokerCsvImportSummary:
        parsed = BrokerCsvParser().parse(broker, content)
        connection = await ConnectionRepository(self.db).by_broker(user_id, broker)
        if connection is None:
            connection = BrokerConnection(
                user_id=user_id,
                broker=broker,
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
        new_items = [item for item in parsed.transactions if item.external_id not in existing_ids]
        warnings = list(parsed.warnings)
        values_eur: list[Decimal | None] = []
        historical_fx_missing = False
        for item in new_items:
            try:
                values_eur.append(
                    await self.fx_rates.convert_to_eur(
                        item.value, item.currency, item.executed_at.date()
                    )
                )
            except FxRateError:
                values_eur.append(None)
                historical_fx_missing = True
        if historical_fx_missing:
            warnings.append(
                "Some older activity has no stored ECB rate yet; its original amount "
                "was preserved without an estimated EUR value."
            )

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
                for item, value_eur in zip(new_items, values_eur, strict=True)
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
        existing_positions = list(
            await self.db.scalars(
                select(Position).where(Position.broker_connection_id == connection.id)
            )
        )
        metadata = {
            item.ticker: item
            for item in parsed.transactions
            if item.transaction_type in {TransactionType.BUY, TransactionType.SELL}
        }
        states = _reconstruct_holdings(all_transactions)
        now = datetime.now(timezone.utc)
        await self.db.execute(
            delete(Position).where(Position.broker_connection_id == connection.id)
        )

        resolver = InstrumentResolver(self.db)
        stored_positions: list[Position] = []
        total_value_eur = Decimal(0)
        total_pnl_eur = Decimal(0)
        has_pnl = False
        previous_by_ticker = {item.ticker: item for item in existing_positions}
        for ticker, state in states.items():
            if state.quantity <= 0:
                continue
            parsed_item = metadata.get(ticker)
            previous = previous_by_ticker.get(ticker)
            name = parsed_item.name if parsed_item else (previous.name if previous else ticker)
            isin = parsed_item.isin if parsed_item else _valid_isin(ticker)
            asset_type = (
                parsed_item.asset_type
                if parsed_item
                else (previous.asset_type if previous else AssetType.OTHER)
            )
            average_price = state.cost / state.quantity if state.quantity else None
            current_price = state.last_price or average_price or Decimal(0)
            current_value = state.quantity * current_price
            reported_pnl = current_value - state.cost
            try:
                current_value_eur = await self.fx_rates.convert_to_eur(
                    current_value, state.currency
                )
                reported_pnl_eur = await self.fx_rates.convert_to_eur(reported_pnl, state.currency)
            except FxRateError as exc:
                await self.db.rollback()
                raise BrokerCsvImportError(str(exc)) from exc

            connector_position = ConnectorPosition(
                instrument_id=isin or f"{broker.value}:{ticker}",
                ticker=ticker,
                name=name,
                asset_type=asset_type,
                quantity=state.quantity,
                average_price=average_price,
                current_value=current_value,
                currency=state.currency,
                canonical_symbol=ticker,
                isin=isin,
                reported_pnl=reported_pnl,
            )
            instrument = await resolver.resolve(broker, connector_position)
            stored_positions.append(
                Position(
                    broker_connection_id=connection.id,
                    instrument_id=connector_position.instrument_id[:120],
                    canonical_instrument_id=instrument.id,
                    ticker=ticker,
                    name=name,
                    asset_type=instrument.asset_type,
                    quantity=state.quantity,
                    average_price=average_price,
                    current_value=current_value,
                    currency=state.currency,
                    current_value_eur=current_value_eur,
                    reported_pnl=reported_pnl,
                    reported_pnl_eur=reported_pnl_eur,
                    valued_at=now,
                    valuation_source="last_imported_trade",
                    is_estimated=True,
                )
            )
            total_value_eur += current_value_eur
            total_pnl_eur += reported_pnl_eur
            has_pnl = True
        self.db.add_all(stored_positions)

        snapshot = await self.db.scalar(
            select(PortfolioSnapshot).where(
                PortfolioSnapshot.broker_connection_id == connection.id,
                PortfolioSnapshot.snapshot_date == now.date(),
            )
        )
        if snapshot:
            snapshot.total_value = total_value_eur
            snapshot.total_value_eur = total_value_eur
            snapshot.currency = "EUR"
            snapshot.reported_pnl = total_pnl_eur if has_pnl else None
            snapshot.reported_pnl_eur = total_pnl_eur if has_pnl else None
        else:
            self.db.add(
                PortfolioSnapshot(
                    broker_connection_id=connection.id,
                    snapshot_date=now.date(),
                    total_value=total_value_eur,
                    total_value_eur=total_value_eur,
                    currency="EUR",
                    reported_pnl=total_pnl_eur if has_pnl else None,
                    reported_pnl_eur=total_pnl_eur if has_pnl else None,
                )
            )

        warnings.append(
            "Current values and unrealized P/L use each holding's latest imported trade "
            "price and are marked as estimated."
        )
        connection.status = ConnectionStatus.ACTIVE
        connection.last_error = None
        connection.last_sync_attempt_at = now
        connection.last_successful_sync_at = now
        connection.last_synced_at = now
        connection.reconciliation_difference_percent = None
        connection.reconciliation_checked_at = None
        connection.reconciliation_warning = None
        await self.db.commit()
        await self.db.refresh(connection)
        return BrokerCsvImportSummary(
            connection=connection,
            rows_read=parsed.rows_read,
            transactions_added=len(new_items),
            duplicates_skipped=len(parsed.transactions) - len(new_items),
            positions_imported=len(stored_positions),
            warnings=_unique(warnings),
        )


def _reconstruct_holdings(transactions: list[Transaction]) -> dict[str, _HoldingState]:
    states: dict[str, _HoldingState] = {}
    for item in transactions:
        if item.transaction_type not in {TransactionType.BUY, TransactionType.SELL}:
            continue
        quantity = abs(item.quantity or Decimal(0))
        if quantity == 0:
            continue
        state = states.setdefault(item.ticker, _HoldingState())
        price = abs(item.price) if item.price is not None else abs(item.value) / quantity
        if item.transaction_type is TransactionType.BUY:
            state.quantity += quantity
            state.cost += abs(item.value)
        else:
            sold = min(quantity, state.quantity)
            average_cost = state.cost / state.quantity if state.quantity else Decimal(0)
            state.quantity -= sold
            state.cost = max(Decimal(0), state.cost - average_cost * sold)
        if state.quantity == 0:
            state.cost = Decimal(0)
        state.last_price = price
        state.currency = item.currency
    return states


def _transaction_type(
    broker: Broker,
    raw_type: str,
    category: str,
    quantity: Decimal | None,
    amount: Decimal | None,
) -> TransactionType | None:
    value = _normalize_header(f"{raw_type} {category}")
    if not value:
        return None
    if any(token in value for token in ("card", "cashwithdrawal", "cashdeposit")):
        return None
    if any(token in value for token in ("dividend", "distribution", "ausschuttung")):
        return TransactionType.DIVIDEND
    if "cryptoinvoice" in value:
        if quantity is not None and quantity < 0:
            return TransactionType.SELL
        return TransactionType.BUY if amount is None or amount < 0 else TransactionType.SELL
    if (
        any(
            token in value
            for token in (
                "savingsplan",
                "savingsplanexecuted",
                "sparplankauf",
                "savebackexecution",
                "sparechangeexecution",
            )
        )
        or re.search(r"(^|transaction)buy", value)
        or value.startswith("kauf")
    ):
        return TransactionType.BUY
    if re.search(r"(^|transaction)sell", value) or "verkauf" in value:
        return TransactionType.SELL
    if any(token in value for token in ("fee", "commission", "gebuhr", "taxes")):
        return TransactionType.FEE
    if broker is Broker.SCALABLE_CAPITAL:
        if any(token in value for token in ("deposit", "einzahlung")):
            return TransactionType.DEPOSIT
        if any(token in value for token in ("withdrawal", "auszahlung")):
            return TransactionType.WITHDRAWAL
    return None


def _asset_type(value: str) -> AssetType:
    normalized = _normalize_header(value)
    if "etf" in normalized or "exchangetradedfund" in normalized:
        return AssetType.ETF
    if any(token in normalized for token in ("stock", "share", "equity", "aktie")):
        return AssetType.STOCK
    if "crypto" in normalized:
        return AssetType.CRYPTO
    return AssetType.OTHER


def _resolve_fields(headers: list[str]) -> dict[str, str]:
    normalized = {_normalize_header(header): header for header in headers if header}
    fields: dict[str, str] = {}
    for field, aliases in HEADER_ALIASES.items():
        normalized_aliases = (_normalize_header(alias) for alias in aliases)
        original = next(
            (normalized[alias] for alias in normalized_aliases if alias in normalized),
            None,
        )
        if original:
            fields[field] = original
    return fields


def _value(row: dict[str, str | None], fields: dict[str, str], field: str) -> str:
    header = fields.get(field)
    return str(row.get(header) or "").strip() if header else ""


def _normalize_header(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]", "", ascii_value.casefold())


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BrokerCsvImportError("The CSV text encoding is not supported.")


def _decimal(value: str) -> Decimal | None:
    cleaned = value.strip()
    if not cleaned or cleaned.upper() in {"-", "—", "N/A", "NONE", "NULL"}:
        return None
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = re.sub(r"[^0-9,.-]", "", cleaned.strip("()"))
    if not cleaned or cleaned in {"-", ".", ","}:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        cleaned = "".join(parts[:-1]) + "." + parts[-1] if len(parts[-1]) <= 4 else "".join(parts)
    try:
        result = Decimal(cleaned)
    except InvalidOperation as exc:
        raise BrokerCsvImportError(f"'{value}' is not a valid number") from exc
    return -result if negative else result


def _parse_datetime(datetime_value: str, date_value: str, time_value: str) -> datetime:
    raw = datetime_value or " ".join(item for item in (date_value, time_value) if item)
    normalized = raw.strip().replace("Z", "+00:00")
    if not normalized:
        raise BrokerCsvImportError("a transaction has no date")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
        for pattern in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%Y-%m-%d",
            "%d.%m.%Y",
            "%d/%m/%Y",
        ):
            try:
                parsed = datetime.strptime(normalized, pattern)
                break
            except ValueError:
                continue
        if parsed is None:
            raise BrokerCsvImportError(f"'{raw}' is not a recognized date") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _currency(value: str) -> str:
    currency = value.strip().upper()
    if currency in {"€", "EURO"}:
        return "EUR"
    return currency if re.fullmatch(r"[A-Z]{3}", currency) else "EUR"


def _name_key(value: str) -> str:
    key = re.sub(r"[^A-Z0-9]", "", value.upper())
    return key[:32] or "UNKNOWN"


def _valid_isin(value: str) -> str | None:
    normalized = value.strip().upper()
    return normalized if ISIN_PATTERN.fullmatch(normalized) else None


def _deduplicate(items: list[ParsedBrokerTransaction]) -> list[ParsedBrokerTransaction]:
    return list({item.external_id: item for item in items}.values())


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _broker_name(broker: Broker) -> str:
    return "Trade Republic" if broker is Broker.TRADE_REPUBLIC else "Scalable Capital"
