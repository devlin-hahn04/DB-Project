
import logging

from fastapi import HTTPException
from psycopg2 import IntegrityError
from psycopg2.errorcodes import (
    UNIQUE_VIOLATION,
    FOREIGN_KEY_VIOLATION,
    NOT_NULL_VIOLATION,
    CHECK_VIOLATION,
)

from backend.dao.vehicles import VehicleDAO


logger = logging.getLogger(__name__)


class VehicleHandler:
    """
    Handles vehicle CRUD requests.
    Coordinates DAO operations and HTTP responses.
    """

    def __init__(self):
        self.dao = VehicleDAO()

    def _handle_integrity_error(self, error, operation):
        if error.pgcode == UNIQUE_VIOLATION:
            detail = (
                "plate_number already exists."
                if operation == "create"
                else "Updated plate_number conflicts with another vehicle."
            )
            raise HTTPException(
                status_code=409,
                detail=detail,
            ) from error

        if error.pgcode == FOREIGN_KEY_VIOLATION:
            detail = (
                "Referenced vehicle_type_id or vehicle_status_id does not exist."
                if operation == "create"
                else "vehicle_id or referenced foreign key does not exist."
            )
            raise HTTPException(
                status_code=404,
                detail=detail,
            ) from error

        if error.pgcode in (NOT_NULL_VIOLATION, CHECK_VIOLATION):
            detail = (
                "Malformed JSON or invalid payload shape."
                if operation == "create"
                else "Malformed JSON or empty payload."
            )
            raise HTTPException(
                status_code=400,
                detail=detail,
            ) from error

        logger.exception("Unexpected vehicle database constraint violation")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from error

    def create_vehicle(self, data):
        try:
            return self.dao.create_vehicle(data)

        except IntegrityError as error:
            self._handle_integrity_error(error, "create")

        except Exception:
            logger.exception("Vehicle creation failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            )

    def get_vehicle_by_id(self, vehicle_id):
        try:
            vehicle = self.dao.get_vehicle_by_id(vehicle_id)

        except Exception:
            logger.exception("Vehicle retrieval failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            )

        if vehicle is None:
            raise HTTPException(
                status_code=404,
                detail="vehicle_id does not exist.",
            )

        return vehicle

    def get_vehicles(self, limit, offset, plate_number=None, status=None):
        try:
            vehicles, total = self.dao.get_vehicles(
                limit,
                offset,
                plate_number,
                status,
            )

            return {
                "items": vehicles,
                "limit": limit,
                "offset": offset,
                "count": total,
            }

        except Exception:
            logger.exception("Vehicle listing failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            )

    def update_vehicle(self, vehicle_id, data):
        try:
            vehicle = self.dao.update_vehicle(vehicle_id, data)

        except IntegrityError as error:
            self._handle_integrity_error(error, "update")

        except Exception:
            logger.exception("Vehicle update failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            )

        if vehicle is None:
            raise HTTPException(
                status_code=404,
                detail="vehicle_id or referenced foreign key does not exist.",
            )

        return vehicle

    def delete_vehicle(self, vehicle_id):
        try:
            deleted = self.dao.delete_vehicle(vehicle_id)

        except IntegrityError as error:
            if error.pgcode == FOREIGN_KEY_VIOLATION:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Deletion is blocked by business rules/"
                        "foreign key constraints."
                    ),
                ) from error

            logger.exception("Unexpected vehicle deletion constraint violation")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from error

        except Exception:
            logger.exception("Vehicle deletion failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            )

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="vehicle_id does not exist.",
            )

        return {
            "message": "Vehicle deleted successfully.",
            "vehicle_id": vehicle_id,
        }

    def get_current_location(self, vehicle_id):
        self.get_vehicle_by_id(vehicle_id)

        try:
            location = self.dao.get_current_location(vehicle_id)

        except Exception:
            logger.exception("Vehicle current location retrieval failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            )

        return location
