from datetime import datetime, timezone
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    field_serializer,
)


class VehicleCreate(BaseModel):
    vehicle_type_id: int = Field(gt=0)
    vehicle_status_id: int = Field(gt=0)
    plate_number: str = Field(min_length=1)
    make: str | None = None
    model: str | None = None
    year: int | None = Field(default=None, ge=1950, le=2100)

    @field_validator("plate_number", "make", "model")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Text must not be empty.")
        return value


class VehicleUpdate(BaseModel):
    vehicle_type_id: int | None = Field(default=None, gt=0)
    vehicle_status_id: int | None = Field(default=None, gt=0)
    plate_number: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = Field(default=None, ge=1950, le=2100)

    @field_validator("plate_number", "make", "model")
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Text must not be empty.")
        return value


class VehicleResponse(BaseModel):
    vehicle_id: int
    vehicle_type_id: int
    vehicle_status_id: int
    plate_number: str
    make: str | None = None
    model: str | None = None
    year: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class VehicleListResponse(BaseModel):
    items: list[VehicleResponse]
    limit: int
    offset: int
    count: int

class VehicleDeleteResponse(BaseModel):
    message: str
    vehicle_id: int


class VehicleCurrentLocationResponse(BaseModel):
    vehicle_id: int
    plate_number: str
    status: str | None = None
    vehicle_kind: str | None = None
    fuel_type: str | None = None
    emissions_rating: float | None = None
    last_ts: datetime
    last_geom: dict[str, Any]
    speed_kph: float | None = None
    heading_deg: float | None = None

    @field_serializer("last_ts")
    def serialize_last_ts(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
