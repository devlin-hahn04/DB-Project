"""Request validation, business rules and HTTP errors for location pings (Issue #22)."""

import logging
import math
import re
from datetime import datetime

from fastapi import HTTPException
from psycopg2 import IntegrityError
from psycopg2.errorcodes import FOREIGN_KEY_VIOLATION, NOT_NULL_VIOLATION

from backend.dao.location_pings import (
    LocationPingDAO,
    TIMESTAMP_PATTERN,
    normalize_timestamp,
    valid_latitude,
    valid_longitude,
)

logger = logging.getLogger(__name__)


CREATE_ERROR = "Malformed geometry or invalid JSON."
UPDATE_ERROR = "Malformed JSON or empty patch payload."
LIST_QUERY_ERROR = "Invalid query parameter values."
VEHICLE_PINGS_QUERY_ERROR = "Invalid query parameters."
INTERNAL_ERROR = "Internal server error"


class LocationPingHandler:
    """
    Handles location ping requests.
    Validates query parameters, applies business rules and maps
    DAO results to HTTP responses.
    """

    def __init__(self):
        self.dao = LocationPingDAO()

    # ---------------------------------------------------------
    # Query parameter validation
    # ---------------------------------------------------------

    @staticmethod
    def _bad_query(detail):
        return HTTPException(status_code=400, detail=detail)

    def _parse_nonnegative(self, value, detail):
        if not value.isascii() or not value.isdecimal():
            raise self._bad_query(detail)
        return int(value)

    def _parse_positive(self, value, detail):
        parsed = self._parse_nonnegative(value, detail)
        if parsed == 0:
            raise self._bad_query(detail)
        return parsed

    def _parse_timestamp(self, value, detail):
        # An unencoded "+" offset arrives as a space; restore it.
        value = re.sub(r" (\d{2}:\d{2})$", r"+\1", value.strip())
        if not TIMESTAMP_PATTERN.fullmatch(value):
            raise self._bad_query(detail)
        try:
            parsed = datetime.fromisoformat(value.replace("z", "Z"))
        except ValueError as error:
            raise self._bad_query(detail) from error
        return normalize_timestamp(parsed)

    def _parse_bbox(self, value, detail):
        parts = value.split(",")
        if len(parts) != 4:
            raise self._bad_query(detail)
        try:
            min_lon, min_lat, max_lon, max_lat = (float(part) for part in parts)
        except ValueError as error:
            raise self._bad_query(detail) from error
        values = (min_lon, min_lat, max_lon, max_lat)
        if (
            not all(math.isfinite(item) for item in values)
            or not valid_longitude(min_lon) or not valid_longitude(max_lon)
            or not valid_latitude(min_lat) or not valid_latitude(max_lat)
            or min_lon >= max_lon or min_lat >= max_lat
        ):
            raise self._bad_query(detail)
        return values

    def _parse_time_range(self, from_ts, to_ts, detail):
        parsed_from = self._parse_timestamp(from_ts, detail) if from_ts is not None else None
        parsed_to = self._parse_timestamp(to_ts, detail) if to_ts is not None else None
        if parsed_from is not None and parsed_to is not None and parsed_from > parsed_to:
            raise self._bad_query(detail)
        return parsed_from, parsed_to

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    @staticmethod
    def _to_dao_data(data):
        """Turn a validated GeoJSON Point into the (lon, lat) pair the DAO stores."""
        data = dict(data)
        if data.get("geom") is not None:
            data["geom"] = tuple(data["geom"]["coordinates"])
        return data

    @staticmethod
    def _internal_error(message, error):
        logger.exception(message)
        return HTTPException(status_code=500, detail=INTERNAL_ERROR)

    # ---------------------------------------------------------
    # Endpoints
    # ---------------------------------------------------------

    def get_all_pings(self, limit, offset, vehicle_id=None, from_ts=None, to_ts=None, bbox=None):
        detail = LIST_QUERY_ERROR
        parsed_limit = self._parse_nonnegative(limit, detail)
        parsed_offset = self._parse_nonnegative(offset, detail)
        parsed_vehicle_id = (
            self._parse_positive(vehicle_id, detail) if vehicle_id is not None else None
        )
        parsed_from, parsed_to = self._parse_time_range(from_ts, to_ts, detail)
        parsed_bbox = self._parse_bbox(bbox, detail) if bbox is not None else None

        try:
            items, count = self.dao.get_all_pings(
                parsed_limit, parsed_offset, parsed_vehicle_id,
                parsed_from, parsed_to, parsed_bbox,
            )
        except Exception as error:
            raise self._internal_error("Location ping listing failed", error) from error

        return {"items": items, "limit": parsed_limit, "offset": parsed_offset, "count": count}

    def get_ping_by_id(self, ping_id):
        try:
            result = self.dao.get_ping_by_id(ping_id)
        except Exception as error:
            raise self._internal_error("Location ping retrieval failed", error) from error

        if result is None:
            raise HTTPException(status_code=404, detail="ping_id does not exist.")
        return result

    def create_ping(self, new_ping):
        new_ping = self._to_dao_data(new_ping)
        try:
            if not self.dao.vehicle_exists(new_ping["vehicle_id"]):
                raise HTTPException(status_code=404, detail="vehicle_id does not exist.")
            ping_id = self.dao.create_ping(new_ping)
            return self.dao.get_ping_by_id(ping_id)
        except HTTPException:
            raise
        except IntegrityError as error:
            if error.pgcode == FOREIGN_KEY_VIOLATION:
                raise HTTPException(status_code=404, detail="vehicle_id does not exist.") from error
            if error.pgcode == NOT_NULL_VIOLATION:
                raise HTTPException(status_code=400, detail=CREATE_ERROR) from error
            raise self._internal_error("Unexpected location ping integrity error", error) from error
        except Exception as error:
            raise self._internal_error("Location ping creation failed", error) from error

    def get_pings_by_vehicle(self, vehicle_id, limit, offset, from_ts=None, to_ts=None):
        detail = VEHICLE_PINGS_QUERY_ERROR
        parsed_limit = self._parse_nonnegative(limit, detail)
        parsed_offset = self._parse_nonnegative(offset, detail)
        parsed_from, parsed_to = self._parse_time_range(from_ts, to_ts, detail)

        try:
            if not self.dao.vehicle_exists(vehicle_id):
                raise HTTPException(status_code=404, detail="vehicle_id does not exist.")
            items, count = self.dao.get_pings_by_vehicle(
                vehicle_id, parsed_limit, parsed_offset, parsed_from, parsed_to,
            )
        except HTTPException:
            raise
        except Exception as error:
            raise self._internal_error("Vehicle ping history retrieval failed", error) from error

        # vehicle_id is reported once at the top level, not on every item.
        for item in items:
            item.pop("vehicle_id", None)
        return {
            "vehicle_id": vehicle_id,
            "items": items,
            "limit": parsed_limit,
            "offset": parsed_offset,
            "count": count,
        }

    def update_ping(self, ping_id, changes):
        if not changes:
            raise HTTPException(status_code=400, detail=UPDATE_ERROR)
        for field in ("vehicle_id", "ts", "geom"):
            if field in changes and changes[field] is None:
                raise HTTPException(status_code=400, detail=UPDATE_ERROR)

        changes = self._to_dao_data(changes)
        not_found = "ping_id or referenced vehicle_id does not exist."
        try:
            if self.dao.get_ping_by_id(ping_id) is None:
                raise HTTPException(status_code=404, detail=not_found)
            if "vehicle_id" in changes and not self.dao.vehicle_exists(changes["vehicle_id"]):
                raise HTTPException(status_code=404, detail=not_found)
            if not self.dao.update_ping(ping_id, changes):
                raise HTTPException(status_code=404, detail=not_found)
            return self.dao.get_ping_by_id(ping_id)
        except HTTPException:
            raise
        except IntegrityError as error:
            if error.pgcode == FOREIGN_KEY_VIOLATION:
                raise HTTPException(status_code=404, detail=not_found) from error
            if error.pgcode == NOT_NULL_VIOLATION:
                raise HTTPException(status_code=400, detail=UPDATE_ERROR) from error
            raise self._internal_error("Unexpected location ping integrity error", error) from error
        except Exception as error:
            raise self._internal_error("Location ping update failed", error) from error

    def delete_ping(self, ping_id):
        try:
            deleted = self.dao.delete_ping(ping_id)
        except Exception as error:
            raise self._internal_error("Location ping deletion failed", error) from error

        if not deleted:
            raise HTTPException(status_code=404, detail="ping_id does not exist.")
        return {"message": "Location ping deleted successfully.", "ping_id": ping_id}
