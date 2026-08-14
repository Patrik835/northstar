import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.connectors.base import ConnectorPosition
from app.models.enums import AssetType, Broker
from app.models.instrument import Instrument, InstrumentAlias

ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
SECURITY_TYPES = (AssetType.STOCK, AssetType.ETF)


def normalized_symbol(position: ConnectorPosition) -> str:
    value = position.canonical_symbol or position.ticker
    return re.sub(r"\s+", "", value).upper()


def valid_isin(position: ConnectorPosition) -> str | None:
    value = (position.isin or "").strip().upper()
    return value if ISIN_PATTERN.fullmatch(value) else None


def identity_key(broker: Broker, position: ConnectorPosition) -> str:
    symbol = normalized_symbol(position)
    isin = valid_isin(position)
    if isin:
        return f"ISIN:{isin}"
    if position.asset_type in SECURITY_TYPES:
        return f"SECURITY:{symbol}"
    if position.asset_type is AssetType.CRYPTO:
        return f"CRYPTO:{symbol}"
    if position.asset_type is AssetType.CASH:
        return f"CASH:{symbol}"
    return f"PROVIDER:{broker.value}:{position.instrument_id}"


class InstrumentResolver:
    """Links provider positions to shared instruments while retaining exact aliases."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolve(self, broker: Broker, position: ConnectorPosition) -> Instrument:
        alias = await self.db.scalar(
            select(InstrumentAlias).where(
                InstrumentAlias.broker == broker,
                InstrumentAlias.provider_instrument_id == position.instrument_id,
            )
        )
        if alias:
            instrument = await self.db.get(Instrument, alias.instrument_id)
            assert instrument is not None
            self._refresh(instrument, alias, position)
            return instrument

        instrument = await self._find_instrument(broker, position)
        if instrument is None:
            symbol = normalized_symbol(position)
            instrument = Instrument(
                identity_key=identity_key(broker, position),
                canonical_symbol=symbol,
                name=position.name or symbol,
                asset_type=position.asset_type,
                isin=valid_isin(position),
            )
            self.db.add(instrument)
            await self.db.flush()
        else:
            self._enrich(instrument, position)

        alias = InstrumentAlias(
            instrument_id=instrument.id,
            broker=broker,
            provider_instrument_id=position.instrument_id,
            provider_symbol=position.ticker,
            provider_name=position.name,
        )
        self.db.add(alias)
        await self.db.flush()
        return instrument

    async def _find_instrument(
        self, broker: Broker, position: ConnectorPosition
    ) -> Instrument | None:
        isin = valid_isin(position)
        if isin:
            by_isin = await self.db.scalar(select(Instrument).where(Instrument.isin == isin))
            if by_isin:
                return by_isin

        key = identity_key(broker, position)
        by_key = await self.db.scalar(select(Instrument).where(Instrument.identity_key == key))
        if by_key:
            return by_key

        symbol = normalized_symbol(position)
        if position.asset_type in SECURITY_TYPES:
            return await self.db.scalar(
                select(Instrument).where(
                    Instrument.canonical_symbol == symbol,
                    Instrument.asset_type.in_(SECURITY_TYPES),
                )
            )
        if position.asset_type in {AssetType.CRYPTO, AssetType.CASH}:
            return await self.db.scalar(
                select(Instrument).where(
                    Instrument.canonical_symbol == symbol,
                    Instrument.asset_type == position.asset_type,
                )
            )
        return None

    def _refresh(
        self,
        instrument: Instrument,
        alias: InstrumentAlias,
        position: ConnectorPosition,
    ) -> None:
        alias.provider_symbol = position.ticker
        alias.provider_name = position.name
        alias.last_seen_at = datetime.now(timezone.utc)
        self._enrich(instrument, position)

    @staticmethod
    def _enrich(instrument: Instrument, position: ConnectorPosition) -> None:
        instrument.canonical_symbol = normalized_symbol(position)
        isin = valid_isin(position)
        if isin and not instrument.isin:
            instrument.isin = isin
            instrument.identity_key = f"ISIN:{isin}"
        if position.name and (
            instrument.name == instrument.canonical_symbol
            or len(position.name) > len(instrument.name)
        ):
            instrument.name = position.name
        if position.asset_type is not AssetType.OTHER:
            instrument.asset_type = position.asset_type
