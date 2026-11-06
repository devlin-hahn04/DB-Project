"""Parking Area API business rules and HTTP error handling (Issue #21)."""

import logging
import math

from fastapi import HTTPException
from psycopg2 import DataError, IntegrityError
from psycopg2.errorcodes import CHECK_VIOLATION, NOT_NULL_VIOLATION, FOREIGN_KEY_VIOLATION

from backend.dao.parking_areas import ParkingAreaDAO

from psycopg2 import Error as PsycopgError

logger = logging.getLogger(__name__)


class ParkingAreaHandler:
    def __init__(self):
        self.dao = ParkingAreaDAO()

    @staticmethod
    def parse_bbox(bbox: str | None):
        if bbox is None:
            return None
        try:
            parts = [float(part.strip()) for part in bbox.split(",")]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid query parameter values.") from exc
        if (len(parts) != 4 or not all(math.isfinite(x) for x in parts)
                or not (-180 <= parts[0] < parts[2] <= 180)
                or not (-90 <= parts[1] < parts[3] <= 90)):
            raise HTTPException(status_code=400, detail="Invalid query parameter values.")
        return parts

    
    @staticmethod
    def _is_geometry_input_error(exc):
        """
        Identify PostgreSQL/PostGIS errors caused by invalid
        user-supplied geometry.

        SQLSTATE class 22 represents data exceptions.

        PostGIS may also use XX000 (internal_error) when it
        cannot parse certain GeoJSON representations.
        Restrict that case to geometry-related messages.
        """
        pgcode = getattr(exc, "pgcode", None)

        if pgcode and pgcode.startswith("22"):
            return True

        if pgcode == "XX000":
            message = str(exc).lower()

            geometry_terms = (
                "geojson",
                "geometry",
                "polygon",
                "parse error",
                "invalid coordinate",
            )

            return any(term in message for term in geometry_terms)

        return False

    def _ensure_valid_geom(
        self,
        geom,
        error_detail="Malformed geometry or invalid JSON.",
    ):
        try:
            if not self.dao.is_valid_polygon(geom):
                raise HTTPException(
                    status_code=400,
                    detail=error_detail,
                )

        except HTTPException:
            raise

        except PsycopgError as exc:
            if self._is_geometry_input_error(exc):
                raise HTTPException(
                    status_code=400,
                    detail=error_detail,
                ) from exc

            logger.exception(
                "Unexpected database error during polygon validation"
            )

            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from exc

        except Exception as exc:
            logger.exception("Unexpected polygon validation failure")

            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from exc


    
    def create_parking_area(self, data):
        self._ensure_valid_geom(data["geom"])

        try:
            return self.dao.create_parking_area(data)

        except (DataError, IntegrityError) as exc:
            if (
                self._is_geometry_input_error(exc)
                or exc.pgcode in (
                    CHECK_VIOLATION,
                    NOT_NULL_VIOLATION,
                )
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Malformed geometry or invalid JSON.",
                ) from exc

            logger.exception("Parking area creation constraint failure")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from exc

        except PsycopgError as exc:
            if self._is_geometry_input_error(exc):
                raise HTTPException(
                    status_code=400,
                    detail="Malformed geometry or invalid JSON.",
                ) from exc

            logger.exception("Parking area creation database failure")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from exc

        except Exception as exc:
            logger.exception("Parking area creation failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from exc


    def get_parking_area_by_id(self, parking_area_id):
        try:
            result = self.dao.get_parking_area_by_id(parking_area_id)
        except Exception as exc:
            logger.exception("Parking area retrieval failed")
            raise HTTPException(status_code=500, detail="Internal server error") from exc
        if result is None:
            raise HTTPException(status_code=404, detail="parking_area_id does not exist.")
        return result

    def get_parking_areas(self, limit, offset, name=None, bbox=None):
        try:
            rows, total = self.dao.get_parking_areas(limit, offset, name, bbox)
            return {"items": rows, "limit": limit, "offset": offset, "count": total}
        except Exception as exc:
            logger.exception("Parking area listing failed")
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    
    def update_parking_area(self, parking_area_id, changes):
        if not changes:
            raise HTTPException(
                status_code=400,
                detail="Malformed JSON or empty patch payload.",
            )

        if "name" in changes and changes["name"] is None:
            raise HTTPException(
                status_code=400,
                detail="Malformed JSON or empty patch payload.",
            )

        if "geom" in changes:
            if changes["geom"] is None:
                raise HTTPException(
                    status_code=400,
                    detail="Malformed JSON or empty patch payload.",
                )

            self._ensure_valid_geom(
                changes["geom"],
                error_detail="Malformed JSON or empty patch payload.",
            )

        try:
            updated = self.dao.update_parking_area(
                parking_area_id,
                changes,
            )

        
        except (IntegrityError, DataError) as exc:
            if (
                self._is_geometry_input_error(exc)
                or exc.pgcode in (
                    CHECK_VIOLATION,
                    NOT_NULL_VIOLATION,
                )
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Malformed JSON or empty patch payload.",
                ) from exc

            logger.exception(
                "Unexpected parking area update constraint failure"
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from exc

        except PsycopgError as exc:
            if self._is_geometry_input_error(exc):
                raise HTTPException(
                    status_code=400,
                    detail="Malformed JSON or empty patch payload.",
                ) from exc

            logger.exception(
                "Unexpected parking area update database failure"
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from exc

        except Exception as exc:
            logger.exception("Parking area update failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from exc

        if updated is None:
            raise HTTPException(
                status_code=404,
                detail="parking_area_id does not exist.",
            )

        return updated


    def delete_parking_area(self, parking_area_id):
        try:
            deleted = self.dao.delete_parking_area(parking_area_id)
        except IntegrityError as exc:
            if exc.pgcode == FOREIGN_KEY_VIOLATION:
                raise HTTPException(status_code=409, detail="Deletion blocked by foreign key constraint.") from exc
            logger.exception("Parking area delete constraint failure")
            raise HTTPException(status_code=500, detail="Internal server error") from exc
        except Exception as exc:
            logger.exception("Parking area deletion failed")
            raise HTTPException(status_code=500, detail="Internal server error") from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="parking_area_id does not exist.")
        return {"message": "Parking area deleted successfully.", "parking_area_id": parking_area_id}