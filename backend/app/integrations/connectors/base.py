from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.models.enums import AssetType, TransactionType


class ConnectorError(RuntimeError):
    """A safe, user-facing broker integration error."""


class InvalidBrokerCredentials(ConnectorError):
    """The broker rejected the supplied credentials."""


class BrokerPermissionError(ConnectorError):
    """The credentials are valid but lack a required read permission."""


class BrokerUnavailableError(ConnectorError):
    """The broker could not be reached or temporarily rejected the request."""


class BrokerRateLimitError(BrokerUnavailableError):
    """The provider asked the client to stop until its quota resets."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ConnectorPosition:
    instrument_id: str
    ticker: str
    name: str | None
    asset_type: AssetType
    quantity: Decimal
    average_price: Decimal | None
    current_value: Decimal
    currency: str
    canonical_symbol: str | None = None
    isin: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectorTransaction:
    external_id: str
    ticker: str
    transaction_type: TransactionType
    quantity: Decimal | None
    price: Decimal | None
    value: Decimal
    currency: str
    executed_at: datetime


@dataclass(frozen=True, slots=True)
class ConnectorSnapshot:
    snapshot_date: date
    total_value: Decimal
    currency: str


class BrokerConnector(ABC):
    """Common server-side contract for every broker and exchange."""

    def __init__(self, credentials: dict[str, str]) -> None:
        self.credentials = credentials

    @abstractmethod
    async def validate_credentials(self) -> None:
        """Raise a safe integration error when credentials are invalid."""

    @abstractmethod
    async def fetch_positions(self) -> list[ConnectorPosition]:
        """Return current holdings normalized into the common data model."""

    @abstractmethod
    async def fetch_transactions(self, since: datetime | None) -> list[ConnectorTransaction]:
        """Return normalized activity since the requested cursor."""

    async def fetch_snapshot(self, snapshot_date: date) -> ConnectorSnapshot:
        raise NotImplementedError("This connector does not provide dated snapshots")
