"""Pydantic schemas and SQL data access for road segments (Issue #30)."""

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from backend.config.dbconfig import get_db_connection
from backend.dao.location_pings import (
    is_number,
    to_rfc3339,
    valid_latitude,
    valid_longitude,
)


# ---------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------

def validate_name_text(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("name must be a non-empty string.")
    return value.strip()


class LineStringGeometry(BaseModel):
    """GeoJSON LineString in EPSG:4326 longitude/latitude order."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["LineString"]
    coordinates: list[list[float]]

    @field_validator("coordinates", mode="before")
    @classmethod
    def validate_coordinates(cls, value):
        if not isinstance(value, list) or len(value) < 2:
            raise ValueError("A LineString needs at least two positions.")
        for position in value:
            if (
                not isinstance(position, list)
                or len(position) != 2
                or not all(is_number(item) for item in position)
            ):
                raise ValueError("Each position must be [longitude, latitude].")
            lon, lat = position
            if not valid_longitude(lon) or not valid_latitude(lat):
                raise ValueError("coordinates must be valid WGS84 values.")
        if len({tuple(position) for position in value}) < 2:
            raise ValueError("A LineString needs at least two distinct positions.")
        return value


class RoadSegmentCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "name": "PR-2 Segment A",
                "speed_limit_kph": 60,
                "is_oneway": True,
                "direction": "forward",
                "geom": {
                    "type": "LineString",
                    "coordinates": [[-67.1601, 18.211], [-67.1588, 18.2101], [-67.1573, 18.2092]],
                },
            }
        },
    )

    name: str
    speed_limit_kph: int | None = Field(default=None, ge=0)
    is_oneway: bool | None = None
    direction: Literal["both", "forward"] | None = None
    geom: LineStringGeometry

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value):
        return validate_name_text(value)


class RoadSegmentUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"speed_limit_kph": 80}},
    )

    name: str | None = None
    speed_limit_kph: int | None = Field(default=None, ge=0)
    is_oneway: bool | None = None
    direction: Literal["both", "forward"] | None = None
    geom: LineStringGeometry | None = None

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value):
        return validate_name_text(value)


class RoadSegmentListItem(BaseModel):
    road_id: int
    name: str
    speed_limit_kph: int | None = None
    is_oneway: bool | None = None
    direction: str | None = None
    created_at: datetime | None = None

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime | None) -> str | None:
        return to_rfc3339(value) if value is not None else None


class RoadSegmentResponse(RoadSegmentListItem):
    geom: dict[str, Any]


class RoadSegmentListResponse(BaseModel):
    items: list[RoadSegmentListItem]
    limit: int
    offset: int
    count: int


class RoadSegmentDeleteResponse(BaseModel):
    message: str
    road_id: int


class RoadSegmentFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any]
    properties: RoadSegmentListItem


class RoadSegmentFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    count: int
    limit: int
    offset: int
    features: list[RoadSegmentFeature]


# ---------------------------------------------------------
# Road segment DAO
# ---------------------------------------------------------

class RoadSegmentDAO:
    LIST_COLUMNS = """
        road_id,
        name,
        speed_limit_kph,
        is_oneway,
        direction,
        created_at
    """

    DETAIL_COLUMNS = LIST_COLUMNS + """,
        ST_AsGeoJSON(geom)::json AS geom
    """

    LINESTRING_SQL = "ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)"

    @staticmethod
    def _geojson(coordinates):
        return json.dumps({"type": "LineString", "coordinates": coordinates})

    @staticmethod
    def _filters(name=None, min_speed_kph=None, max_speed_kph=None, bbox=None):
        conditions = []
        params = []

        if name is not None:
            # Case-insensitive partial match.
            conditions.append("name ILIKE %s")
            params.append(f"%{name}%")
        if min_speed_kph is not None:
            conditions.append("speed_limit_kph >= %s")
            params.append(min_speed_kph)
        if max_speed_kph is not None:
            conditions.append("speed_limit_kph <= %s")
            params.append(max_speed_kph)
        if bbox is not None:
            # ST_Intersects keeps roads inside, touching or crossing the box.
            conditions.append(
                "ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))"
            )
            params.extend(bbox)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        return where_clause, params

    def _get_page(self, columns, limit, offset, **filters):
        where_clause, params = self._filters(**filters)
        query = f"""
            SELECT {columns}
            FROM road_segment
            {where_clause}
            ORDER BY road_id
            LIMIT %s OFFSET %s
        """
        count_query = f"""
            SELECT COUNT(*) AS total
            FROM road_segment
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

    def get_all_road_segments(
        self, limit, offset, name=None, min_speed_kph=None, max_speed_kph=None, bbox=None,
    ):
        return self._get_page(
            self.LIST_COLUMNS, limit, offset, name=name,
            min_speed_kph=min_speed_kph, max_speed_kph=max_speed_kph, bbox=bbox,
        )

    def get_road_segments_geojson(
        self, limit, offset, name=None, min_speed_kph=None, max_speed_kph=None,
    ):
        return self._get_page(
            self.DETAIL_COLUMNS, limit, offset, name=name,
            min_speed_kph=min_speed_kph, max_speed_kph=max_speed_kph,
        )

    def get_road_segment_by_id(self, road_id) -> dict | None:
        # Get connection from pool
        with get_db_connection() as conn:
            # now get the cursor
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            query = f"""
                SELECT {self.DETAIL_COLUMNS}
                FROM road_segment
                WHERE road_id = %s
            """
            cursor.execute(query, (road_id,))
            row = cursor.fetchone()
            result = dict(row) if row else None
            # Always close cursor
            cursor.close()
        return result

    def create_road_segment(self, new_road) -> int:
        # Get connection from pool
        with get_db_connection() as conn:
            # now get the cursor
            cursor = conn.cursor()
            query = f"""
                INSERT INTO road_segment (
                    name, speed_limit_kph, is_oneway, direction, geom
                ) VALUES (
                    %s, %s, %s, %s, {self.LINESTRING_SQL}
                )
                RETURNING road_id
            """
            cursor.execute(query, (
                new_road["name"], new_road.get("speed_limit_kph"),
                new_road.get("is_oneway"), new_road.get("direction"),
                self._geojson(new_road["geom"]),
            ))
            road_id = cursor.fetchone()[0]
            # Always close cursor
            cursor.close()
        # Leaving the block commits the change to the DB
        return road_id

    def update_road_segment(self, road_id, changes) -> bool:
        allowed = {"name", "speed_limit_kph", "is_oneway", "direction", "geom"}
        if not changes or not set(changes).issubset(allowed):
            raise ValueError("At least one valid updatable field is required")

        # Only the supplied fields are updated (partial or full update).
        assignments = []
        values = []
        for field, value in changes.items():
            if field == "geom":
                assignments.append(sql.SQL("geom = " + self.LINESTRING_SQL))
                values.append(self._geojson(value))
            else:
                assignments.append(sql.SQL("{} = %s").format(sql.Identifier(field)))
                values.append(value)

        query = sql.SQL("""
            UPDATE road_segment
            SET {}
            WHERE road_id = %s
        """).format(sql.SQL(", ").join(assignments))

        # Get connection from pool
        with get_db_connection() as conn:
            # now get the cursor
            cursor = conn.cursor()
            cursor.execute(query, values + [road_id])
            rows = cursor.rowcount
            # Always close cursor
            cursor.close()
        return rows == 1

    def delete_road_segment(self, road_id) -> bool:
        # Get connection from pool
        with get_db_connection() as conn:
            # now get the cursor
            cursor = conn.cursor()
            query = """
                DELETE FROM road_segment
                WHERE road_id = %s
            """
            cursor.execute(query, (road_id,))
            rows = cursor.rowcount
            # Always close cursor
            cursor.close()
        return rows == 1
