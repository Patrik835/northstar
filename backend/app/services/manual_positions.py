import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import CredentialCipher
from app.integrations.connectors.base import ConnectorPosition
from app.integrations.market_data import EcbFxRateProvider, FxRateError, FxRateProvider
from app.integrations.market_data.current_prices import CurrentPriceError, CurrentPriceProvider
from app.models.broker import BrokerConnection
from app.models.enums import Broker, ConnectionStatus
from app.models.instrument import Instrument, InstrumentAlias
from app.models.portfolio import PortfolioSnapshot, Position
from app.models.user import User
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
        prices: CurrentPriceProvider | None = None,
    ) -> None:
        self.db = db
        self.cipher = cipher
        self.fx_rates = fx_rates or EcbFxRateProvider(db)
        self.prices = prices or CurrentPriceProvider()

    async def list(self, user_id: uuid.UUID) -> list[ManualPositionRead]:
        await self.refresh(user_id)
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

    async def create(self, user_id: uuid.UUID, payload: ManualPositionWrite) -> ManualPositionRead:
        connection = await self._connection(user_id)
        position_id = uuid.uuid4()
        position, instrument = await self._build_position(
            connection, position_id, f"MANUAL:{position_id}", payload
        )
        self.db.add(position)
        await self.db.flush()
        quoted = position.valuation_source != "manual_cost"
        position = await self._consolidate(connection, position)
        await self._touch(connection, refreshed=quoted)
        await self.db.commit()
        await self.db.refresh(position)
        instrument = await self.db.get(Instrument, position.canonical_instrument_id)
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
        position.note = replacement.note
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
        quoted = replacement.valuation_source != "manual_cost"
        position = await self._consolidate(connection, position)
        await self._touch(connection, refreshed=quoted)
        await self.db.commit()
        await self.db.refresh(position)
        instrument = await self.db.get(Instrument, position.canonical_instrument_id)
        return self._read(position, instrument)

    async def delete(self, user_id: uuid.UUID, position_id: uuid.UUID) -> bool:
        row = await self._owned(user_id, position_id)
        if row is None:
            return False
        position, connection = row
        await self.db.execute(
            delete(InstrumentAlias).where(
                InstrumentAlias.broker == Broker.MANUAL,
                InstrumentAlias.provider_instrument_id == position.instrument_id,
            )
        )
        await self.db.delete(position)
        await self.db.flush()
        await self._touch(connection)
        await self.db.commit()
        return True

    async def _lock_user(self, user_id: uuid.UUID) -> None:
        # Serialize manual mutations, including first-connection creation and read refreshes.
        await self.db.scalar(select(User.id).where(User.id == user_id).with_for_update())

    async def _connection(self, user_id: uuid.UUID) -> BrokerConnection:
        await self._lock_user(user_id)
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
        await self._lock_user(user_id)
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
        unit_price = payload.current_price or payload.average_price
        assert unit_price is not None
        current_value = payload.quantity * unit_price
        open_pnl = (
            None
            if payload.average_price is None or payload.current_price is None
            else (unit_price - payload.average_price) * payload.quantity
        )
        try:
            current_value_eur = await self.fx_rates.convert_to_eur(current_value, payload.currency)
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
        instrument = await InstrumentResolver(self.db).resolve(Broker.MANUAL, connector_position)
        now = datetime.now(timezone.utc)
        position = Position(
            id=position_id,
            broker_connection_id=connection.id,
            instrument_id=instrument_id,
            canonical_instrument_id=instrument.id,
            ticker=payload.ticker,
            name=payload.name,
            note=payload.note,
            asset_type=payload.asset_type,
            quantity=payload.quantity,
            average_price=payload.average_price,
            current_value=current_value,
            currency=payload.currency,
            current_value_eur=current_value_eur,
            reported_pnl=open_pnl,
            reported_pnl_eur=open_pnl_eur,
            valued_at=now,
            valuation_source="manual" if payload.current_price is not None else "manual_cost",
            is_estimated=True,
        )
        if payload.current_price is None:
            await self._mark_to_market(position)
        return position, instrument

    async def _mark_to_market(self, position: Position) -> bool:
        try:
            price, currency, as_of = await self.prices.price(position.ticker, position.asset_type)
            price_eur = await self.fx_rates.convert_to_eur(price, currency)
            unit_eur = await self.fx_rates.convert_to_eur(Decimal(1), position.currency)
            if not price_eur.is_finite() or price_eur <= 0 or unit_eur <= 0:
                return False
            current_price = price_eur / unit_eur
            pnl = (
                (current_price - position.average_price) * position.quantity
                if position.average_price is not None
                else None
            )
        except (CurrentPriceError, FxRateError):
            return False
        position.current_value = current_price * position.quantity
        position.current_value_eur = price_eur * position.quantity
        position.reported_pnl = pnl
        position.reported_pnl_eur = pnl * unit_eur if pnl is not None else None
        position.valued_at = as_of
        position.valuation_source = "market"
        position.is_estimated = True
        return True

    async def _consolidate(
        self, connection: BrokerConnection, incoming: Position | None = None
    ) -> Position | None:
        rows = list(
            await self.db.scalars(
                select(Position)
                .where(Position.broker_connection_id == connection.id)
                .order_by(Position.id)
            )
        )
        # Preserve an existing entry's ID when a new purchase is added.
        if incoming is not None:
            rows = [row for row in rows if row.id != incoming.id] + [incoming]
        grouped = {}
        survivor = incoming
        for position in rows:
            key = (position.ticker, position.asset_type, position.canonical_instrument_id)
            target = grouped.get(key)
            if target is None:
                grouped[key] = position
                continue
            if target.currency == position.currency:
                unit_eur = source_unit_eur = Decimal(1)
            else:
                unit_eur = await self.fx_rates.convert_to_eur(Decimal(1), target.currency)
                source_unit_eur = await self.fx_rates.convert_to_eur(Decimal(1), position.currency)
            quantity = target.quantity + position.quantity
            average_price = (
                (
                    target.average_price * target.quantity
                    + position.average_price * position.quantity * source_unit_eur / unit_eur
                )
                / quantity
                if target.average_price is not None and position.average_price is not None
                else None
            )
            notes = list(dict.fromkeys(note for note in (target.note, position.note) if note))
            target.note = "\n\n".join(notes) or None
            target.current_value += position.current_value * source_unit_eur / unit_eur
            target.current_value_eur += position.current_value_eur
            target.quantity = quantity
            target.average_price = average_price
            if target.reported_pnl is not None and position.reported_pnl is not None:
                target.reported_pnl += position.reported_pnl * source_unit_eur / unit_eur
                target.reported_pnl_eur += position.reported_pnl_eur
            else:
                target.reported_pnl = None
                target.reported_pnl_eur = None
            # Until the next successful quote, retain the oldest component's timestamp.
            target.valued_at = min(
                target.valued_at,
                position.valued_at,
                key=lambda value: (
                    value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
                ),
            )
            if target.valuation_source != position.valuation_source:
                target.valuation_source = "manual"
            target.is_estimated = target.is_estimated or position.is_estimated
            if incoming is not None and position.id == incoming.id:
                survivor = target
            await self.db.execute(
                delete(InstrumentAlias).where(
                    InstrumentAlias.broker == Broker.MANUAL,
                    InstrumentAlias.provider_instrument_id == position.instrument_id,
                )
            )
            await self.db.delete(position)
        await self.db.flush()
        return survivor

    async def refresh(self, user_id: uuid.UUID) -> None:
        connections = list(
            await self.db.scalars(
                select(BrokerConnection).where(
                    BrokerConnection.user_id == user_id,
                    BrokerConnection.broker == Broker.MANUAL,
                )
            )
        )
        if not connections:
            return
        inputs = ("ticker", "asset_type", "quantity", "average_price", "currency")
        outputs = (
            "current_value",
            "current_value_eur",
            "reported_pnl",
            "reported_pnl_eur",
            "valued_at",
            "valuation_source",
            "is_estimated",
        )
        quotes = {}
        for connection in connections:
            positions = await self.db.scalars(
                select(Position).where(Position.broker_connection_id == connection.id)
            )
            for position in positions:
                original = tuple(getattr(position, field) for field in inputs)
                quoted = SimpleNamespace(**{field: getattr(position, field) for field in inputs})
                success = await self._mark_to_market(quoted)
                quotes[position.id] = (original, quoted, success)
        # Fetch quotes before locking. Re-read and apply only to unchanged inputs.
        await self._lock_user(user_id)
        for connection in connections:
            positions = list(
                await self.db.scalars(
                    select(Position)
                    .where(Position.broker_connection_id == connection.id)
                    .execution_options(populate_existing=True)
                )
            )
            success = True
            changed = False
            for position in positions:
                quote = quotes.get(position.id)
                if quote is None or quote[0] != tuple(getattr(position, field) for field in inputs):
                    changed = True
                    continue
                if not quote[2]:
                    success = False
                    continue
                current_at = position.valued_at
                current_at = (
                    current_at.replace(tzinfo=timezone.utc)
                    if current_at.tzinfo is None
                    else current_at
                )
                if position.valuation_source == "market" and quote[1].valued_at < current_at:
                    changed = True
                    continue
                for field in outputs:
                    setattr(position, field, getattr(quote[1], field))
            await self._consolidate(connection)
            await self.db.flush()
            await self._touch(connection, refreshed=None if changed else success)
        await self.db.commit()

    async def _touch(self, connection: BrokerConnection, *, refreshed: bool | None = None) -> None:
        now = datetime.now(timezone.utc)
        positions = list(
            await self.db.scalars(
                select(Position).where(Position.broker_connection_id == connection.id)
            )
        )
        if refreshed is not None:
            connection.last_sync_attempt_at = now
        if refreshed:
            connection.status = ConnectionStatus.ACTIVE
            connection.last_error = None
            connection.last_successful_sync_at = min(
                (
                    position.valued_at.replace(tzinfo=timezone.utc)
                    if position.valued_at.tzinfo is None
                    else position.valued_at
                    for position in positions
                ),
                default=now,
            )
            connection.last_synced_at = connection.last_successful_sync_at
        elif refreshed is False:
            connection.status = ConnectionStatus.ERROR
            connection.last_error = "Current market price unavailable; last valuation preserved"
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
            note=position.note,
            asset_type=position.asset_type,
            quantity=position.quantity,
            average_price=position.average_price,
            current_price=(
                position.current_value / position.quantity
                if position.valuation_source != "manual_cost"
                else None
            ),
            currency=position.currency,
            isin=instrument.isin if instrument else None,
            current_value=position.current_value,
            current_value_eur=position.current_value_eur,
            open_pnl=position.reported_pnl,
            open_pnl_eur=position.reported_pnl_eur,
            valued_at=position.valued_at,
        )
