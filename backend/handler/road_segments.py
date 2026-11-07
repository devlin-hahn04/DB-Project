"""Request validation, business rules and HTTP errors for road segments (Issue #30)."""

import logging
import math

from fastapi import HTTPException
from psycopg2 import Error as PsycopgError
from psycopg2.errorcodes import CHECK_VIOLATION, NOT_NULL_VIOLATION

from backend.dao.location_pings import valid_latitude, valid_longitude
from backend.dao.road_segments import RoadSegmentDAO

logger = logging.getLogger(__name__)


CREATE_ERROR = "Malformed geometry or invalid JSON."
UPDATE_ERROR = "Malformed JSON or empty patch payload."
NOT_FOUND = "road_id does not exist."
LIST_QUERY_ERROR = "Invalid query parameter values."
GEOJSON_FILTER_ERROR = "Invalid or inconsistent filter values."
GEOJSON_PARAM_ERROR = "A query parameter fails type or range validation."
GEOJSON_SERVER_ERROR = "The service could not complete the request."
INTERNAL_ERROR = "Internal server error"


class InvalidQueryValue(ValueError):
    """A query parameter that is not a valid value for its type or range."""


def parse_nonnegative_int(value):
    if not value.isascii() or not value.isdecimal():
        raise InvalidQueryValue(value)
    return int(value)


def parse_nonnegative_number(value):
    try:
        number = float(value)
    except ValueError as error:
        raise InvalidQueryValue(value) from error
    if not math.isfinite(number) or number < 0:
        raise InvalidQueryValue(value)
    return int(number) if number.is_integer() else number


def parse_bbox(value):
    parts = value.split(",")
    if len(parts) != 4:
        raise InvalidQueryValue(value)
    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in parts)
    except ValueError as error:
        raise InvalidQueryValue(value) from error
    values = (min_lon, min_lat, max_lon, max_lat)
    if (
        not all(math.isfinite(item) for item in values)
        or not valid_longitude(min_lon) or not valid_longitude(max_lon)
        or not valid_latitude(min_lat) or not valid_latitude(max_lat)
        or min_lon >= max_lon or min_lat >= max_lat
    ):
        raise InvalidQueryValue(value)
    return values


def is_geometry_input_error(error):
    """PostGIS data errors caused by the supplied geometry."""
    pgcode = getattr(error, "pgcode", None) or ""
    if pgcode.startswith("22"):
        return True
    return pgcode == "XX000" and any(
        term in str(error).lower() for term in ("geojson", "geometry", "linestring", "parse")
    )


class RoadSegmentHandler:
    """
    Handles road segment requests.
    Validates query parameters, applies business rules and maps
    DAO results to HTTP responses.
    """

    def __init__(self):
        self.dao = RoadSegmentDAO()

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    @staticmethod
    def _to_dao_data(data):
        """Keep only the coordinates of a validated GeoJSON LineString."""
        data = dict(data)
        if data.get("geom") is not None:
            data["geom"] = data["geom"]["coordinates"]
        return data

    @staticmethod
    def _internal_error(message, detail=INTERNAL_ERROR):
        logger.exception(message)
        return HTTPException(status_code=500, detail=detail)

    def _database_error(self, error, bad_input_detail, message):
        """Map constraint and geometry errors to 400, anything else to 500."""
        if (
            getattr(error, "pgcode", None) in (CHECK_VIOLATION, NOT_NULL_VIOLATION)
            or is_geometry_input_error(error)
        ):
            return HTTPException(status_code=400, detail=bad_input_detail)
        return self._internal_error(message)

    # ---------------------------------------------------------
    # Endpoints
    # ---------------------------------------------------------

    def get_all_road_segments(
        self, limit, offset, name=None, min_speed_kph=None, max_speed_kph=None, bbox=None,
    ):
        try:
            parsed_limit = parse_nonnegative_int(limit)
            parsed_offset = parse_nonnegative_int(offset)
            parsed_min = parse_nonnegative_number(min_speed_kph) if min_speed_kph is not None else None
            parsed_max = parse_nonnegative_number(max_speed_kph) if max_speed_kph is not None else None
            parsed_bbox = parse_bbox(bbox) if bbox is not None else None
        except InvalidQueryValue as error:
            raise HTTPException(status_code=400, detail=LIST_QUERY_ERROR) from error
        if parsed_min is not None and parsed_max is not None and parsed_min > parsed_max:
            raise HTTPException(status_code=400, detail=LIST_QUERY_ERROR)

        try:
            items, count = self.dao.get_all_road_segments(
                parsed_limit, parsed_offset, name, parsed_min, parsed_max, parsed_bbox,
            )
        except Exception as error:
            raise self._internal_error("Road segment listing failed") from error

        return {"items": items, "limit": parsed_limit, "offset": parsed_offset, "count": count}

    def get_road_segments_geojson(
        self, limit, offset, name=None, min_speed_kph=None, max_speed_kph=None, bbox=None,
    ):
        # This endpoint does not accept a bbox parameter.
        if bbox is not None:
            raise HTTPException(status_code=400, detail=GEOJSON_FILTER_ERROR)
        try:
            parsed_limit = parse_nonnegative_int(limit)
            parsed_offset = parse_nonnegative_int(offset)
            parsed_min = parse_nonnegative_number(min_speed_kph) if min_speed_kph is not None else None
            parsed_max = parse_nonnegative_number(max_speed_kph) if max_speed_kph is not None else None
        except InvalidQueryValue as error:
            raise HTTPException(status_code=422, detail=GEOJSON_PARAM_ERROR) from error
        if parsed_min is not None and parsed_max is not None and parsed_min > parsed_max:
            raise HTTPException(status_code=400, detail=GEOJSON_FILTER_ERROR)

        try:
            rows, count = self.dao.get_road_segments_geojson(
                parsed_limit, parsed_offset, name, parsed_min, parsed_max,
            )
        except Exception as error:
            raise self._internal_error(
                "Road segment GeoJSON export failed", GEOJSON_SERVER_ERROR
            ) from error

        features = [
            {"type": "Feature", "geometry": row.pop("geom"), "properties": row}
            for row in rows
        ]
        return {
            "type": "FeatureCollection",
            "count": count,
            "limit": parsed_limit,
            "offset": parsed_offset,
            "features": features,
        }

    def get_road_segment_by_id(self, road_id):
        try:
            result = self.dao.get_road_segment_by_id(road_id)
        except Exception as error:
            raise self._internal_error("Road segment retrieval failed") from error

        if result is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return result

    def create_road_segment(self, new_road):
        new_road = self._to_dao_data(new_road)
        try:
            road_id = self.dao.create_road_segment(new_road)
            return self.dao.get_road_segment_by_id(road_id)
        except PsycopgError as error:
            raise self._database_error(
                error, CREATE_ERROR, "Road segment creation failed"
            ) from error
        except Exception as error:
            raise self._internal_error("Road segment creation failed") from error

    def update_road_segment(self, road_id, changes):
        if not changes:
            raise HTTPException(status_code=400, detail=UPDATE_ERROR)
        for field in ("name", "geom"):
            if field in changes and changes[field] is None:
                raise HTTPException(status_code=400, detail=UPDATE_ERROR)

        changes = self._to_dao_data(changes)
        try:
            if self.dao.get_road_segment_by_id(road_id) is None:
                raise HTTPException(status_code=404, detail=NOT_FOUND)
            if not self.dao.update_road_segment(road_id, changes):
                raise HTTPException(status_code=404, detail=NOT_FOUND)
            return self.dao.get_road_segment_by_id(road_id)
        except HTTPException:
            raise
        except PsycopgError as error:
            raise self._database_error(
                error, UPDATE_ERROR, "Road segment update failed"
            ) from error
        except Exception as error:
            raise self._internal_error("Road segment update failed") from error

    def delete_road_segment(self, road_id):
        try:
            deleted = self.dao.delete_road_segment(road_id)
        except Exception as error:
            raise self._internal_error("Road segment deletion failed") from error

        if not deleted:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return {"message": "Road segment deleted successfully.", "road_id": road_id}
