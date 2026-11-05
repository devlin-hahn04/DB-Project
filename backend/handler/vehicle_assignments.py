"""Business rules and HTTP errors for Vehicle Assignment (Issue #20)."""

import logging

from fastapi import HTTPException
from psycopg2 import IntegrityError
from psycopg2.errorcodes import (
    FOREIGN_KEY_VIOLATION,
    CHECK_VIOLATION,
    NOT_NULL_VIOLATION,
)

from backend.dao.vehicle_assignments import VehicleAssignmentDAO

logger = logging.getLogger(__name__)


class VehicleAssignmentHandler:
    def __init__(self):
        self.dao = VehicleAssignmentDAO()

    @staticmethod
    def _interval_valid(data):
        end = data.get("assigned_to")
        return end is None or end > data["assigned_from"]

    def _validate_references(self, data, update=False):
        detail = (
            "assignment_id or a referenced foreign key does not exist."
            if update
            else "Referenced vehicle_id or driver_id does not exist."
        )
        if "vehicle_id" in data and not self.dao.vehicle_exists(data["vehicle_id"]):
            raise HTTPException(status_code=404, detail=detail)
        if "driver_id" in data and not self.dao.driver_exists(data["driver_id"]):
            raise HTTPException(status_code=404, detail=detail)

    @staticmethod
    def _database_error(error, update=False):
        if error.pgcode == FOREIGN_KEY_VIOLATION:
            raise HTTPException(
                status_code=404,
                detail=(
                    "assignment_id or a referenced foreign key does not exist."
                    if update else "Referenced vehicle_id or driver_id does not exist."
                ),
            ) from error
        if error.pgcode == CHECK_VIOLATION:
            raise HTTPException(
                status_code=422,
                detail=(
                    "The resulting assignment interval is invalid."
                    if update else "The assignment time interval is invalid."
                ),
            ) from error
        if error.pgcode == NOT_NULL_VIOLATION:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Malformed JSON or empty update payload."
                    if update else "Malformed JSON or invalid payload shape."
                ),
            ) from error
        logger.exception("Unexpected vehicle assignment database integrity error")
        raise HTTPException(status_code=500, detail="Internal server error") from error

    def create_assignment(self, data):
        if not self._interval_valid(data):
            raise HTTPException(
                status_code=422, detail="The assignment time interval is invalid."
            )
        try:
            self._validate_references(data)
            return self.dao.create_assignment(data)
        except HTTPException:
            raise
        except IntegrityError as error:
            self._database_error(error)
        except Exception as error:
            logger.exception("Vehicle assignment creation failed")
            raise HTTPException(status_code=500, detail="Internal server error") from error

    def get_assignments(self, limit, offset, vehicle_id=None, driver_id=None, active=None):
        try:
            items, count = self.dao.get_assignments(
                limit, offset, vehicle_id, driver_id, active
            )
            return {"items": items, "limit": limit, "offset": offset, "count": count}
        except Exception as error:
            logger.exception("Vehicle assignment listing failed")
            raise HTTPException(status_code=500, detail="Internal server error") from error

    def get_assignment_by_id(self, assignment_id):
        try:
            item = self.dao.get_assignment_by_id(assignment_id)
        except Exception as error:
            logger.exception("Vehicle assignment retrieval failed")
            raise HTTPException(status_code=500, detail="Internal server error") from error
        if item is None:
            raise HTTPException(status_code=404, detail="assignment_id does not exist.")
        return item

    def update_assignment(self, assignment_id, changes):
        if not changes:
            raise HTTPException(
                status_code=400, detail="Malformed JSON or empty update payload."
            )
        for field in ("vehicle_id", "driver_id", "assigned_from"):
            if field in changes and changes[field] is None:
                raise HTTPException(
                    status_code=400, detail="Malformed JSON or empty update payload."
                )
        try:
            original = self.dao.get_assignment_by_id(assignment_id)
            if original is None:
                raise HTTPException(
                    status_code=404,
                    detail="assignment_id or a referenced foreign key does not exist.",
                )
            merged = {**original, **changes}
            if not self._interval_valid(merged):
                raise HTTPException(
                    status_code=422,
                    detail="The resulting assignment interval is invalid.",
                )
            self._validate_references(changes, update=True)
            updated = self.dao.update_assignment(assignment_id, changes)
            if updated is None:
                raise HTTPException(
                    status_code=404,
                    detail="assignment_id or a referenced foreign key does not exist.",
                )
            return updated
        except HTTPException:
            raise
        except IntegrityError as error:
            self._database_error(error, update=True)
        except Exception as error:
            logger.exception("Vehicle assignment update failed")
            raise HTTPException(status_code=500, detail="Internal server error") from error

    def delete_assignment(self, assignment_id):
        try:
            deleted = self.dao.delete_assignment(assignment_id)
        except Exception as error:
            logger.exception("Vehicle assignment deletion failed")
            raise HTTPException(status_code=500, detail="Internal server error") from error
        if not deleted:
            raise HTTPException(status_code=404, detail="assignment_id does not exist.")
        return {
            "message": "Vehicle assignment deleted successfully.",
            "assignment_id": assignment_id,
        }
