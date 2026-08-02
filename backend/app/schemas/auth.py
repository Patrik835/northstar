import re

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=256)


class RegistrationRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    password_confirmation: str = Field(min_length=12, max_length=256)

    @field_validator("username")
    @classmethod
    def username_uses_safe_characters(cls, value: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", value):
            raise ValueError(
                "Username can only contain letters, numbers, dots, underscores, and hyphens"
            )
        return value

    @model_validator(mode="after")
    def passwords_match(self) -> "RegistrationRequest":
        if self.password != self.password_confirmation:
            raise ValueError("Passwords do not match")
        return self


class EmailVerificationRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class MessageResponse(BaseModel):
    message: str
