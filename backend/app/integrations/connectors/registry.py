from collections.abc import Callable

from app.integrations.connectors.base import BrokerConnector
from app.integrations.connectors.binance import BinanceConnector
from app.integrations.connectors.etoro import EtoroConnector
from app.integrations.connectors.trading212 import Trading212Connector
from app.models.enums import Broker

ConnectorFactory = Callable[[dict[str, str]], BrokerConnector]


class ConnectorRegistry:
    def __init__(self) -> None:
        self._factories: dict[Broker, ConnectorFactory] = {
            Broker.TRADING212: Trading212Connector,
            Broker.ETORO: EtoroConnector,
            Broker.BINANCE: BinanceConnector,
        }

    def create(self, broker: Broker, credentials: dict[str, str]) -> BrokerConnector:
        try:
            return self._factories[broker](credentials)
        except KeyError as exc:
            raise ValueError(f"No connector registered for {broker.value}") from exc

