"""Pydantic schemas and SQL data access for location pings (Issue #22)."""

import math
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from backend.config.dbconfig import get_db_connection


# RFC 3339 date-time. The offset is optional because the specification's own
# example requests omit it; timestamps without an offset are treated as UTC.
TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})?"
)


# ---------------------------------------------------------
# Timestamp and coordinate helpers
# ---------------------------------------------------------

def require_timestamp_string(value):
    """Reject non-string or non-RFC 3339 values before datetime coercion."""
    if value is None:
        return None
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.fullmatch(value):
        raise ValueError("Timestamp must be a valid RFC 3339 string.")
    return value


def normalize_timestamp(value: datetime | None) -> datetime | None:
    """Convert to the UTC-naive value stored in TIMESTAMP columns."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def to_rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def valid_longitude(value):
    return -180 <= value <= 180


def valid_latitude(value):
    return -90 <= value <= 90


# ---------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------

class PointGeometry(BaseModel):
    """GeoJSON Point in EPSG:4326 longitude/latitude order."""

    type: Literal["Point"]
    coordinates: list[float]

    @field_validator("coordinates", mode="before")
    @classmethod
    def validate_coordinates(cls, value):
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(is_number(item) for item in value)
        ):
            raise ValueError("coordinates must be [longitude, latitude].")
        lon, lat = value
        if not valid_longitude(lon) or not valid_latitude(lat):
            raise ValueError("coordinates must be valid WGS84 values.")
        return value


class LocationPingCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "vehicle_id": 1,
                "ts": "2026-03-14T09:58:20Z",
                "geom": {"type": "Point", "coordinates": [-67.1453, 18.2011]},
                "speed_kph": 42.8,
                "heading_deg": 185.4,
            }
        },
    )

    vehicle_id: int = Field(gt=0)
    ts: datetime
    geom: PointGeometry
    speed_kph: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    heading_deg: float | None = Field(default=None, ge=0, lt=360, allow_inf_nan=False)

    @field_validator("ts", mode="before")
    @classmethod
    def validate_timestamp_string(cls, value):
        return require_timestamp_string(value)

    @field_validator("ts")
    @classmethod
    def validate_timestamp(cls, value):
        return normalize_timestamp(value)


class LocationPingUpdate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"speed_kph": 45.1, "heading_deg": 190.0}
        },
    )

    vehicle_id: int | None = Field(default=None, gt=0)
    ts: datetime | None = None
    geom: PointGeometry | None = None
    speed_kph: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    heading_deg: float | None = Field(default=None, ge=0, lt=360, allow_inf_nan=False)

    @field_validator("ts", mode="before")
    @classmethod
    def validate_timestamp_string(cls, value):
        return require_timestamp_string(value)

    @field_validator("ts")
    @classmethod
    def validate_timestamp(cls, value):
        return normalize_timestamp(value)


class LocationPingResponse(BaseModel):
    ping_id: int
    vehicle_id: int
    ts: datetime
    geom: dict[str, Any]
    speed_kph: float | None = None
    heading_deg: float | None = None

    @field_serializer("ts")
    def serialize_ts(self, value: datetime) -> str:
        return to_rfc3339(value)


class LocationPingListResponse(BaseModel):
    items: list[LocationPingResponse]
    limit: int
    offset: int
    count: int


class VehiclePingItem(BaseModel):
    ping_id: int
    ts: datetime
    geom: dict[str, Any]
    speed_kph: float | None = None
    heading_deg: float | None = None

    @field_serializer("ts")
    def serialize_ts(self, value: datetime) -> str:
        return to_rfc3339(value)


class VehiclePingListResponse(BaseModel):
    vehicle_id: int
    items: list[VehiclePingItem]
    limit: int
    offset: int
    count: int


class LocationPingDeleteResponse(BaseModel):
    message: str
    ping_id: int


# ---------------------------------------------------------
# Location ping DAO
# ---------------------------------------------------------

class LocationPingDAO:
    """
    Data Access Object for location_ping records.

    Responsible for SQL operations only. Connections come from the
    shared pool; get_db_connection() commits and returns them to it.
    Geometry is written as SRID 4326 points and read back as GeoJSON.
    """

    PING_COLUMNS = """
        ping_id,
        vehicle_id,
        ts,
        ST_AsGeoJSON(geom)::json AS geom,
        speed_kph,
        heading_deg
    """

    POINT_SQL = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)"

    @staticmethod
    def _filters(vehicle_id=None, from_ts=None, to_ts=None, bbox=None):
        conditions = []
        params = []

        if vehicle_id is not None:
            conditions.append("vehicle_id = %s")
            params.append(vehicle_id)
        if from_ts is not None:
            conditions.append("ts >= %s")
            params.append(from_ts)
        if to_ts is not None:
            conditions.append("ts <= %s")
            params.append(to_ts)
        if bbox is not None:
            # ST_Intersects keeps points inside or on the edge of the box.
            conditions.append(
                "ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))"
            )
            params.extend(bbox)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        return where_clause, params

    def _get_page(self, limit, offset, order_by, **filters):
        where_clause, params = self._filters(**filters)
        query = f"""
            SELECT {self.PING_COLUMNS}
            FROM location_ping
            {where_clause}
            ORDER BY {order_by}
            LIMIT %s OFFSET %s
        """
        count_query = f"""
            SELECT COUNT(*) AS total
            FROM location_ping
            {where_clause}
        """
        # Get connection from pool
        with get_db_connection() as conn:
            # now get the cursor
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params + [limit, offset])
            result = [dict(row) for row in cursor]
            # count is the number of matches before pagination
            cursor.execute(count_query, params)
            count = cursor.fetchone()["total"]
            # Always close cursor
            cursor.close()
        return result, count

    def vehicle_exists(self, vehicle_id) -> bool:
        # Get connection from pool
        with get_db_connection() as conn:
            # now get the cursor
            cursor = conn.cursor()
            query = "SELECT 1 FROM vehicle WHERE vehicle_id = %s"
            cursor.execute(query, (vehicle_id,))
            exists = cursor.fetchone() is not None
            # Always close cursor
            cursor.close()
        return exists

    def get_all_pings(
        self, limit, offset, vehicle_id=None, from_ts=None, to_ts=None, bbox=None,
    ):
        return self._get_page(
            limit, offset, "ping_id",
            vehicle_id=vehicle_id, from_ts=from_ts, to_ts=to_ts, bbox=bbox,
        )

    def get_pings_by_vehicle(self, vehicle_id, limit, offset, from_ts=None, to_ts=None):
        # Vehicle history reads as a timeline: oldest ping first.
        return self._get_page(
            limit, offset, "ts, ping_id",
            vehicle_id=vehicle_id, from_ts=from_ts, to_ts=to_ts,
        )

    def get_ping_by_id(self, ping_id) -> dict | None:
        # Get connection from pool
        with get_db_connection() as conn:
            # now get the cursor
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            query = f"""
                SELECT {self.PING_COLUMNS}
                FROM location_ping
                WHERE ping_id = %s
            """
            cursor.execute(query, (ping_id,))
            row = cursor.fetchone()
            result = dict(row) if row else None
            # Always close cursor
            cursor.close()
        return result

    def create_ping(self, new_ping) -> int:
        lon, lat = new_ping["geom"]
        # Get connection from pool
        with get_db_connection() as conn:
            # now get the cursor
            cursor = conn.cursor()
            query = f"""
                INSERT INTO location_ping (
                    vehicle_id, ts, geom, speed_kph, heading_deg
                ) VALUES (
                    %s, %s, {self.POINT_SQL}, %s, %s
                )
                RETURNING ping_id
            """
            cursor.execute(query, (
                new_ping["vehicle_id"], new_ping["ts"], lon, lat,
                new_ping.get("speed_kph"), new_ping.get("heading_deg"),
            ))
            ping_id = cursor.fetchone()[0]
            # Always close cursor
            cursor.close()
        # Leaving the block commits the change to the DB
        return ping_id

    def update_ping(self, ping_id, changes) -> bool:
        allowed = {"vehicle_id", "ts", "geom", "speed_kph", "heading_deg"}
        if not changes or not set(changes).issubset(allowed):
            raise ValueError("At least one valid updatable field is required")

        # Only the supplied fields are updated (partial or full update).
        assignments = []
        values = []
        for field, value in changes.items():
            if field == "geom":
                assignments.append(sql.SQL("geom = " + self.POINT_SQL))
                values.extend(value)
            else:
                assignments.append(sql.SQL("{} = %s").format(sql.Identifier(field)))
                values.append(value)

        query = sql.SQL("""
            UPDATE location_ping
            SET {}
            WHERE ping_id = %s
        """).format(sql.SQL(", ").join(assignments))

        # Get connection from pool
        with get_db_connection() as conn:
            # now get the cursor
            cursor = conn.cursor()
            cursor.execute(query, values + [ping_id])
            rows = cursor.rowcount
            # Always close cursor
            cursor.close()
        return rows == 1

    def delete_ping(self, ping_id) -> bool:
        # Get connection from pool
        with get_db_connection() as conn:
            # now get the cursor
            cursor = conn.cursor()
            query = """
                DELETE FROM location_ping
                WHERE ping_id = %s
            """
            cursor.execute(query, (ping_id,))
            rows = cursor.rowcount
            # Always close cursor
            cursor.close()
        return rows == 1
