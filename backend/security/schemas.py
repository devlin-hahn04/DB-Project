
"""Pydantic request and response models for authentication."""

from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)


def normalize_email(value: str) -> str:
    """Normalize an email before Pydantic validates it."""
    if not isinstance(value, str):
        raise ValueError("Email must be a string.")

    return value.strip().lower()


class RegisterRequest(BaseModel):
    """Request body for account registration."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=254)

    password: str = Field(
        min_length=12,
        max_length=1024,
    )

    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, value: str) -> str:
        """Normalize email before EmailStr validation."""
        return normalize_email(value)


class LoginRequest(BaseModel):
    """Request body for user login."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=254)

    password: str = Field(
        min_length=1,
        max_length=1024,
    )

    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, value: str) -> str:
        """Normalize email before EmailStr validation."""
        return normalize_email(value)


class UserResponse(BaseModel):
    """Public user representation."""

    user_id: int
    email: str
    created_at: datetime
    is_active: bool


class TokenResponse(BaseModel):
    """Successful login response."""

    access_token: str
    token_type: str
    expires_in: int
