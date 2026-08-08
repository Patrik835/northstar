from enum import Enum


class StrEnum(str, Enum):
    """Python 3.10-compatible string enum."""

    def __str__(self) -> str:
        return self.value


class Broker(StrEnum):
    TRADING212 = "trading212"
    TRADING212_CRYPTO = "trading212_crypto"
    ETORO = "etoro"
    BINANCE = "binance"
    XTB = "xtb"


class ConnectionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    LIMITED = "limited"
    ERROR = "error"
    DISABLED = "disabled"


class SyncRunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    ERROR = "error"


class SyncTrigger(StrEnum):
    INITIAL = "initial"
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class AssetType(StrEnum):
    STOCK = "stock"
    ETF = "etf"
    CRYPTO = "crypto"
    CASH = "cash"
    OTHER = "other"


class TransactionType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    FEE = "fee"
    OTHER = "other"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
