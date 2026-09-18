import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ChatRole


class CalculationReference(BaseModel):
    id: str
    label: str
    source: str


class PortfolioContextRead(BaseModel):
    version: str
    context_hash: str
    calculated_at: datetime
    calculation_references: list[CalculationReference]


class PortfolioReviewRead(BaseModel):
    id: uuid.UUID
    content: str
    model_used: str
    context_version: str | None
    context_hash: str | None
    calculation_references: list[dict[str, Any]]
    generated_at: datetime
    cached: bool = False


class ChatMessageRead(BaseModel):
    id: uuid.UUID
    role: ChatRole
    content: str
    created_at: datetime


class ConversationRead(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessageRead] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Message cannot be empty")
        return cleaned
