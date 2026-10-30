from datetime import datetime, timezone
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
)


# Automatically trims whitespace and rejects empty strings.
NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1)
]


def validate_timestamp(value):
    """
    Require an RFC 3339 timestamp with timezone information.

    Convert the timestamp to UTC and remove timezone information
    because the PostgreSQL column uses TIMESTAMP WITHOUT TIME ZONE.
    """
    if not isinstance(value, str):
        raise ValueError(
            "hired_at must be an RFC 3339 timestamp string"
        )

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(
            "hired_at must be a valid RFC 3339 timestamp"
        )

    if (
        "T" not in value
        or parsed.tzinfo is None
        or parsed.utcoffset() is None
    ):
        raise ValueError(
            "hired_at must include a timezone offset"
        )

    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


class DriverCreate(BaseModel):
    """Request body for creating a driver."""

    model_config = ConfigDict(extra="forbid")

    first_name: NonEmptyText
    last_name: NonEmptyText
    license_number: NonEmptyText
    hired_at: datetime

    @field_validator("hired_at", mode="before")
    @classmethod
    def validate_hired_at(cls, value):
        return validate_timestamp(value)


class DriverUpdate(BaseModel):
    """Request body for partially or fully updating a driver."""

    model_config = ConfigDict(extra="forbid")

    first_name: NonEmptyText | None = None
    last_name: NonEmptyText | None = None
    license_number: NonEmptyText | None = None
    hired_at: datetime | None = None

    @field_validator(
        "first_name",
        "last_name",
        "license_number",
        mode="before",
    )
    @classmethod
    def reject_null_text(cls, value):
        if value is None:
            raise ValueError("Updated fields cannot be null")
        return value

    @field_validator("hired_at", mode="before")
    @classmethod
    def validate_hired_at(cls, value):
        if value is None:
            raise ValueError("Updated fields cannot be null")
        return validate_timestamp(value)


class DriverResponse(BaseModel):
    """Response body for one driver."""

    driver_id: int
    first_name: str
    last_name: str
    license_number: str
    hired_at: datetime

    @field_validator("hired_at", mode="before")
    @classmethod
    def attach_utc_timezone(cls, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class DriverListResponse(BaseModel):
    """Response body for paginated driver retrieval."""

    items: list[DriverResponse]
    limit: int
    offset: int
    count: int


class DriverDeleteResponse(BaseModel):
    """Response body after deleting a driver."""

    message: str
    driver_id: int