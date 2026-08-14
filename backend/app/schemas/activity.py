import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import Broker, TransactionType


class ActivityItem(BaseModel):
    id: uuid.UUID
    broker: Broker
    connection_id: uuid.UUID
    holding_key: str | None
    symbol: str
    name: str | None
    transaction_type: TransactionType
    quantity: Decimal | None
    price: Decimal | None
    value: Decimal
    value_eur: Decimal | None
    is_estimated_fx: bool
    currency: str
    executed_at: datetime


class ActivityCurrencyTotal(BaseModel):
    currency: str
    value: Decimal
    event_count: int


class ActivityTotal(BaseModel):
    value_eur: Decimal
    event_count: int
    missing_eur_count: int
    estimated_eur_count: int
    native_values: list[ActivityCurrencyTotal]


class ActivitySummary(BaseModel):
    bought: ActivityTotal
    sold: ActivityTotal
    dividends: ActivityTotal
    deposited: ActivityTotal


class ActivityResponse(BaseModel):
    items: list[ActivityItem]
    total: int
    offset: int
    limit: int
    brokers: list[Broker]
    transaction_types: list[TransactionType]
    summary: ActivitySummary
