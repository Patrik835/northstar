import pytest

from app.integrations.connectors.binance import BinanceConnector
from app.integrations.connectors.registry import ConnectorRegistry
from app.models.enums import Broker


def test_registry_resolves_connector_without_core_changes() -> None:
    connector = ConnectorRegistry().create(
        Broker.BINANCE, {"api_key": "key", "secret_key": "secret"}
    )
    assert isinstance(connector, BinanceConnector)


def test_manual_source_has_no_live_connector() -> None:
    with pytest.raises(ValueError, match="No connector registered"):
        ConnectorRegistry().create(Broker.XTB_MANUAL, {})
