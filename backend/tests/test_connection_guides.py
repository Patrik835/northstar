from typing import cast

import pytest

from app.api.v1.connections import guides
from app.models.enums import Broker
from app.models.user import User


@pytest.mark.asyncio
async def test_connection_guides_are_built_from_connector_catalogs() -> None:
    result = await guides(cast(User, object()))
    by_broker = {guide.broker: guide for guide in result}

    assert list(by_broker) == [
        Broker.TRADING212,
        Broker.ETORO,
        Broker.BINANCE,
        Broker.BYBIT,
        Broker.INTERACTIVE_BROKERS,
        Broker.TRADING212_CRYPTO,
        Broker.XTB,
        Broker.TRADE_REPUBLIC,
        Broker.SCALABLE_CAPITAL,
    ]
    assert by_broker[Broker.ETORO].credential_fields == ["api_key", "user_key"]
    assert by_broker[Broker.ETORO].file_import is None
    assert by_broker[Broker.BYBIT].credential_fields == ["api_key", "secret_key"]
    assert by_broker[Broker.BYBIT].file_import is None
    assert by_broker[Broker.BYBIT].sync_frequency_label == "Every 1–2 hours"
    assert by_broker[Broker.INTERACTIVE_BROKERS].sync_frequency_label == "Daily"

    xtb_import = by_broker[Broker.XTB].file_import
    assert xtb_import is not None
    assert xtb_import.endpoint == "/connections/imports/xtb"
    assert xtb_import.multiple is True
    assert ".xlsx" in xtb_import.accept

    trade_republic_import = by_broker[Broker.TRADE_REPUBLIC].file_import
    assert trade_republic_import is not None
    assert trade_republic_import.endpoint == "/connections/imports/trade-republic"

    scalable_import = by_broker[Broker.SCALABLE_CAPITAL].file_import
    assert scalable_import is not None
    assert scalable_import.endpoint == "/connections/imports/scalable-capital"
