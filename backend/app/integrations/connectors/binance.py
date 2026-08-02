from datetime import datetime

from app.integrations.connectors.base import (
    BrokerConnector,
    ConnectorPosition,
    ConnectorTransaction,
)


class BinanceConnector(BrokerConnector):
    """Read-only Binance Spot adapter. Never implements order/trading endpoints."""

    base_url = "https://api.binance.com"

    async def validate_credentials(self) -> None:
        raise NotImplementedError

    async def fetch_positions(self) -> list[ConnectorPosition]:
        raise NotImplementedError

    async def fetch_transactions(self, since: datetime | None) -> list[ConnectorTransaction]:
        raise NotImplementedError

