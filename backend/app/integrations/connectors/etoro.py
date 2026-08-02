from datetime import date, datetime

from app.integrations.connectors.base import (
    BrokerConnector,
    ConnectorPosition,
    ConnectorSnapshot,
    ConnectorTransaction,
)


class EtoroConnector(BrokerConnector):
    """Monthly eToro portfolio snapshot adapter."""

    base_url = "https://api.etoro.com"

    async def validate_credentials(self) -> None:
        raise NotImplementedError

    async def fetch_positions(self) -> list[ConnectorPosition]:
        return []

    async def fetch_transactions(self, since: datetime | None) -> list[ConnectorTransaction]:
        return []

    async def fetch_snapshot(self, snapshot_date: date) -> ConnectorSnapshot:
        raise NotImplementedError

