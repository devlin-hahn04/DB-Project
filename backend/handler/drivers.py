
import logging

from fastapi import HTTPException
from psycopg2 import IntegrityError
from psycopg2.errorcodes import (
    UNIQUE_VIOLATION,
    FOREIGN_KEY_VIOLATION,
    NOT_NULL_VIOLATION,
    CHECK_VIOLATION,
)

from backend.dao.drivers import DriverDAO


logger = logging.getLogger(__name__)


class DriverHandler:
    """
    Handles driver CRUD requests.
    Coordinates DAO operations and HTTP responses.
    """

    def __init__(self):
        self.dao = DriverDAO()

    def create_driver(self, data):
        try:
            return self.dao.create_driver(data)

        except IntegrityError as error:
            if error.pgcode == UNIQUE_VIOLATION:
                raise HTTPException(
                    status_code=409,
                    detail="license_number already exists.",
                ) from error

            if error.pgcode in (
                NOT_NULL_VIOLATION,
                CHECK_VIOLATION,
            ):
                raise HTTPException(
                    status_code=422,
                    detail="A required field is null or invalid.",
                ) from error

            logger.exception(
                "Driver creation violated a database constraint"
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from error

        except Exception:
            logger.exception("Driver creation failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            )

    def get_driver_by_id(self, driver_id):
        try:
            driver = self.dao.get_driver_by_id(driver_id)

        except Exception:
            logger.exception("Driver retrieval failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            )

        if driver is None:
            raise HTTPException(
                status_code=404,
                detail="driver_id does not exist.",
            )

        return driver

    def get_drivers(
        self,
        limit,
        offset,
        name=None,
        license_number=None,
    ):
        try:
            drivers, total = self.dao.get_drivers(
                limit,
                offset,
                name,
                license_number,
            )

            return {
                "items": drivers,
                "limit": limit,
                "offset": offset,
                "count": total,
            }

        except Exception:
            logger.exception("Driver listing failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            )

    def update_driver(self, driver_id, data):
        try:
            driver = self.dao.update_driver(
                driver_id,
                data,
            )

        except IntegrityError as error:
            if error.pgcode == UNIQUE_VIOLATION:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Updated license_number conflicts "
                        "with another driver."
                    ),
                ) from error

            if error.pgcode in (
                NOT_NULL_VIOLATION,
                CHECK_VIOLATION,
            ):
                raise HTTPException(
                    status_code=422,
                    detail="A supplied field is null or invalid.",
                ) from error

            logger.exception(
                "Driver update violated a database constraint"
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from error

        except Exception:
            logger.exception("Driver update failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            )

        if driver is None:
            raise HTTPException(
                status_code=404,
                detail="driver_id does not exist.",
            )

        return driver

    def delete_driver(self, driver_id):
        try:
            deleted = self.dao.delete_driver(driver_id)

        except IntegrityError as error:
            if error.pgcode == FOREIGN_KEY_VIOLATION:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "The driver is referenced by "
                        "a vehicle assignment."
                    ),
                ) from error

            logger.exception(
                "Driver deletion violated a database constraint"
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            ) from error

        except Exception:
            logger.exception("Driver deletion failed")
            raise HTTPException(
                status_code=500,
                detail="Internal server error",
            )

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="driver_id does not exist.",
            )

        return {
            "message": "Driver deleted successfully.",
            "driver_id": driver_id,
        }
