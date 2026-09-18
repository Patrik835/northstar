import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import CredentialCipher
from app.integrations.connectors.base import ConnectorPosition
from app.integrations.market_data import EcbFxRateProvider, FxRateError, FxRateProvider
from app.models.broker import BrokerConnection
from app.models.enums import Broker, ConnectionStatus
from app.models.instrument import Instrument, InstrumentAlias
from app.models.portfolio import PortfolioSnapshot, Position
from app.schemas.portfolio import ManualPositionRead, ManualPositionWrite
from app.services.instrument_resolver import InstrumentResolver


class ManualPositionError(ValueError):
    pass


class ManualPositionService:
    def __init__(
        self,
        db: AsyncSession,
        cipher: CredentialCipher,
        fx_rates: FxRateProvider | None = None,
    ) -> None:
        self.db = db
        self.cipher = cipher
        self.fx_rates = fx_rates or EcbFxRateProvider(db)

    async def list(self, user_id: uuid.UUID) -> list[ManualPositionRead]:
        rows = await self.db.execute(
            select(Position, Instrument)
            .join(BrokerConnection, Position.broker_connection_id == BrokerConnection.id)
            .outerjoin(Instrument, Position.canonical_instrument_id == Instrument.id)
            .where(
                BrokerConnection.user_id == user_id,
                BrokerConnection.broker == Broker.MANUAL,
            )
            .order_by(Position.ticker)
        )
        return [self._read(position, instrument) for position, instrument in rows]

    async def create(
        self, user_id: uuid.UUID, payload: ManualPositionWrite
    ) -> ManualPositionRead:
        connection = await self._connection(user_id)
        position_id = uuid.uuid4()
        position, instrument = await self._build_position(
            connection, position_id, f"MANUAL:{position_id}", payload
        )
        self.db.add(position)
        await self._touch(connection)
        await self.db.commit()
        await self.db.refresh(position)
        return self._read(position, instrument)

    async def update(
        self,
        user_id: uuid.UUID,
        position_id: uuid.UUID,
        payload: ManualPositionWrite,
    ) -> ManualPositionRead | None:
        row = await self._owned(user_id, position_id)
        if row is None:
            return None
        position, connection = row
        await self.db.execute(
            delete(InstrumentAlias).where(
                InstrumentAlias.broker == Broker.MANUAL,
                InstrumentAlias.provider_instrument_id == position.instrument_id,
            )
        )
        await self.db.flush()
        replacement, instrument = await self._build_position(
            connection, position.id, position.instrument_id, payload
        )
        position.canonical_instrument_id = replacement.canonical_instrument_id
        position.ticker = replacement.ticker
        position.name = replacement.name
        position.asset_type = replacement.asset_type
        position.quantity = replacement.quantity
        position.average_price = replacement.average_price
        position.current_value = replacement.current_value
        position.currency = replacement.currency
        position.current_value_eur = replacement.current_value_eur
        position.reported_pnl = replacement.reported_pnl
        position.reported_pnl_eur = replacement.reported_pnl_eur
        position.valued_at = replacement.valued_at
        position.valuation_source = replacement.valuation_source
        position.is_estimated = replacement.is_estimated
        await self._touch(connection)
        await self.db.commit()
        await self.db.refresh(position)
        return self._read(position, instrument)

    async def delete(self, user_id: uuid.UUID, position_id: uuid.UUID) -> bool:
        row = await self._owned(user_id, position_id)
        if row is None:
            return False
        position, connection = row
        await self.db.delete(position)
        await self.db.flush()
        await self._touch(connection)
        await self.db.commit()
        return True

    async def _connection(self, user_id: uuid.UUID) -> BrokerConnection:
        connection = await self.db.scalar(
            select(BrokerConnection).where(
                BrokerConnection.user_id == user_id,
                BrokerConnection.broker == Broker.MANUAL,
            )
        )
        if connection is None:
            connection = BrokerConnection(
                user_id=user_id,
                broker=Broker.MANUAL,
                encrypted_credentials=self.cipher.encrypt({"source": "manual"}),
                credential_hint="Manual entries",
                status=ConnectionStatus.ACTIVE,
            )
            self.db.add(connection)
            await self.db.flush()
        return connection

    async def _owned(
        self, user_id: uuid.UUID, position_id: uuid.UUID
    ) -> tuple[Position, BrokerConnection] | None:
        row = await self.db.execute(
            select(Position, BrokerConnection)
            .join(BrokerConnection, Position.broker_connection_id == BrokerConnection.id)
            .where(
                Position.id == position_id,
                BrokerConnection.user_id == user_id,
                BrokerConnection.broker == Broker.MANUAL,
            )
        )
        return row.one_or_none()

    async def _build_position(
        self,
        connection: BrokerConnection,
        position_id: uuid.UUID,
        instrument_id: str,
        payload: ManualPositionWrite,
    ) -> tuple[Position, Instrument]:
        current_value = payload.quantity * payload.current_price
        open_pnl = (
            None
            if payload.average_price is None
            else (payload.current_price - payload.average_price) * payload.quantity
        )
        try:
            current_value_eur = await self.fx_rates.convert_to_eur(
                current_value, payload.currency
            )
            open_pnl_eur = (
                None
                if open_pnl is None
                else await self.fx_rates.convert_to_eur(open_pnl, payload.currency)
            )
        except FxRateError as exc:
            raise ManualPositionError(str(exc)) from exc

        connector_position = ConnectorPosition(
            instrument_id=instrument_id,
            ticker=payload.ticker,
            name=payload.name,
            asset_type=payload.asset_type,
            quantity=payload.quantity,
            average_price=payload.average_price,
            current_value=current_value,
            currency=payload.currency,
            canonical_symbol=payload.ticker,
            isin=payload.isin,
            reported_pnl=open_pnl,
        )
        instrument = await InstrumentResolver(self.db).resolve(
            Broker.MANUAL, connector_position
        )
        now = datetime.now(timezone.utc)
        return (
            Position(
                id=position_id,
                broker_connection_id=connection.id,
                instrument_id=instrument_id,
                canonical_instrument_id=instrument.id,
                ticker=payload.ticker,
                name=payload.name,
                asset_type=payload.asset_type,
                quantity=payload.quantity,
                average_price=payload.average_price,
                current_value=current_value,
                currency=payload.currency,
                current_value_eur=current_value_eur,
                reported_pnl=open_pnl,
                reported_pnl_eur=open_pnl_eur,
                valued_at=now,
                valuation_source="manual",
                is_estimated=True,
            ),
            instrument,
        )

    async def _touch(self, connection: BrokerConnection) -> None:
        now = datetime.now(timezone.utc)
        connection.status = ConnectionStatus.ACTIVE
        connection.last_error = None
        connection.last_sync_attempt_at = now
        connection.last_synced_at = now
        connection.last_successful_sync_at = now
        total = await self.db.scalar(
            select(func.coalesce(func.sum(Position.current_value_eur), 0)).where(
                Position.broker_connection_id == connection.id
            )
        )
        pnl = await self.db.scalar(
            select(func.sum(Position.reported_pnl_eur)).where(
                Position.broker_connection_id == connection.id
            )
        )
        snapshot = await self.db.scalar(
            select(PortfolioSnapshot).where(
                PortfolioSnapshot.broker_connection_id == connection.id,
                PortfolioSnapshot.snapshot_date == date.today(),
            )
        )
        if snapshot is None:
            snapshot = PortfolioSnapshot(
                broker_connection_id=connection.id,
                snapshot_date=date.today(),
                total_value=Decimal(total or 0),
                currency="EUR",
                total_value_eur=Decimal(total or 0),
                reported_pnl=Decimal(pnl) if pnl is not None else None,
                reported_pnl_eur=Decimal(pnl) if pnl is not None else None,
            )
            self.db.add(snapshot)
        else:
            snapshot.total_value = Decimal(total or 0)
            snapshot.total_value_eur = Decimal(total or 0)
            snapshot.reported_pnl = Decimal(pnl) if pnl is not None else None
            snapshot.reported_pnl_eur = Decimal(pnl) if pnl is not None else None

    @staticmethod
    def _read(position: Position, instrument: Instrument | None) -> ManualPositionRead:
        return ManualPositionRead(
            id=position.id,
            ticker=position.ticker,
            name=position.name,
            asset_type=position.asset_type,
            quantity=position.quantity,
            average_price=position.average_price,
            current_price=position.current_value / position.quantity,
            currency=position.currency,
            isin=instrument.isin if instrument else None,
            current_value=position.current_value,
            current_value_eur=position.current_value_eur,
            open_pnl=position.reported_pnl,
            open_pnl_eur=position.reported_pnl_eur,
            valued_at=position.valued_at,
        )
