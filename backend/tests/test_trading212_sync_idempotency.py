from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.database import Base
from app.core.encryption import CredentialCipher
from app.integrations.connectors.base import (
    BrokerConnector,
    BrokerUnavailableError,
    ConnectorPosition,
    ConnectorSnapshot,
    ConnectorTransaction,
    ConnectorTransactionPage,
)
from app.models.broker import BrokerConnection
from app.models.enums import (
    AssetType,
    Broker,
    ConnectionStatus,
    SyncRunStatus,
    TransactionType,
)
from app.models.portfolio import PortfolioSnapshot, Position, Transaction
from app.models.sync import SyncCursor, SyncRun
from app.models.user import User
from app.services.connection_sync import ConnectionSyncService

TEST_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
ORDERS_CURSOR_1 = "/api/v0/equity/history/orders?limit=50&cursor=1"
ORDERS_CURSOR_2 = "/api/v0/equity/history/orders?limit=50&cursor=2"


class EurRates:
    async def convert_to_eur(
        self, value: Decimal, currency: str, as_of: date | None = None
    ) -> Decimal:
        assert currency == "EUR"
        return value


class AsyncSessionAdapter:
    """Exercise the async service against a real synchronous SQLite test database."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item: Any) -> None:
        self.session.add(item)

    def add_all(self, items: list[Any]) -> None:
        self.session.add_all(items)

    async def flush(self) -> None:
        self.session.flush()

    async def commit(self) -> None:
        self.session.commit()

    async def rollback(self) -> None:
        self.session.rollback()

    async def refresh(self, item: Any) -> None:
        self.session.refresh(item)

    async def execute(self, statement: Any):
        return self.session.execute(statement)

    async def scalar(self, statement: Any):
        return self.session.scalar(statement)

    async def scalars(self, statement: Any):
        return self.session.scalars(statement)

    async def get(self, model: type, item_id: Any):
        return self.session.get(model, item_id)


class PaginatedConnector(BrokerConnector):
    def __init__(
        self,
        pages: dict[str | None, ConnectorTransactionPage | Exception],
    ) -> None:
        super().__init__({})
        self.pages = pages
        self.requested_paths: list[str | None] = []

    async def validate_credentials(self) -> None:
        return None

    async def fetch_positions(self) -> list[ConnectorPosition]:
        return [
            ConnectorPosition(
                instrument_id="US0378331005",
                ticker="AAPL_US_EQ",
                name="Apple",
                asset_type=AssetType.STOCK,
                quantity=Decimal("2"),
                average_price=Decimal("100"),
                current_value=Decimal("220"),
                currency="EUR",
                canonical_symbol="AAPL",
                isin="US0378331005",
            )
        ]

    async def fetch_transactions(
        self, since: datetime | None
    ) -> list[ConnectorTransaction]:
        raise AssertionError("Paginated history must not use fetch_transactions")

    def transaction_history_streams(self) -> tuple[str, ...]:
        return ("orders",)

    async def fetch_transaction_page(
        self, stream: str, page_path: str | None = None
    ) -> ConnectorTransactionPage:
        assert stream == "orders"
        self.requested_paths.append(page_path)
        result = self.pages[page_path]
        if isinstance(result, Exception):
            raise result
        return result

    async def fetch_snapshot(self, snapshot_date: date) -> ConnectorSnapshot:
        return ConnectorSnapshot(snapshot_date, Decimal("250"), "EUR")


class BinanceActivityConnector(BrokerConnector):
    def __init__(self) -> None:
        super().__init__({})
        self.requested_since: list[datetime | None] = []

    async def validate_credentials(self) -> None:
        return None

    async def fetch_positions(self) -> list[ConnectorPosition]:
        return [
            ConnectorPosition(
                instrument_id="BINANCE:BTC",
                ticker="BTC",
                name="BTC",
                asset_type=AssetType.CRYPTO,
                quantity=Decimal("0.1"),
                average_price=None,
                current_value=Decimal("5000"),
                currency="EUR",
                canonical_symbol="BTC",
                reported_pnl=Decimal("125"),
            )
        ]

    async def fetch_transactions(
        self, since: datetime | None
    ) -> list[ConnectorTransaction]:
        self.requested_since.append(since)
        return [
            ConnectorTransaction(
                external_id="deposit:7",
                ticker="BTC",
                transaction_type=TransactionType.DEPOSIT,
                quantity=Decimal("0.1"),
                price=None,
                value=Decimal("0.1"),
                currency="BTC",
                executed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            )
        ]

    async def fetch_snapshot(self, snapshot_date: date) -> ConnectorSnapshot:
        return ConnectorSnapshot(
            snapshot_date, Decimal("5000"), "EUR", reported_pnl=Decimal("125")
        )


def _transaction(external_id: str, day: int) -> ConnectorTransaction:
    return ConnectorTransaction(
        external_id=external_id,
        ticker="AAPL_US_EQ",
        transaction_type=TransactionType.BUY,
        quantity=Decimal("1"),
        price=Decimal("100"),
        value=Decimal("100"),
        currency="EUR",
        executed_at=datetime(2026, 8, day, tzinfo=timezone.utc),
    )


def _database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


async def _connection(
    db, broker: Broker = Broker.TRADING212
) -> BrokerConnection:
    user = User(username="cursor-user", password_hash="hash")
    db.add(user)
    await db.flush()
    connection = BrokerConnection(
        user_id=user.id,
        broker=broker,
        encrypted_credentials=CredentialCipher(TEST_KEY).encrypt(
            {"api_key": "unused", "api_secret": "unused"}
        ),
        credential_hint="••••used",
        status=ConnectionStatus.PENDING,
    )
    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    return connection


@pytest.mark.asyncio
async def test_binance_activity_upgrade_backfills_once_then_syncs_incrementally() -> None:
    engine, session_factory = _database()
    try:
        with session_factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            connection = await _connection(db, Broker.BINANCE)
            connection.last_synced_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
            await db.commit()
            service = ConnectionSyncService(
                db, CredentialCipher(TEST_KEY), EurRates()  # type: ignore[arg-type]
            )

            initial = BinanceActivityConnector()
            await service.sync(connection, initial)
            incremental = BinanceActivityConnector()
            await service.sync(connection, incremental)

            cursor = await db.scalar(
                select(SyncCursor).where(SyncCursor.stream == "binance-activity-v1")
            )
            assert cursor is not None
            assert cursor.backfill_complete is True
            assert initial.requested_since == [None]
            assert incremental.requested_since[0] is not None
            assert await db.scalar(select(func.count()).select_from(Transaction)) == 1
            position = await db.scalar(select(Position))
            snapshot = await db.scalar(select(PortfolioSnapshot))
            assert position is not None
            assert position.reported_pnl == Decimal("125")
            assert position.reported_pnl_eur == Decimal("125")
            assert snapshot is not None
            assert snapshot.reported_pnl == Decimal("125")
            assert snapshot.reported_pnl_eur == Decimal("125")
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_repeated_sync_is_idempotent_for_transactions_positions_and_snapshots() -> None:
    engine, session_factory = _database()
    try:
        with session_factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            connection = await _connection(db)
            pages = {
                None: ConnectorTransactionPage(
                    [_transaction("order-fill:1", 1)], ORDERS_CURSOR_1
                ),
                ORDERS_CURSOR_1: ConnectorTransactionPage(
                    [_transaction("order-fill:2", 2)], None
                ),
            }
            service = ConnectionSyncService(
                db, CredentialCipher(TEST_KEY), EurRates()  # type: ignore[arg-type]
            )
            await service.sync(connection, PaginatedConnector(pages))
            await service.sync(connection, PaginatedConnector(pages))

            assert await db.scalar(select(func.count()).select_from(Transaction)) == 2
            assert await db.scalar(select(func.count()).select_from(Position)) == 1
            assert await db.scalar(select(func.count()).select_from(PortfolioSnapshot)) == 1
            runs = list(await db.scalars(select(SyncRun)))
            assert len(runs) == 2
            assert sorted(run.transactions_written for run in runs) == [0, 2]
            assert all(run.status is SyncRunStatus.SUCCESS for run in runs)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_failed_backfill_resumes_from_the_last_committed_cursor() -> None:
    engine, session_factory = _database()
    try:
        with session_factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            connection = await _connection(db)
            interrupted = PaginatedConnector(
                {
                    None: ConnectorTransactionPage(
                        [_transaction("order-fill:1", 1)], ORDERS_CURSOR_1
                    ),
                    ORDERS_CURSOR_1: ConnectorTransactionPage(
                        [_transaction("order-fill:2", 2)], ORDERS_CURSOR_2
                    ),
                    ORDERS_CURSOR_2: BrokerUnavailableError(
                        "Trading 212 is temporarily unavailable."
                    ),
                }
            )
            service = ConnectionSyncService(
                db, CredentialCipher(TEST_KEY), EurRates()  # type: ignore[arg-type]
            )
            failed = await service.sync(connection, interrupted)

            cursor = await db.scalar(select(SyncCursor))
            assert cursor is not None
            assert cursor.next_page_path == ORDERS_CURSOR_2
            assert cursor.backfill_complete is False
            assert failed.status is ConnectionStatus.ERROR
            assert await db.scalar(select(func.count()).select_from(Transaction)) == 2

            resumed = PaginatedConnector(
                {
                    None: ConnectorTransactionPage(
                        [_transaction("order-fill:1", 1)], ORDERS_CURSOR_1
                    ),
                    ORDERS_CURSOR_2: ConnectorTransactionPage(
                        [_transaction("order-fill:3", 3)], None
                    ),
                }
            )
            synced = await service.sync(connection, resumed)

            await db.refresh(cursor)
            assert resumed.requested_paths == [None, ORDERS_CURSOR_2]
            assert cursor.next_page_path is None
            assert cursor.backfill_complete is True
            assert synced.status is ConnectionStatus.ACTIVE
            assert await db.scalar(select(func.count()).select_from(Transaction)) == 3
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_completed_backfill_reads_new_pages_until_existing_history_overlap() -> None:
    engine, session_factory = _database()
    try:
        with session_factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            connection = await _connection(db)
            service = ConnectionSyncService(
                db, CredentialCipher(TEST_KEY), EurRates()  # type: ignore[arg-type]
            )
            await service.sync(
                connection,
                PaginatedConnector(
                    {
                        None: ConnectorTransactionPage(
                            [_transaction("order-fill:1", 1)], ORDERS_CURSOR_1
                        ),
                        ORDERS_CURSOR_1: ConnectorTransactionPage(
                            [_transaction("order-fill:2", 2)], None
                        ),
                    }
                ),
            )

            incremental = PaginatedConnector(
                {
                    None: ConnectorTransactionPage(
                        [_transaction("order-fill:4", 4)], ORDERS_CURSOR_1
                    ),
                    ORDERS_CURSOR_1: ConnectorTransactionPage(
                        [
                            _transaction("order-fill:3", 3),
                            _transaction("order-fill:2", 2),
                        ],
                        ORDERS_CURSOR_2,
                    ),
                }
            )
            await service.sync(connection, incremental)

            cursor = await db.scalar(select(SyncCursor))
            assert cursor is not None
            assert incremental.requested_paths == [None, ORDERS_CURSOR_1]
            assert cursor.backfill_complete is True
            assert cursor.next_page_path is None
            assert await db.scalar(select(func.count()).select_from(Transaction)) == 4
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_backfill_stays_within_six_requests_per_stream_and_saves_next_page() -> None:
    engine, session_factory = _database()
    try:
        with session_factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            connection = await _connection(db)

            def cursor(number: int) -> str:
                return f"/api/v0/equity/history/orders?limit=50&cursor={number}"

            pages: dict[str | None, ConnectorTransactionPage | Exception] = {
                None: ConnectorTransactionPage(
                    [_transaction("order-fill:0", 1)], cursor(1)
                )
            }
            for number in range(1, 6):
                pages[cursor(number)] = ConnectorTransactionPage(
                    [_transaction(f"order-fill:{number}", number + 1)],
                    cursor(number + 1),
                )
            connector = PaginatedConnector(pages)
            await ConnectionSyncService(
                db, CredentialCipher(TEST_KEY), EurRates()  # type: ignore[arg-type]
            ).sync(connection, connector)

            saved = await db.scalar(select(SyncCursor))
            assert saved is not None
            assert connector.requested_paths == [None, *(cursor(item) for item in range(1, 6))]
            assert saved.next_page_path == cursor(6)
            assert saved.backfill_complete is False
            assert await db.scalar(select(func.count()).select_from(Transaction)) == 6
    finally:
        engine.dispose()
