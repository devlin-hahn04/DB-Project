"""SQL data access and Pydantic schemas for vehicle assignments (Issue #20)."""

import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from backend.config.dbconfig import get_db_connection


RFC3339_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})"
)


def require_rfc3339_string(value):
    """Reject non-RFC3339 strings before Pydantic's datetime coercion."""
    if value is None:
        return None  # The model/handler rejects null when the field is required.
    if not isinstance(value, str) or not RFC3339_PATTERN.fullmatch(value):
        raise ValueError("Timestamp must be a valid RFC 3339 string.")
    return value


def normalize_timestamp(value: datetime | None) -> datetime | None:
    """Normalize timezone-aware timestamps to UTC-naive legacy TIMESTAMP columns."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A valid RFC 3339 timestamp must include a timezone offset.")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class AssignmentCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "vehicle_id": 1,
                "driver_id": 1,
                "assigned_from": "2026-11-05T12:00:00Z",
                "assigned_to": "2026-11-05T18:00:00Z",
            }
        },
    )

    vehicle_id: int = Field(gt=0)
    driver_id: int = Field(gt=0)
    assigned_from: datetime
    assigned_to: datetime | None = None

    @field_validator("assigned_from", "assigned_to", mode="before")
    @classmethod
    def validate_rfc3339_string(cls, value):
        return require_rfc3339_string(value)

    @field_validator("assigned_from", "assigned_to")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return normalize_timestamp(value)


class AssignmentUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "assigned_to": "2026-11-05T18:00:00Z"
            }
        },
    )

    vehicle_id: int | None = Field(default=None, gt=0)
    driver_id: int | None = Field(default=None, gt=0)
    assigned_from: datetime | None = None
    assigned_to: datetime | None = None

    @field_validator("assigned_from", "assigned_to", mode="before")
    @classmethod
    def validate_rfc3339_string(cls, value):
        return require_rfc3339_string(value)

    @field_validator("assigned_from", "assigned_to")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return normalize_timestamp(value)


class AssignmentResponse(BaseModel):
    assignment_id: int
    vehicle_id: int
    driver_id: int
    assigned_from: datetime
    assigned_to: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("assigned_from", "assigned_to")
    def serialize_time(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class AssignmentListResponse(BaseModel):
    items: list[AssignmentResponse]
    limit: int
    offset: int
    count: int


class AssignmentDeleteResponse(BaseModel):
    message: str
    assignment_id: int


class VehicleAssignmentDAO:
    """Execute parameterized SQL through the shared connection pool."""

    ASSIGNMENT_COLUMNS = """
        assignment_id, vehicle_id, driver_id, assigned_from, assigned_to
    """

    def vehicle_exists(self, vehicle_id):
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM vehicle WHERE vehicle_id = %s", (vehicle_id,))
                return cursor.fetchone() is not None

    def driver_exists(self, driver_id):
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM driver WHERE driver_id = %s", (driver_id,))
                return cursor.fetchone() is not None

    def create_assignment(self, data):
        query = f"""
            INSERT INTO vehicle_assignment (
                vehicle_id, driver_id, assigned_from, assigned_to
            ) VALUES (
                %(vehicle_id)s, %(driver_id)s, %(assigned_from)s, %(assigned_to)s
            ) RETURNING {self.ASSIGNMENT_COLUMNS}
        """
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, data)
                return dict(cursor.fetchone())

    def get_assignment_by_id(self, assignment_id):
        query = f"""
            SELECT {self.ASSIGNMENT_COLUMNS}
            FROM vehicle_assignment
            WHERE assignment_id = %s
        """
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (assignment_id,))
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_assignments(self, limit, offset, vehicle_id=None, driver_id=None, active=None):
        conditions = []
        params = []

        if vehicle_id is not None:
            conditions.append("vehicle_id = %s")
            params.append(vehicle_id)
        if driver_id is not None:
            conditions.append("driver_id = %s")
            params.append(driver_id)
        if active is not None:
            conditions.append("assigned_to IS NULL" if active else "assigned_to IS NOT NULL")

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"""
            SELECT {self.ASSIGNMENT_COLUMNS}
            FROM vehicle_assignment
            {where_clause}
            ORDER BY assignment_id
            LIMIT %s OFFSET %s
        """
        count_query = f"""
            SELECT COUNT(*) AS total
            FROM vehicle_assignment
            {where_clause}
        """
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params + [limit, offset])
                items = [dict(row) for row in cursor.fetchall()]
                cursor.execute(count_query, params)
                count = cursor.fetchone()["total"]
        return items, count

    def update_assignment(self, assignment_id, data):
        allowed = {"vehicle_id", "driver_id", "assigned_from", "assigned_to"}
        if not data or not set(data).issubset(allowed):
            raise ValueError("At least one valid updatable field is required")

        assignments = [
            sql.SQL("{} = %s").format(sql.Identifier(field)) for field in data
        ]
        query = sql.SQL("""
            UPDATE vehicle_assignment
            SET {}
            WHERE assignment_id = %s
            RETURNING assignment_id, vehicle_id, driver_id,
                      assigned_from, assigned_to
        """).format(sql.SQL(", ").join(assignments))
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, list(data.values()) + [assignment_id])
                row = cursor.fetchone()
                return dict(row) if row else None

    def delete_assignment(self, assignment_id):
        query = """
            DELETE FROM vehicle_assignment
            WHERE assignment_id = %s
            RETURNING assignment_id
        """
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, (assignment_id,))
                return cursor.fetchone() is not None
