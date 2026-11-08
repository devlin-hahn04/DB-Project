"""Trip API business rules, filter validation and HTTP errors (Issue #23)."""

import logging
import re
from datetime import datetime

from fastapi import HTTPException
from psycopg2 import DataError, IntegrityError
from psycopg2.errorcodes import CHECK_VIOLATION, FOREIGN_KEY_VIOLATION, NOT_NULL_VIOLATION

from backend.dao.trips import TIMESTAMP_PATTERN, TripDAO, normalize_timestamp

logger = logging.getLogger(__name__)
CREATE_ERROR = "Malformed geometry or invalid JSON."
UPDATE_ERROR = "Malformed JSON or empty patch payload."
QUERY_ERROR = "Invalid query parameter values."


class TripHandler:
    def __init__(self):
        self.dao = TripDAO()

    @staticmethod
    def _parse_nonnegative(value):
        if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
            raise HTTPException(status_code=400, detail=QUERY_ERROR)
        return int(value)

    @classmethod
    def _parse_positive(cls, value):
        result = cls._parse_nonnegative(value)
        if not result:
            raise HTTPException(status_code=400, detail=QUERY_ERROR)
        return result

    @staticmethod
    def _parse_timestamp(value):
        # A raw "+" in a URL query is decoded as a space.
        value = re.sub(r" (\d{2}:\d{2})$", r"+\1", value)
        if not TIMESTAMP_PATTERN.fullmatch(value):
            raise HTTPException(status_code=400, detail=QUERY_ERROR)
        try:
            return normalize_timestamp(datetime.fromisoformat(value.replace("z", "Z")))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=QUERY_ERROR) from error

    def _parse_filters(self, limit, offset, vehicle_id, from_ts, to_ts):
        parsed_limit = self._parse_nonnegative(limit)
        parsed_offset = self._parse_nonnegative(offset)
        parsed_vehicle = self._parse_positive(vehicle_id) if vehicle_id is not None else None
        parsed_from = self._parse_timestamp(from_ts) if from_ts is not None else None
        parsed_to = self._parse_timestamp(to_ts) if to_ts is not None else None
        if parsed_from is not None and parsed_to is not None and parsed_from > parsed_to:
            raise HTTPException(status_code=400, detail=QUERY_ERROR)
        return parsed_limit, parsed_offset, parsed_vehicle, parsed_from, parsed_to

    @staticmethod
    def _normalize_data(data):
        data = dict(data)
        for field in ("start_geom", "end_geom"):
            if data.get(field) is not None and hasattr(data[field], "model_dump"):
                data[field] = data[field].model_dump()
        return data

    @staticmethod
    def _check_interval(data, update=False):
        if data["end_ts"] <= data["start_ts"]:
            raise HTTPException(
                status_code=422 if update else 400,
                detail="Validation failed." if update else CREATE_ERROR,
            )

    def _check_vehicle(self, vehicle_id, update=False):
        if not self.dao.vehicle_exists(vehicle_id):
            raise HTTPException(
                status_code=404,
                detail="trip_id or referenced vehicle_id does not exist."
                if update else "vehicle_id does not exist.",
            )

    @staticmethod
    def _db_error(error, update=False):
        if error.pgcode == FOREIGN_KEY_VIOLATION:
            raise HTTPException(
                status_code=404,
                detail="trip_id or referenced vehicle_id does not exist."
                if update else "vehicle_id does not exist.",
            ) from error
        if error.pgcode == CHECK_VIOLATION:
            raise HTTPException(
                status_code=422 if update else 400,
                detail="Validation failed." if update else CREATE_ERROR,
            ) from error
        if error.pgcode == NOT_NULL_VIOLATION:
            raise HTTPException(status_code=400, detail=UPDATE_ERROR if update else CREATE_ERROR) from error
        logger.exception("Unexpected Trip integrity error")
        raise HTTPException(status_code=500, detail="Internal server error") from error

    def create_trip(self, data):
        data = self._normalize_data(data)
        self._check_interval(data)

        try:
            self._check_vehicle(data["vehicle_id"])
            new_id = self.dao.create_trip(data)
            return self.dao.get_trip_by_id(new_id)

        except HTTPException:
            raise

        except IntegrityError as error:
            self._db_error(error)

        except DataError as error:
            logger.warning("Invalid Trip creation data: %s", error)
            raise HTTPException(
                status_code=400,
                detail=CREATE_ERROR,
            ) from error

        except Exception as error:
            logger.exception("Trip creation failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from error

    def get_trips(self, limit, offset, vehicle_id=None, from_ts=None, to_ts=None):
        limit, offset, vehicle_id, from_ts, to_ts = self._parse_filters(
            limit, offset, vehicle_id, from_ts, to_ts
        )
        try:
            items, count = self.dao.get_trips(limit, offset, vehicle_id, from_ts, to_ts)
            return {"items": items, "limit": limit, "offset": offset, "count": count}
        except Exception as error:
            logger.exception("Trip listing failed")
            raise HTTPException(status_code=500, detail="Internal server error") from error

    def get_trip_by_id(self, trip_id):
        try:
            record = self.dao.get_trip_by_id(trip_id)
        except Exception as error:
            logger.exception("Trip retrieval failed")
            raise HTTPException(status_code=500, detail="Internal server error") from error
        if record is None:
            raise HTTPException(status_code=404, detail="trip_id does not exist.")
        return record

    def update_trip(self, trip_id, changes):
        if not changes:
            raise HTTPException(status_code=400, detail=UPDATE_ERROR)

        for field in ("vehicle_id", "start_ts", "end_ts"):
            if field in changes and changes[field] is None:
                raise HTTPException(status_code=400, detail=UPDATE_ERROR)

        changes = self._normalize_data(changes)

        try:
            existing = self.dao.get_trip_by_id(trip_id)

            if existing is None:
                raise HTTPException(
                    status_code=404,
                    detail="trip_id or referenced vehicle_id does not exist."
                )

            merged = {**existing, **changes}
            self._check_interval(merged, update=True)

            if "vehicle_id" in changes:
                self._check_vehicle(changes["vehicle_id"], update=True)

            updated = self.dao.update_trip(trip_id, changes)

            if not updated:
                raise HTTPException(
                    status_code=404,
                    detail="trip_id or referenced vehicle_id does not exist."
                )

            return self.dao.get_trip_by_id(trip_id)

        except HTTPException:
            raise

        except IntegrityError as error:
            self._db_error(error, update=True)

        except DataError as error:
            logger.warning("Invalid Trip update data: %s", error)
            raise HTTPException(
                status_code=400,
                detail=UPDATE_ERROR,
            ) from error

        except Exception as error:
            logger.exception("Trip update failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error"
            ) from error

    def delete_trip(self, trip_id):
        try:
            deleted = self.dao.delete_trip(trip_id)
        except Exception as error:
            logger.exception("Trip deletion failed")
            raise HTTPException(status_code=500, detail="Internal server error") from error
        if not deleted:
            raise HTTPException(status_code=404, detail="trip_id does not exist.")
        return {"message": "Trip deleted successfully.", "trip_id": trip_id}

    def get_vehicle_trips(self, vehicle_id, limit="20", offset="0", from_ts=None, to_ts=None):
        try:
            self._check_vehicle(vehicle_id)
        except HTTPException:
            raise
        result = self.get_trips(limit, offset, str(vehicle_id), from_ts, to_ts)
        return {"vehicle_id": vehicle_id, **result}
