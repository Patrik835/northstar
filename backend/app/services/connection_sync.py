import logging
from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import CredentialCipher
from app.integrations.connectors.base import BrokerConnector, BrokerPermissionError, ConnectorError
from app.integrations.connectors.registry import ConnectorRegistry
from app.integrations.market_data import EcbFxRateProvider, FxRateError, FxRateProvider
from app.models.broker import BrokerConnection
from app.models.enums import ConnectionStatus
from app.models.portfolio import PortfolioSnapshot, Position, Transaction
from app.services.instrument_resolver import InstrumentResolver

logger = logging.getLogger(__name__)


class ConnectionSyncService:
    def __init__(
        self,
        db: AsyncSession,
        cipher: CredentialCipher,
        fx_rates: FxRateProvider | None = None,
    ) -> None:
        self.db = db
        self.cipher = cipher
        self.fx_rates = fx_rates or EcbFxRateProvider()

    async def sync(
        self,
        connection: BrokerConnection,
        connector: BrokerConnector | None = None,
    ) -> BrokerConnection:
        connection_id = connection.id
        connector = connector or ConnectorRegistry().create(
            connection.broker,
            self.cipher.decrypt(connection.encrypted_credentials),
        )
        try:
            await connector.validate_credentials()
            positions = await connector.fetch_positions()
            history_warning = None
            try:
                transactions = await connector.fetch_transactions(connection.last_synced_at)
            except BrokerPermissionError as exc:
                transactions = []
                history_warning = str(exc)
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
                    for item in transactions
                    if item.external_id not in existing_ids
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
            connection.last_synced_at = datetime.now(timezone.utc)
            await self.db.commit()
        except ConnectorError as exc:
            await self.db.rollback()
            connection = await self.db.get(BrokerConnection, connection_id)
            assert connection is not None
            connection.status = ConnectionStatus.ERROR
            connection.last_error = str(exc)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            logger.exception("Unexpected broker sync failure for connection %s", connection_id)
            connection = await self.db.get(BrokerConnection, connection_id)
            assert connection is not None
            connection.status = ConnectionStatus.ERROR
            connection.last_error = "The broker data could not be imported. Please try again."
            await self.db.commit()

        await self.db.refresh(connection)
        return connection
