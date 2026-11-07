"""Trip request/response models and parameterized PostGIS SQL (Issue #23)."""

import math
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from backend.config.dbconfig import get_db_connection

TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})?"
)


def require_timestamp_string(value):
    if value is None:
        return None
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.fullmatch(value):
        raise ValueError("Timestamp must be an ISO 8601 date-time string.")
    return value


def normalize_timestamp(value: datetime | None) -> datetime | None:
    """Legacy PostgreSQL TIMESTAMP columns store UTC without a timezone."""
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def to_rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class TripPoint(BaseModel):
    """GeoJSON Point with [longitude, latitude] coordinates (WGS84)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["Point"]
    coordinates: list[float]

    @field_validator("coordinates", mode="before")
    @classmethod
    def validate_coordinates(cls, value):
        if not isinstance(value, list) or len(value) != 2 or not all(valid_number(x) for x in value):
            raise ValueError("coordinates must be [longitude, latitude].")
        lon, lat = value
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError("Coordinates are outside WGS84 ranges.")
        return value


class TripCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "vehicle_id": 1,
        "start_ts": "2026-03-14T08:00:00Z",
        "end_ts": "2026-03-14T08:45:00Z",
        "start_geom": {"type": "Point", "coordinates": [-67.15, 18.205]},
        "end_geom": {"type": "Point", "coordinates": [-67.141, 18.21]},
        "distance_km": 6.7,
    }})

    vehicle_id: int = Field(gt=0)
    start_ts: datetime
    end_ts: datetime
    start_geom: TripPoint | None = None
    end_geom: TripPoint | None = None
    distance_km: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("start_ts", "end_ts", mode="before")
    @classmethod
    def validate_time_string(cls, value):
        return require_timestamp_string(value)

    @field_validator("start_ts", "end_ts")
    @classmethod
    def normalize_time(cls, value):
        return normalize_timestamp(value)


class TripUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "end_ts": "2026-03-14T08:50:00Z", "distance_km": 7.1,
    }})

    vehicle_id: int | None = Field(default=None, gt=0)
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    start_geom: TripPoint | None = None
    end_geom: TripPoint | None = None
    distance_km: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("start_ts", "end_ts", mode="before")
    @classmethod
    def validate_time_string(cls, value):
        return require_timestamp_string(value)

    @field_validator("start_ts", "end_ts")
    @classmethod
    def normalize_time(cls, value):
        return normalize_timestamp(value)


class TripResponse(BaseModel):
    trip_id: int
    vehicle_id: int
    start_ts: datetime
    end_ts: datetime
    start_geom: dict[str, Any] | None = None
    end_geom: dict[str, Any] | None = None
    distance_km: float | None = None

    @field_serializer("start_ts", "end_ts")
    def serialize_time(self, value: datetime) -> str:
        return to_rfc3339(value)


class TripListItem(BaseModel):
    trip_id: int
    vehicle_id: int
    start_ts: datetime
    end_ts: datetime
    distance_km: float | None = None

    @field_serializer("start_ts", "end_ts")
    def serialize_time(self, value: datetime) -> str:
        return to_rfc3339(value)


class TripListResponse(BaseModel):
    items: list[TripListItem]
    limit: int
    offset: int
    count: int

class VehicleTripListItem(BaseModel):
    trip_id: int
    start_ts: datetime
    end_ts: datetime
    distance_km: float | None = None

    @field_serializer("start_ts", "end_ts")
    def serialize_time(self, value: datetime) -> str:
        return to_rfc3339(value)


class VehicleTripListResponse(BaseModel):
    vehicle_id: int
    items: list[VehicleTripListItem]
    limit: int
    offset: int
    count: int


class TripDeleteResponse(BaseModel):
    message: str
    trip_id: int


class TripDAO:
    """SQL-only data access using the project's shared psycopg2 pool."""

    DETAIL_COLUMNS = """
        trip_id, vehicle_id, start_ts, end_ts,
        ST_AsGeoJSON(start_geom)::json AS start_geom,
        ST_AsGeoJSON(end_geom)::json AS end_geom,
        distance_km
    """
    LIST_COLUMNS = "trip_id, vehicle_id, start_ts, end_ts, distance_km"

    @staticmethod
    def vehicle_exists(vehicle_id):
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM vehicle WHERE vehicle_id = %s", (vehicle_id,))
                return cursor.fetchone() is not None

    @staticmethod
    def _sql_value(field, value):
        """Produce SQL and bound parameters for one field."""
        if field in ("start_geom", "end_geom") and value is not None:
            coords = value["coordinates"]
            return sql.SQL("ST_SetSRID(ST_MakePoint(%s, %s), 4326)"), coords
        return sql.SQL("%s"), [value]

    def create_trip(self, data):
        fields = ["vehicle_id", "start_ts", "end_ts", "start_geom", "end_geom", "distance_km"]
        parts, params = [], []
        for field in fields:
            expr, values = self._sql_value(field, data.get(field))
            parts.append(expr)
            params.extend(values)
        query = sql.SQL("""
            INSERT INTO trip ({}) VALUES ({}) RETURNING trip_id
        """).format(
            sql.SQL(", ").join(map(sql.Identifier, fields)), sql.SQL(", ").join(parts)
        )
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchone()[0]

    def get_trip_by_id(self, trip_id):
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    f"SELECT {self.DETAIL_COLUMNS} FROM trip WHERE trip_id = %s", (trip_id,)
                )
                record = cursor.fetchone()
                return dict(record) if record else None

    @staticmethod
    def _where(vehicle_id=None, from_ts=None, to_ts=None):
        conditions, params = [], []
        if vehicle_id is not None:
            conditions.append("vehicle_id = %s")
            params.append(vehicle_id)
        if from_ts is not None:
            conditions.append("start_ts >= %s")
            params.append(from_ts)
        if to_ts is not None:
            conditions.append("start_ts <= %s")
            params.append(to_ts)
        return (" WHERE " + " AND ".join(conditions) if conditions else ""), params

    def get_trips(self, limit, offset, vehicle_id=None, from_ts=None, to_ts=None):
        where, params = self._where(vehicle_id, from_ts, to_ts)
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    f"SELECT {self.LIST_COLUMNS} FROM trip{where} "
                    "ORDER BY trip_id LIMIT %s OFFSET %s", params + [limit, offset]
                )
                items = [dict(row) for row in cursor.fetchall()]
                cursor.execute(f"SELECT COUNT(*) AS total FROM trip{where}", params)
                count = cursor.fetchone()["total"]
        return items, count

    def update_trip(self, trip_id, changes):
        allowed = {"vehicle_id", "start_ts", "end_ts", "start_geom", "end_geom", "distance_km"}
        if not changes or not set(changes).issubset(allowed):
            raise ValueError("At least one updatable field must be present.")
        assignments, params = [], []
        for field, value in changes.items():
            expression, values = self._sql_value(field, value)
            assignments.append(sql.SQL("{} = {}").format(sql.Identifier(field), expression))
            params.extend(values)
        query = sql.SQL("UPDATE trip SET {} WHERE trip_id = %s RETURNING trip_id").format(
            sql.SQL(", ").join(assignments)
        )
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params + [trip_id])
                return cursor.fetchone() is not None

    @staticmethod
    def delete_trip(trip_id):
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM trip WHERE trip_id = %s RETURNING trip_id", (trip_id,))
                return cursor.fetchone() is not None