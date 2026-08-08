import logging
import re
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import CredentialCipher
from app.integrations.connectors.base import (
    BrokerConnector,
    BrokerPermissionError,
    ConnectorError,
    ConnectorTransaction,
)
from app.integrations.connectors.registry import ConnectorRegistry
from app.integrations.market_data import EcbFxRateProvider, FxRateError, FxRateProvider
from app.models.broker import BrokerConnection
from app.models.enums import Broker, ConnectionStatus, SyncRunStatus, SyncTrigger
from app.models.portfolio import PortfolioSnapshot, Position, Transaction
from app.models.sync import SyncCursor, SyncRun
from app.services.instrument_resolver import InstrumentResolver

logger = logging.getLogger(__name__)

GENERIC_SYNC_ERROR = "The broker data could not be imported. Please try again."
MAX_BACKFILL_PAGES_PER_STREAM = 5
BINANCE_ACTIVITY_CURSOR = "binance-activity-v1"


class ConnectionSyncService:
    def __init__(
        self,
        db: AsyncSession,
        cipher: CredentialCipher,
        fx_rates: FxRateProvider | None = None,
    ) -> None:
        self.db = db
        self.cipher = cipher
        self.fx_rates = fx_rates or EcbFxRateProvider(db)

    async def sync(
        self,
        connection: BrokerConnection,
        connector: BrokerConnector | None = None,
        *,
        trigger: SyncTrigger = SyncTrigger.MANUAL,
    ) -> BrokerConnection:
        connection_id = connection.id
        attempted_at = datetime.now(timezone.utc)
        connection.last_sync_attempt_at = attempted_at
        run = SyncRun(
            broker_connection_id=connection_id,
            status=SyncRunStatus.RUNNING,
            trigger=trigger,
        )
        self.db.add(run)
        # Persist RUNNING independently so a later rollback cannot erase observability.
        await self.db.commit()
        await self.db.refresh(run)
        run_id = run.id

        try:
            connector = connector or ConnectorRegistry().create(
                connection.broker,
                self.cipher.decrypt(connection.encrypted_credentials),
            )
            await connector.validate_credentials()
            positions = await connector.fetch_positions()
            history_warning = None
            paginated_history = bool(connector.transaction_history_streams())
            transactions: list[ConnectorTransaction] = []
            binance_backfill_needed = False
            try:
                if paginated_history:
                    await self._sync_paginated_history(connection, connector, run)
                else:
                    transaction_since = connection.last_synced_at
                    if connection.broker is Broker.BINANCE:
                        activity_cursor = await self.db.scalar(
                            select(SyncCursor).where(
                                SyncCursor.broker_connection_id == connection.id,
                                SyncCursor.stream == BINANCE_ACTIVITY_CURSOR,
                            )
                        )
                        binance_backfill_needed = activity_cursor is None
                        if binance_backfill_needed:
                            transaction_since = None
                    transactions = await connector.fetch_transactions(transaction_since)
            except BrokerPermissionError as exc:
                history_warning = _safe_detail(exc)
            snapshot = await connector.fetch_snapshot(date.today())

            try:
                position_values_eur = [
                    await self.fx_rates.convert_to_eur(item.current_value, item.currency)
                    for item in positions
                ]
                position_pnl_eur = [
                    (
                        None
                        if item.reported_pnl is None
                        else await self.fx_rates.convert_to_eur(item.reported_pnl, item.currency)
                    )
                    for item in positions
                ]
                snapshot_value_eur = await self.fx_rates.convert_to_eur(
                    snapshot.total_value, snapshot.currency
                )
                snapshot_pnl_eur = (
                    None
                    if snapshot.reported_pnl is None
                    else await self.fx_rates.convert_to_eur(
                        snapshot.reported_pnl, snapshot.currency
                    )
                )
            except FxRateError as exc:
                raise ConnectorError(str(exc)) from exc

            resolver = InstrumentResolver(self.db)
            canonical_instruments = [
                await resolver.resolve(connection.broker, item) for item in positions
            ]

            await self.db.execute(
                delete(Position).where(Position.broker_connection_id == connection.id)
            )
            self.db.add_all(
                [
                    Position(
                        broker_connection_id=connection.id,
                        instrument_id=item.instrument_id,
                        canonical_instrument_id=canonical.id,
                        ticker=item.ticker,
                        name=item.name,
                        asset_type=canonical.asset_type,
                        quantity=item.quantity,
                        average_price=item.average_price,
                        current_value=item.current_value,
                        currency=item.currency,
                        current_value_eur=value_eur,
                        reported_pnl=item.reported_pnl,
                        reported_pnl_eur=pnl_eur,
                    )
                    for item, value_eur, pnl_eur, canonical in zip(
                        positions,
                        position_values_eur,
                        position_pnl_eur,
                        canonical_instruments,
                        strict=True,
                    )
                ]
            )

            new_transactions_written = 0
            if not paginated_history:
                new_transactions_written = await self._store_transactions(
                    connection.id, transactions
                )
                if binance_backfill_needed and history_warning is None:
                    self.db.add(
                        SyncCursor(
                            broker_connection_id=connection.id,
                            stream=BINANCE_ACTIVITY_CURSOR,
                            next_page_path=None,
                            backfill_complete=True,
                        )
                    )

            stored_snapshot = await self.db.scalar(
                select(PortfolioSnapshot).where(
                    PortfolioSnapshot.broker_connection_id == connection.id,
                    PortfolioSnapshot.snapshot_date == snapshot.snapshot_date,
                )
            )
            if stored_snapshot:
                stored_snapshot.total_value = snapshot.total_value
                stored_snapshot.currency = snapshot.currency
                stored_snapshot.total_value_eur = snapshot_value_eur
                stored_snapshot.reported_pnl = snapshot.reported_pnl
                stored_snapshot.reported_pnl_eur = snapshot_pnl_eur
            else:
                self.db.add(
                    PortfolioSnapshot(
                        broker_connection_id=connection.id,
                        snapshot_date=snapshot.snapshot_date,
                        total_value=snapshot.total_value,
                        currency=snapshot.currency,
                        total_value_eur=snapshot_value_eur,
                        reported_pnl=snapshot.reported_pnl,
                        reported_pnl_eur=snapshot_pnl_eur,
                    )
                )

            connection.status = (
                ConnectionStatus.LIMITED if history_warning else ConnectionStatus.ACTIVE
            )
            connection.last_error = history_warning
            completed_at = datetime.now(timezone.utc)
            connection.last_synced_at = completed_at
            connection.last_successful_sync_at = completed_at
            run.status = SyncRunStatus.PARTIAL if history_warning else SyncRunStatus.SUCCESS
            run.positions_written = len(positions)
            if not paginated_history:
                run.transactions_read = len(transactions)
                run.transactions_written = new_transactions_written
            run.warning_count = 1 if history_warning else 0
            run.safe_error_detail = history_warning
            run.finished_at = completed_at
            await self.db.commit()
        except ConnectorError as exc:
            await self.db.rollback()
            detail = _safe_detail(exc)
            connection, run = await self._reload(connection_id, run_id)
            connection.status = ConnectionStatus.ERROR
            connection.last_error = detail
            run.status = SyncRunStatus.ERROR
            run.safe_error_detail = detail
            run.finished_at = datetime.now(timezone.utc)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            logger.exception("Unexpected broker sync failure for connection %s", connection_id)
            connection, run = await self._reload(connection_id, run_id)
            connection.status = ConnectionStatus.ERROR
            connection.last_error = GENERIC_SYNC_ERROR
            run.status = SyncRunStatus.ERROR
            run.safe_error_detail = GENERIC_SYNC_ERROR
            run.finished_at = datetime.now(timezone.utc)
            await self.db.commit()

        await self.db.refresh(connection)
        return connection

    async def _sync_paginated_history(
        self,
        connection: BrokerConnection,
        connector: BrokerConnector,
        run: SyncRun,
    ) -> None:
        for stream in connector.transaction_history_streams():
            cursor = await self.db.scalar(
                select(SyncCursor).where(
                    SyncCursor.broker_connection_id == connection.id,
                    SyncCursor.stream == stream,
                )
            )
            resume_until_overlap = cursor is not None and cursor.backfill_complete
            head = await connector.fetch_transaction_page(stream)
            run.transactions_read += len(head.transactions)
            head_written = await self._store_transactions(connection.id, head.transactions)
            run.transactions_written += head_written

            if cursor is None:
                cursor = SyncCursor(
                    broker_connection_id=connection.id,
                    stream=stream,
                    next_page_path=head.next_page_path,
                    backfill_complete=head.next_page_path is None,
                )
                self.db.add(cursor)
            elif (
                resume_until_overlap
                and head.next_page_path is not None
                and (not head.transactions or head_written == len(head.transactions))
            ):
                # More than one page of activity arrived after the original backfill.
                cursor.next_page_path = head.next_page_path
                cursor.backfill_complete = False
            await self.db.commit()

            if cursor.backfill_complete:
                continue
            next_page_path = cursor.next_page_path
            seen_paths: set[str] = set()
            for _ in range(MAX_BACKFILL_PAGES_PER_STREAM):
                if not next_page_path:
                    break
                if next_page_path in seen_paths:
                    raise ConnectorError(
                        "Trading 212 repeated a history continuation. Backfill will resume later."
                    )
                seen_paths.add(next_page_path)
                page = await connector.fetch_transaction_page(stream, next_page_path)
                if page.next_page_path == next_page_path:
                    raise ConnectorError(
                        "Trading 212 repeated a history continuation. Backfill will resume later."
                    )
                run.transactions_read += len(page.transactions)
                page_written = await self._store_transactions(connection.id, page.transactions)
                run.transactions_written += page_written
                reached_overlap = (
                    resume_until_overlap
                    and bool(page.transactions)
                    and page_written < len(page.transactions)
                )
                cursor.next_page_path = None if reached_overlap else page.next_page_path
                cursor.backfill_complete = reached_overlap or page.next_page_path is None
                await self.db.commit()
                if reached_overlap:
                    break
                next_page_path = page.next_page_path

    async def _store_transactions(
        self,
        connection_id: uuid.UUID,
        transactions: list[ConnectorTransaction],
    ) -> int:
        if not transactions:
            return 0
        external_ids = {item.external_id for item in transactions}
        existing = set(
            await self.db.scalars(
                select(Transaction.external_id).where(
                    Transaction.broker_connection_id == connection_id,
                    Transaction.external_id.in_(external_ids),
                )
            )
        )
        unique_new: dict[str, ConnectorTransaction] = {}
        for item in transactions:
            if item.external_id not in existing:
                unique_new.setdefault(item.external_id, item)
        self.db.add_all(
            [
                Transaction(
                    broker_connection_id=connection_id,
                    external_id=item.external_id,
                    ticker=item.ticker,
                    transaction_type=item.transaction_type,
                    quantity=item.quantity,
                    price=item.price,
                    value=item.value,
                    currency=item.currency,
                    executed_at=item.executed_at,
                )
                for item in unique_new.values()
            ]
        )
        return len(unique_new)

    async def _reload(
        self, connection_id: uuid.UUID, run_id: uuid.UUID
    ) -> tuple[BrokerConnection, SyncRun]:
        connection = await self.db.get(BrokerConnection, connection_id)
        run = await self.db.get(SyncRun, run_id)
        assert connection is not None
        assert run is not None
        return connection, run


def _safe_detail(error: ConnectorError) -> str:
    """Bound connector-authored user-safe text before it reaches persistent storage."""

    detail = re.sub(r"[\x00-\x1f\x7f]+", " ", str(error)).strip()
    return detail[:500] or GENERIC_SYNC_ERROR
