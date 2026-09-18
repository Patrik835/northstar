from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from app.integrations.connectors.base import BrokerConnector
from app.integrations.connectors.binance import BinanceConnector
from app.integrations.connectors.etoro import EtoroConnector
from app.integrations.connectors.interactive_brokers import InteractiveBrokersConnector
from app.integrations.connectors.trading212 import Trading212Connector
from app.models.enums import Broker

ConnectorFactory = Callable[[dict[str, str]], BrokerConnector]


@dataclass(frozen=True, slots=True)
class CredentialField:
    key: str
    label: str


@dataclass(frozen=True, slots=True)
class ConnectorDefinition:
    """Everything the core application needs to host one live connector."""

    broker: Broker
    display_name: str
    short_mark: str
    factory: ConnectorFactory
    credentials: tuple[CredentialField, ...]
    category: str
    description: str
    security_notice: str
    setup_steps: tuple[str, ...]
    tutorial_url: str
    valuation_source: Literal["provider", "market"] = "provider"
    initial_activity_cursor: str | None = None
    schedule: Literal["intraday", "daily"] = "intraday"
    stale_after_hours: int = 24

    def __post_init__(self) -> None:
        keys = self.credential_fields
        if not keys or len(keys) != len(set(keys)):
            raise ValueError("Live connectors require unique credential fields")
        if self.stale_after_hours <= 0:
            raise ValueError("Live connector freshness must be positive")

    @property
    def credential_fields(self) -> tuple[str, ...]:
        return tuple(field.key for field in self.credentials)

    @property
    def credential_labels(self) -> dict[str, str]:
        return {field.key: field.label for field in self.credentials}

    @property
    def sync_frequency_label(self) -> str:
        return "Daily" if self.schedule == "daily" else "Every 1–2 hours"


DEFAULT_CONNECTORS = (
    ConnectorDefinition(
        broker=Broker.TRADING212,
        display_name="Trading 212",
        short_mark="T2",
        factory=Trading212Connector,
        credentials=(
            CredentialField("api_key", "API key"),
            CredentialField("api_secret", "API secret"),
        ),
        category="Broker",
        description="Automatically synchronize stocks, ETFs, cash, and recent activity.",
        security_notice=(
            "Use a read-only key with Account, Portfolio, and History access. "
            "Never enable trading permissions."
        ),
        setup_steps=(
            "Open Trading 212 Settings → API (Beta) → Generate API key.",
            "Enable Account data, Portfolio, and all three History permissions.",
            "Keep every order and trading permission disabled.",
            "Copy the API Key and API Secret; the secret is shown once.",
        ),
        tutorial_url=(
            "https://helpcentre.trading212.com/hc/en-us/articles/14584770928157-Trading-212-API-key"
        ),
    ),
    ConnectorDefinition(
        broker=Broker.ETORO,
        display_name="eToro",
        short_mark="eT",
        factory=EtoroConnector,
        credentials=(
            CredentialField("api_key", "Public key"),
            CredentialField("user_key", "Private key"),
        ),
        category="Broker",
        description="Automatically synchronize investments, cash, and Copy Portfolios.",
        security_notice=(
            "Use a Real-environment key with Read permission only. "
            "Enter eToro's Public Key and Private Key."
        ),
        setup_steps=(
            "Open eToro Settings → Trading → API Key Management.",
            "Create a Real-environment key with Read permission only.",
            "Complete verification, then copy the Public Key and Private Key.",
        ),
        tutorial_url="https://api-portal.etoro.com/getting-started/authentication",
        initial_activity_cursor="etoro-activity-v2",
    ),
    ConnectorDefinition(
        broker=Broker.BINANCE,
        display_name="Binance",
        short_mark="BN",
        factory=BinanceConnector,
        credentials=(
            CredentialField("api_key", "API key"),
            CredentialField("secret_key", "Secret key"),
        ),
        category="Crypto exchange",
        description=(
            "Automatically synchronize Spot balances, trades, transfers, fees, and distributions."
        ),
        security_notice=("Enable Reading only. Keep trading, Futures, and Withdrawals disabled."),
        setup_steps=(
            "Open Binance Profile → API Management and create an HMAC key.",
            "Enable Reading only; leave trading and withdrawals disabled.",
            "Copy the API Key and Secret Key; the secret may be shown once.",
        ),
        tutorial_url=(
            "https://www.binance.com/en/academy/articles/what-are-api-keys-and-security-types"
        ),
        valuation_source="market",
        initial_activity_cursor="binance-activity-v1",
    ),
    ConnectorDefinition(
        broker=Broker.INTERACTIVE_BROKERS,
        display_name="Interactive Brokers",
        short_mark="IB",
        factory=InteractiveBrokersConnector,
        credentials=(
            CredentialField("flex_token", "Flex Web Service token"),
            CredentialField("query_id", "Activity Flex Query ID"),
        ),
        category="Broker",
        description=(
            "Synchronize positions, cash, P/L, trades, dividends, and cash movements daily."
        ),
        security_notice=(
            "Uses IBKR's reporting-only Flex Web Service. Your IBKR password is never requested."
        ),
        setup_steps=(
            "In Client Portal, open Performance & Reports → Flex Queries.",
            "Enable Flex Web Service and copy its token.",
            "Create an XML Activity Flex Query with Open Positions, Cash Report, "
            "Change in NAV, Trades (Executions), and Cash Transactions.",
            "Choose a useful history period, save it, and copy its Query ID.",
        ),
        tutorial_url="https://ibkrcampus.com/campus/ibkr-api-page/flex-web-service/",
        initial_activity_cursor="ibkr-flex-activity-v1",
        schedule="daily",
        stale_after_hours=48,
    ),
)


class ConnectorRegistry:
    def __init__(self, definitions: Iterable[ConnectorDefinition] = DEFAULT_CONNECTORS) -> None:
        definitions = tuple(definitions)
        self._definitions = {definition.broker: definition for definition in definitions}
        if len(self._definitions) != len(definitions):
            raise ValueError("A broker can only have one live connector definition")

    def definitions(self) -> tuple[ConnectorDefinition, ...]:
        return tuple(self._definitions.values())

    def brokers(self) -> tuple[Broker, ...]:
        return tuple(self._definitions)

    def brokers_for_schedule(self, schedule: Literal["intraday", "daily"]) -> tuple[Broker, ...]:
        return tuple(
            definition.broker
            for definition in self._definitions.values()
            if definition.schedule == schedule
        )

    def supports(self, broker: Broker) -> bool:
        return broker in self._definitions

    def definition(self, broker: Broker) -> ConnectorDefinition:
        try:
            return self._definitions[broker]
        except KeyError as exc:
            raise ValueError(f"No live connector registered for {broker.value}") from exc

    def create(self, broker: Broker, credentials: dict[str, str]) -> BrokerConnector:
        return self.definition(broker).factory(credentials)
