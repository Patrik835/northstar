import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Broker, ConnectionStatus


class ConnectionCreate(BaseModel):
    broker: Broker
    credentials: dict[str, str] = Field(min_length=1)


class ConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    broker: Broker
    credential_hint: str
    status: ConnectionStatus
    last_error: str | None
    last_synced_at: datetime | None


class ConnectionGuide(BaseModel):
    broker: Broker
    credential_fields: list[str]
    security_notice: str
    setup_steps: list[str]
    tutorial_url: str
