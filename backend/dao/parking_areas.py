"""Pydantic schemas and SQL access for parking areas (Issue #21)."""

import json
import math
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from backend.config.dbconfig import get_db_connection


class PolygonGeometry(BaseModel):
    type: Literal["Polygon"]
    coordinates: list[list[list[float]]]
    model_config = ConfigDict(extra="forbid")

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, rings):
        if not rings:
            raise ValueError("Polygon must contain at least one ring.")
        for ring in rings:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Polygon rings must be closed and contain at least four positions.")
            for point in ring:
                if len(point) != 2:
                    raise ValueError("Coordinates must contain longitude and latitude.")
                lon, lat = point
                if not (math.isfinite(lon) and math.isfinite(lat)):
                    raise ValueError("Coordinates must be finite.")
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    raise ValueError("Coordinates must be within WGS84 ranges.")
        return rings


class ParkingAreaCreate(BaseModel):
    name: str
    capacity: int | None = Field(default=None, ge=0)
    geom: PolygonGeometry
    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, name):
        if not name.strip():
            raise ValueError("name must be non-empty.")
        return name.strip()


class ParkingAreaUpdate(BaseModel):
    name: str | None = None
    capacity: int | None = Field(default=None, ge=0)
    geom: PolygonGeometry | None = None
    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, name):
        if name is not None and not name.strip():
            raise ValueError("name must be non-empty.")
        return name.strip() if name is not None else None


class ParkingAreaListItem(BaseModel):
    parking_area_id: int
    name: str
    capacity: int | None = None
    created_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime | None):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class ParkingAreaResponse(ParkingAreaListItem):
    geom: dict[str, Any]


class ParkingAreaListResponse(BaseModel):
    items: list[ParkingAreaListItem]
    limit: int
    offset: int
    count: int


class ParkingAreaDeleteResponse(BaseModel):
    message: str
    parking_area_id: int


class ParkingAreaDAO:
    """SQL-only data access using the existing psycopg2 connection pool."""

    DETAIL_COLUMNS = """parking_area_id, name, capacity,
        ST_AsGeoJSON(geom)::json AS geom, created_at"""
    LIST_COLUMNS = "parking_area_id, name, capacity, created_at"

    def is_valid_polygon(self, geometry: dict[str, Any]) -> bool:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT ST_IsValid(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))""",
                    (json.dumps(geometry),),
                )
                return bool(cursor.fetchone()[0])

    def create_parking_area(self, data: dict):
        query = f"""
            INSERT INTO public.parking_area (name, capacity, geom)
            VALUES (%s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
            RETURNING {self.DETAIL_COLUMNS}
        """
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (
                    data["name"], data.get("capacity"), json.dumps(data["geom"]),
                ))
                return dict(cursor.fetchone())

    def get_parking_area_by_id(self, parking_area_id: int):
        query = f"""SELECT {self.DETAIL_COLUMNS}
            FROM public.parking_area WHERE parking_area_id = %s"""
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (parking_area_id,))
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_parking_areas(self, limit: int, offset: int, name=None, bbox=None):
        clauses = []
        params = []
        if name is not None:
            clauses.append("name ILIKE %s")
            params.append(f"%{name}%")
        if bbox is not None:
            clauses.append("ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))")
            params.extend(bbox)
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        query = f"""SELECT {self.LIST_COLUMNS} FROM public.parking_area
            {where_sql} ORDER BY parking_area_id LIMIT %s OFFSET %s"""
        count_query = f"SELECT COUNT(*) AS total FROM public.parking_area {where_sql}"
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params + [limit, offset])
                rows = [dict(row) for row in cursor.fetchall()]
                cursor.execute(count_query, params)
                total = cursor.fetchone()["total"]
                return rows, total

    def update_parking_area(self, parking_area_id: int, changes: dict):
        expressions = []
        values = []
        for field, value in changes.items():
            if field == "geom":
                expressions.append(sql.SQL("geom = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)"))
                values.append(json.dumps(value))
            elif field in {"name", "capacity"}:
                expressions.append(sql.SQL("{} = %s").format(sql.Identifier(field)))
                values.append(value)
        if not expressions:
            return None
        query = sql.SQL("UPDATE public.parking_area SET {} WHERE parking_area_id = %s RETURNING ").format(
            sql.SQL(", ").join(expressions)
        ) + sql.SQL(self.DETAIL_COLUMNS)
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, values + [parking_area_id])
                row = cursor.fetchone()
                return dict(row) if row else None

    def delete_parking_area(self, parking_area_id: int):
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM public.parking_area WHERE parking_area_id = %s RETURNING parking_area_id",
                    (parking_area_id,),
                )
                return cursor.fetchone() is not None