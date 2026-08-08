import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.integrations.connectors.base import ConnectorPosition
from app.models.enums import AssetType, Broker
from app.models.instrument import Instrument, InstrumentAlias
from app.services.instrument_resolver import InstrumentResolver


class ResolverSession:
    def __init__(self) -> None:
        self.instruments: list[Instrument] = []
        self.aliases: list[InstrumentAlias] = []

    async def scalar(self, statement: Any) -> Instrument | InstrumentAlias | None:
        sql = str(statement)
        params = statement.compile().params
        if "FROM instrument_aliases" in sql:
            broker = next(value for key, value in params.items() if key.startswith("broker_"))
            provider_id = next(
                value
                for key, value in params.items()
                if key.startswith("provider_instrument_id_")
            )
            return next(
                (
                    alias
                    for alias in self.aliases
                    if alias.broker is broker
                    and alias.provider_instrument_id == provider_id
                ),
                None,
            )
        if any(key.startswith("identity_key_") for key in params):
            key = next(
                value for name, value in params.items() if name.startswith("identity_key_")
            )
            return next(
                (
                    instrument
                    for instrument in self.instruments
                    if instrument.identity_key == key
                ),
                None,
            )
        if any(key.startswith("isin_") for key in params):
            isin = next(value for key, value in params.items() if key.startswith("isin_"))
            return next(
                (instrument for instrument in self.instruments if instrument.isin == isin),
                None,
            )
        if any(key.startswith("canonical_symbol_") for key in params):
            symbol = next(
                value
                for key, value in params.items()
                if key.startswith("canonical_symbol_")
            )
            return next(
                (
                    instrument
                    for instrument in self.instruments
                    if instrument.canonical_symbol == symbol
                ),
                None,
            )
        raise AssertionError(f"Unexpected resolver query: {sql}")

    async def get(self, model: type[Instrument], model_id: uuid.UUID) -> Instrument | None:
        return next(
            (instrument for instrument in self.instruments if instrument.id == model_id),
            None,
        )

    def add(self, item: Instrument | InstrumentAlias) -> None:
        if item.id is None:
            item.id = uuid.uuid4()
        if isinstance(item, Instrument):
            self.instruments.append(item)
        else:
            self.aliases.append(item)

    async def flush(self) -> None:
        return None


def _position(
    instrument_id: str,
    ticker: str,
    asset_type: AssetType,
    *,
    canonical_symbol: str | None = None,
    isin: str | None = None,
) -> ConnectorPosition:
    return ConnectorPosition(
        instrument_id=instrument_id,
        ticker=ticker,
        name="Apple Inc." if asset_type is AssetType.STOCK else ticker,
        asset_type=asset_type,
        quantity=Decimal(1),
        average_price=None,
        current_value=Decimal(100),
        currency="EUR",
        canonical_symbol=canonical_symbol,
        isin=isin,
    )


@pytest.mark.asyncio
async def test_resolver_combines_broker_aliases_and_enriches_isin() -> None:
    session = ResolverSession()
    resolver = InstrumentResolver(session)  # type: ignore[arg-type]
    etoro = await resolver.resolve(
        Broker.ETORO,
        _position("ETORO:1001", "AAPL", AssetType.STOCK),
    )
    trading212 = await resolver.resolve(
        Broker.TRADING212,
        _position(
            "US0378331005",
            "AAPL_US_EQ",
            AssetType.STOCK,
            canonical_symbol="AAPL",
            isin="US0378331005",
        ),
    )

    assert etoro.id == trading212.id
    assert trading212.isin == "US0378331005"
    assert trading212.identity_key == "ISIN:US0378331005"
    assert len(session.instruments) == 1
    assert len(session.aliases) == 2


@pytest.mark.asyncio
async def test_resolver_combines_crypto_symbols_across_platforms() -> None:
    session = ResolverSession()
    resolver = InstrumentResolver(session)  # type: ignore[arg-type]
    binance = await resolver.resolve(
        Broker.BINANCE,
        _position("BINANCE:BTC", "BTC", AssetType.CRYPTO),
    )
    etoro = await resolver.resolve(
        Broker.ETORO,
        _position("ETORO:BTC", "BTC", AssetType.CRYPTO),
    )

    assert binance.id == etoro.id
    assert len(session.instruments) == 1
    assert len(session.aliases) == 2
