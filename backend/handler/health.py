import logging

from fastapi import HTTPException

from backend.dao.health import HealthDAO


logger = logging.getLogger(__name__)


class HealthHandler:
    
    # Handles database health check requests.

    # Coordinates DAO operations and HTTP responses.
    

    def __init__(self):
        self.dao = HealthDAO()

    def get_database_status(self):

        try:
            result = self.dao.get_database_status()

            return {
                "status": "connected",
                "database": result["database"],
                "postgis_version": result["postgis_version"]
            }

        except Exception:
            logger.exception("Database health check failed")

            raise HTTPException(
                status_code=503,
                detail="Database connection unavailable"
            )