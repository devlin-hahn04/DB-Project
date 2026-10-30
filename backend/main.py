from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from pydantic import BaseModel

from backend.config.dbconfig import (
    initialize_connection_pool,
    close_connection_pool,
)

from backend.handler.health import HealthHandler
from backend.handler.drivers import DriverHandler

from backend.models.drivers import (
    DriverCreate,
    DriverUpdate,
    DriverResponse,
    DriverListResponse,
    DriverDeleteResponse,
)


# ---------------------------------------------------------
# Pydantic health response models
# ---------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    service: str


class DatabaseHealthResponse(BaseModel):
    status: str
    database: str
    postgis_version: str


# ---------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):

    initialize_connection_pool()

    yield

    close_connection_pool()


# ---------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------

app = FastAPI(
    title="Car Tracking REST API",
    description=(
        "Phase 2 REST API for the Car Tracking "
        "Database Project using Handler/DAO architecture."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------

@app.get("/")
def root():
    return {
        "application": "Car Tracking REST API",
        "version": "1.0.0",
        "status": "running",
    }


# ---------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------

@app.get(
    "/api/v1/health",
    response_model=HealthResponse,
)
def health():
    return {
        "status": "ok",
        "service": "backend",
    }


@app.get(
    "/api/v1/health/database",
    response_model=DatabaseHealthResponse,
)
def database_health():

    handler = HealthHandler()

    return handler.get_database_status()


# ---------------------------------------------------------
# Driver Handler
# ---------------------------------------------------------

driver_handler = DriverHandler()


# ---------------------------------------------------------
# Driver validation helpers
# ---------------------------------------------------------

def validate_driver_id(driver_id: int):

    if driver_id <= 0:
        raise HTTPException(
            status_code=400,
            detail="driver_id must be a positive integer",
        )

    return driver_id


def parse_nonnegative_integer(value: str, field_name: str):

    if not value.isascii() or not value.isdecimal():
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be a nonnegative integer",
        )

    return int(value)


# ---------------------------------------------------------
# POST /api/v1/drivers
# ---------------------------------------------------------

@app.post(
    "/api/v1/drivers",
    response_model=DriverResponse,
    status_code=201,
    tags=["Drivers"],
)
def create_driver(driver: DriverCreate):

    return driver_handler.create_driver(
        driver.model_dump()
    )


# ---------------------------------------------------------
# GET /api/v1/drivers
# ---------------------------------------------------------

@app.get(
    "/api/v1/drivers",
    response_model=DriverListResponse,
    tags=["Drivers"],
)
def get_drivers(
    limit: str = Query(default="20"),
    offset: str = Query(default="0"),
    name: str | None = None,
    license_number: str | None = None,
):

    parsed_limit = parse_nonnegative_integer(
        limit,
        "limit",
    )

    parsed_offset = parse_nonnegative_integer(
        offset,
        "offset",
    )

    return driver_handler.get_drivers(
        limit=parsed_limit,
        offset=parsed_offset,
        name=name,
        license_number=license_number,
    )


# ---------------------------------------------------------
# GET /api/v1/drivers/{driver_id}
# ---------------------------------------------------------

@app.get(
    "/api/v1/drivers/{driver_id}",
    response_model=DriverResponse,
    tags=["Drivers"],
)
def get_driver(driver_id: int):

    validate_driver_id(driver_id)

    return driver_handler.get_driver_by_id(
        driver_id
    )


# ---------------------------------------------------------
# PUT /api/v1/drivers/{driver_id}
# ---------------------------------------------------------

@app.put(
    "/api/v1/drivers/{driver_id}",
    response_model=DriverResponse,
    tags=["Drivers"],
)
def update_driver(
    driver_id: int,
    driver: DriverUpdate,
):

    validate_driver_id(driver_id)

    changes = driver.model_dump(
        exclude_unset=True
    )

    if not changes:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be supplied",
        )

    return driver_handler.update_driver(
        driver_id,
        changes,
    )


# ---------------------------------------------------------
# DELETE /api/v1/drivers/{driver_id}
# ---------------------------------------------------------

@app.delete(
    "/api/v1/drivers/{driver_id}",
    response_model=DriverDeleteResponse,
    tags=["Drivers"],
)
def delete_driver(driver_id: int):

    validate_driver_id(driver_id)

    return driver_handler.delete_driver(
        driver_id
    )


# ---------------------------------------------------------
# Validation error handler
# ---------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):

    errors = exc.errors()

    malformed_json = any(
        error.get("type") == "json_invalid"
        for error in errors
    )

    if malformed_json:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "Malformed JSON request body"
            },
        )

    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {
                    "loc": error.get("loc"),
                    "msg": error.get("msg"),
                    "type": error.get("type"),
                }
                for error in errors
            ]
        },
    )