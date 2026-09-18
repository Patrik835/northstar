from dataclasses import replace

import pytest

from app.integrations.connectors.binance import BinanceConnector
from app.integrations.connectors.bybit import BybitConnector
from app.integrations.connectors.registry import ConnectorRegistry
from app.models.enums import Broker


def test_registry_resolves_connector_without_core_changes() -> None:
    connector = ConnectorRegistry().create(
        Broker.BINANCE, {"api_key": "key", "secret_key": "secret"}
    )
    assert isinstance(connector, BinanceConnector)


def test_registry_is_the_single_live_connector_catalog() -> None:
    registry = ConnectorRegistry()

    assert registry.brokers() == (
        Broker.TRADING212,
        Broker.ETORO,
        Broker.BINANCE,
        Broker.BYBIT,
        Broker.INTERACTIVE_BROKERS,
    )
    assert registry.definition(Broker.ETORO).credential_fields == (
        "api_key",
        "user_key",
    )
    assert registry.definition(Broker.BINANCE).valuation_source == "market"
    assert registry.definition(Broker.BINANCE).initial_activity_cursor == ("binance-activity-v1")
    assert registry.definition(Broker.BYBIT).credential_fields == (
        "api_key",
        "secret_key",
    )
    assert registry.brokers_for_schedule("daily") == (Broker.INTERACTIVE_BROKERS,)
    assert registry.definition(Broker.INTERACTIVE_BROKERS).stale_after_hours == 48


def test_registry_creates_bybit_eu_connector() -> None:
    connector = ConnectorRegistry().create(
        Broker.BYBIT, {"api_key": "key", "secret_key": "secret"}
    )

    assert isinstance(connector, BybitConnector)
    assert connector.base_url == "https://api.bybit.eu"


def test_new_live_provider_can_be_registered_without_sync_or_api_changes() -> None:
    binance = ConnectorRegistry().definition(Broker.BINANCE)
    registry = ConnectorRegistry([replace(binance, broker=Broker.XTB, display_name="Test XTB")])

    assert registry.supports(Broker.XTB)
    assert registry.brokers() == (Broker.XTB,)
    assert isinstance(
        registry.create(Broker.XTB, {"api_key": "key", "secret_key": "secret"}),
        BinanceConnector,
    )


def test_registry_rejects_duplicate_provider_definitions() -> None:
    definition = ConnectorRegistry().definition(Broker.BINANCE)

    with pytest.raises(ValueError, match="only have one"):
        ConnectorRegistry([definition, definition])


def test_manual_stock_source_is_not_part_of_the_broker_domain() -> None:
    with pytest.raises(ValueError, match="not a valid Broker"):
        Broker("xtb_manual")
