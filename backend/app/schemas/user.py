import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str | None
    email_verified_at: datetime | None
    is_admin: bool


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    email: str | None = Field(default=None, max_length=320)
    initial_password: str = Field(min_length=12, max_length=256)
    is_admin: bool = False

    @field_validator("username")
    @classmethod
    def username_uses_safe_characters(cls, value: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", value):
            raise ValueError(
                "Username can only contain letters, numbers, dots, underscores, and hyphens"
            )
        return value


class ProfileRead(BaseModel):
    goals: str | None
    risk_tolerance: int | None
    time_horizon_years: int | None


class ProfileUpdate(BaseModel):
    goals: str | None = Field(default=None, max_length=4000)
    risk_tolerance: int | None = Field(default=None, ge=1, le=5)
    time_horizon_years: int | None = Field(default=None, ge=1, le=100)
