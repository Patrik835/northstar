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
)
from app.integrations.connectors.registry import ConnectorRegistry
from app.integrations.market_data import EcbFxRateProvider, FxRateError, FxRateProvider
from app.models.broker import BrokerConnection
from app.models.enums import ConnectionStatus, SyncRunStatus, SyncTrigger
from app.models.portfolio import PortfolioSnapshot, Position, Transaction
from app.models.sync import SyncRun
from app.services.instrument_resolver import InstrumentResolver

logger = logging.getLogger(__name__)

GENERIC_SYNC_ERROR = "The broker data could not be imported. Please try again."


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
            try:
                transactions = await connector.fetch_transactions(connection.last_synced_at)
            except BrokerPermissionError as exc:
                transactions = []
                history_warning = _safe_detail(exc)
            snapshot = await connector.fetch_snapshot(date.today())

            try:
                position_values_eur = [
                    await self.fx_rates.convert_to_eur(item.current_value, item.currency)
                    for item in positions
                ]
                snapshot_value_eur = await self.fx_rates.convert_to_eur(
                    snapshot.total_value, snapshot.currency
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
                        asset_type=item.asset_type,
                        quantity=item.quantity,
                        average_price=item.average_price,
                        current_value=item.current_value,
                        currency=item.currency,
                        current_value_eur=value_eur,
                    )
                    for item, value_eur, canonical in zip(
                        positions,
                        position_values_eur,
                        canonical_instruments,
                        strict=True,
                    )
                ]
            )

            existing_ids = set(
                await self.db.scalars(
                    select(Transaction.external_id).where(
                        Transaction.broker_connection_id == connection.id
                    )
                )
            )
            new_transactions = [
                item for item in transactions if item.external_id not in existing_ids
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
                        currency=item.currency,
                        executed_at=item.executed_at,
                    )
                    for item in new_transactions
                ]
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
            else:
                self.db.add(
                    PortfolioSnapshot(
                        broker_connection_id=connection.id,
                        snapshot_date=snapshot.snapshot_date,
                        total_value=snapshot.total_value,
                        currency=snapshot.currency,
                        total_value_eur=snapshot_value_eur,
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
            run.transactions_read = len(transactions)
            run.transactions_written = len(new_transactions)
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
