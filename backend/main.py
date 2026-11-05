from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel

from backend.config.dbconfig import initialize_connection_pool, close_connection_pool
from backend.handler.health import HealthHandler
from backend.handler.drivers import DriverHandler
from backend.handler.vehicles import VehicleHandler
from backend.handler.vehicle_assignments import VehicleAssignmentHandler
from backend.handler.location_pings import LocationPingHandler
from backend.dao.drivers import (
    DriverCreate, DriverUpdate, DriverResponse, DriverListResponse,
    DriverDeleteResponse,
)
from backend.dao.vehicles import (
    VehicleCreate, VehicleUpdate, VehicleResponse, VehicleListResponse,
    VehicleDeleteResponse, VehicleCurrentLocationResponse,
)
from backend.dao.vehicle_assignments import (
    AssignmentCreate, AssignmentUpdate, AssignmentResponse,
    AssignmentListResponse, AssignmentDeleteResponse,
)
from backend.dao.location_pings import (
    LocationPingCreate, LocationPingUpdate, LocationPingResponse,
    LocationPingListResponse, LocationPingDeleteResponse, VehiclePingListResponse,
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
# Root and health endpoints
# ---------------------------------------------------------

@app.get("/")
def root():
    return {"application": "Car Tracking REST API", "version": "1.0.0", "status": "running"}


@app.get("/api/v1/health", response_model=HealthResponse)
def health():
    return {"status": "ok", "service": "backend"}


@app.get("/api/v1/health/database", response_model=DatabaseHealthResponse)
def database_health():
    handler = HealthHandler()
    return handler.get_database_status()



# ---------------------------------------------------------
# Driver Handler and validation helpers
# ---------------------------------------------------------

driver_handler = DriverHandler()


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
    response_description="Driver was created successfully.",
    responses={
        400: {
            "description": "Malformed JSON or invalid payload shape."
        },
        409: {
            "description": "license_number already exists."
        },
        422: {
            "description": "A required field is null or invalid."
        },
    },
    tags=["Drivers"],
)
def create_driver(driver: DriverCreate):
    return driver_handler.create_driver(driver.model_dump())


# ---------------------------------------------------------
# GET /api/v1/drivers
# ---------------------------------------------------------

@app.get(
    "/api/v1/drivers",
    response_model=DriverListResponse,
    response_description="Driver collection returned successfully.",
    responses={
        400: {
            "description": "Invalid query parameter values."
        },
    },
    tags=["Drivers"],
)
def get_drivers(
    limit: str = Query(default="20"),
    offset: str = Query(default="0"),
    name: str | None = None,
    license_number: str | None = None,
):
    try:
        parsed_limit = parse_nonnegative_integer(limit, "limit")
        parsed_offset = parse_nonnegative_integer(offset, "offset")
    except HTTPException as error:
        raise HTTPException(
            status_code=400,
            detail="Invalid query parameter values.",
        ) from error

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
    response_description="Driver returned successfully.",
    responses={
        404: {
            "description": "driver_id does not exist."
        },
    },
    tags=["Drivers"],
)
def get_driver(driver_id: int):
    validate_driver_id(driver_id)
    return driver_handler.get_driver_by_id(driver_id)


# ---------------------------------------------------------
# PUT /api/v1/drivers/{driver_id}
# ---------------------------------------------------------

@app.put(
    "/api/v1/drivers/{driver_id}",
    response_model=DriverResponse,
    response_description="Driver updated successfully.",
    responses={
        400: {
            "description": "Malformed JSON or empty update payload."
        },
        404: {
            "description": "driver_id does not exist."
        },
        409: {
            "description": (
                "Updated license_number conflicts with another driver."
            )
        },
        422: {
            "description": "A supplied field is null or invalid."
        },
    },
    tags=["Drivers"],
)
def update_driver(driver_id: int, driver: DriverUpdate):
    validate_driver_id(driver_id)

    changes = driver.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(
            status_code=400,
            detail="Malformed JSON or empty update payload.",
        )

    return driver_handler.update_driver(driver_id, changes)


# ---------------------------------------------------------
# DELETE /api/v1/drivers/{driver_id}
# ---------------------------------------------------------

@app.delete(
    "/api/v1/drivers/{driver_id}",
    response_model=DriverDeleteResponse,
    response_description="Driver deleted successfully.",
    responses={
        404: {
            "description": "driver_id does not exist."
        },
        409: {
            "description": (
                "The driver is referenced by a vehicle assignment."
            )
        },
    },
    tags=["Drivers"],
)
def delete_driver(driver_id: int):
    validate_driver_id(driver_id)
    return driver_handler.delete_driver(driver_id)



# ---------------------------------------------------------
# Vehicle Handler and validation helper
# ---------------------------------------------------------

vehicle_handler = VehicleHandler()


def validate_vehicle_id(
    vehicle_id: int,
    current_location: bool = False,
    updating: bool = False,
):
    if vehicle_id <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "vehicle_id is not a positive integer."
                if current_location
                else "vehicle_id must be a positive integer"
            ),
        )

    return vehicle_id


# ---------------------------------------------------------
# POST /api/v1/vehicles
# ---------------------------------------------------------

@app.post(
    "/api/v1/vehicles",
    response_model=VehicleResponse,
    status_code=201,
    response_description="Vehicle was created successfully.",
    responses={
        400: {"description": "Malformed JSON or invalid payload shape."},
        404: {"description": "Referenced vehicle_type_id or vehicle_status_id does not exist."},
        409: {"description": "plate_number already exists."},
    },
    tags=["Vehicles"],
)
def create_vehicle(vehicle: VehicleCreate):
    return vehicle_handler.create_vehicle(vehicle.model_dump())


# ---------------------------------------------------------
# GET /api/v1/vehicles
# ---------------------------------------------------------

@app.get(
    "/api/v1/vehicles",
    response_model=VehicleListResponse,
    response_description="Vehicle collection returned successfully.",
    responses={400: {"description": "Invalid query parameter values."}},
    tags=["Vehicles"],
)
def get_vehicles(
    limit: str = Query(default="20"),
    offset: str = Query(default="0"),
    plate_number: str | None = None,
    status: str | None = None,
):
    try:
        parsed_limit = parse_nonnegative_integer(limit, "limit")
        parsed_offset = parse_nonnegative_integer(offset, "offset")
    except HTTPException as error:
        raise HTTPException(
            status_code=400, detail="Invalid query parameter values."
        ) from error

    return vehicle_handler.get_vehicles(
        limit=parsed_limit, offset=parsed_offset,
        plate_number=plate_number, status=status,
    )


# ---------------------------------------------------------
# GET /api/v1/vehicles/{vehicle_id}
# ---------------------------------------------------------

@app.get(
    "/api/v1/vehicles/{vehicle_id}",
    response_model=VehicleResponse,
    response_description="Vehicle returned successfully.",
    responses={404: {"description": "vehicle_id does not exist."}},
    tags=["Vehicles"],
)
def get_vehicle(vehicle_id: int):
    validate_vehicle_id(vehicle_id)
    return vehicle_handler.get_vehicle_by_id(vehicle_id)


# ---------------------------------------------------------
# PUT /api/v1/vehicles/{vehicle_id}
# ---------------------------------------------------------

@app.put(
    "/api/v1/vehicles/{vehicle_id}",
    response_model=VehicleResponse,
    response_description="Vehicle updated successfully.",
    responses={
        400: {"description": "Malformed JSON or empty payload."},
        404: {"description": "vehicle_id or referenced foreign key does not exist."},
        409: {"description": "Updated plate_number conflicts with another vehicle."},
    },
    tags=["Vehicles"],
)
def update_vehicle(vehicle_id: int, vehicle: VehicleUpdate):
    validate_vehicle_id(vehicle_id, updating=True)
    changes = vehicle.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Malformed JSON or empty payload.")

    for required_field in (
        "vehicle_type_id", "vehicle_status_id", "plate_number",
    ):
        if required_field in changes and changes[required_field] is None:
            raise HTTPException(status_code=400, detail="Malformed JSON or empty payload.")

    return vehicle_handler.update_vehicle(vehicle_id, changes)


# ---------------------------------------------------------
# DELETE /api/v1/vehicles/{vehicle_id}
# ---------------------------------------------------------

@app.delete(
    "/api/v1/vehicles/{vehicle_id}",
    response_model=VehicleDeleteResponse,
    response_description="Vehicle deleted successfully.",
    responses={
        404: {"description": "vehicle_id does not exist."},
        409: {"description": "Deletion is blocked by business rules/foreign key constraints."},
    },
    tags=["Vehicles"],
)
def delete_vehicle(vehicle_id: int):
    validate_vehicle_id(vehicle_id)
    return vehicle_handler.delete_vehicle(vehicle_id)


# ---------------------------------------------------------
# GET /api/v1/vehicles/{vehicle_id}/current-location
# ---------------------------------------------------------

@app.get(
    "/api/v1/vehicles/{vehicle_id}/current-location",
    response_model=VehicleCurrentLocationResponse,
    response_description="Current location returned.",
    responses={
        400: {"description": "vehicle_id is not a positive integer."},
        404: {"description": "vehicle_id does not exist."},
        204: {"description": "Vehicle exists but has no recorded pings yet."},
    },
    tags=["Vehicles"],
)
def get_vehicle_current_location(vehicle_id: int):
    validate_vehicle_id(vehicle_id, current_location=True)
    location = vehicle_handler.get_current_location(vehicle_id)
    if location is None:
        return Response(status_code=204)
    return location


# ---------------------------------------------------------
# Vehicle Assignment REST API 
# ---------------------------------------------------------

assignment_handler = VehicleAssignmentHandler()


def validate_assignment_id(assignment_id: int):
    if assignment_id <= 0:
        raise HTTPException(status_code=400, detail="assignment_id must be a positive integer.")
    return assignment_id


@app.post(
    "/api/v1/vehicle-assignments",
    response_model=AssignmentResponse,
    status_code=201,
    response_description="Vehicle assignment was created successfully.",
    responses={
        400: {"description": "Malformed JSON or invalid payload shape."},
        404: {"description": "Referenced vehicle_id or driver_id does not exist."},
        422: {"description": "The assignment time interval is invalid."},
    },
    tags=["Vehicle Assignments"],
)
def create_assignment(assignment: AssignmentCreate):
    return assignment_handler.create_assignment(assignment.model_dump())


@app.get(
    "/api/v1/vehicle-assignments",
    response_model=AssignmentListResponse,
    response_description="Vehicle assignment collection returned successfully.",
    responses={400: {"description": "Invalid query parameter values."}},
    tags=["Vehicle Assignments"],
)
def get_assignments(
    limit: str = Query(default="20"),
    offset: str = Query(default="0"),
    vehicle_id: str | None = None,
    driver_id: str | None = None,
    active: str | None = None,
):
    try:
        parsed_limit = parse_nonnegative_integer(limit, "limit")
        parsed_offset = parse_nonnegative_integer(offset, "offset")
        parsed_vehicle_id = (
            parse_nonnegative_integer(vehicle_id, "vehicle_id")
            if vehicle_id is not None else None
        )
        parsed_driver_id = (
            parse_nonnegative_integer(driver_id, "driver_id")
            if driver_id is not None else None
        )
        if parsed_vehicle_id == 0 or parsed_driver_id == 0:
            raise ValueError("IDs must be positive")
        if active is not None and active.lower() not in ("true", "false"):
            raise ValueError("active must be true or false")
    except (HTTPException, ValueError) as error:
        raise HTTPException(status_code=400, detail="Invalid query parameter values.") from error
    return assignment_handler.get_assignments(
        parsed_limit, parsed_offset, parsed_vehicle_id, parsed_driver_id,
        active.lower() == "true" if active is not None else None,
    )


@app.get(
    "/api/v1/vehicle-assignments/{assignment_id}",
    response_model=AssignmentResponse,
    response_description="Vehicle assignment returned successfully.",
    responses={404: {"description": "assignment_id does not exist."}},
    tags=["Vehicle Assignments"],
)
def get_assignment(assignment_id: int):
    validate_assignment_id(assignment_id)
    return assignment_handler.get_assignment_by_id(assignment_id)


@app.put(
    "/api/v1/vehicle-assignments/{assignment_id}",
    response_model=AssignmentResponse,
    response_description="Vehicle assignment updated successfully.",
    responses={
        400: {"description": "Malformed JSON or empty update payload."},
        404: {"description": "assignment_id or a referenced foreign key does not exist."},
        422: {"description": "The resulting assignment interval is invalid."},
    },
    tags=["Vehicle Assignments"],
)
def update_assignment(assignment_id: int, assignment: AssignmentUpdate):
    validate_assignment_id(assignment_id)
    changes = assignment.model_dump(exclude_unset=True)
    return assignment_handler.update_assignment(assignment_id, changes)


@app.delete(
    "/api/v1/vehicle-assignments/{assignment_id}",
    response_model=AssignmentDeleteResponse,
    response_description="Vehicle assignment deleted successfully.",
    responses={404: {"description": "assignment_id does not exist."}},
    tags=["Vehicle Assignments"],
)
def delete_assignment(assignment_id: int):
    validate_assignment_id(assignment_id)
    return assignment_handler.delete_assignment(assignment_id)


# ---------------------------------------------------------
# Location Ping REST API
# ---------------------------------------------------------

ping_handler = LocationPingHandler()


def validate_ping_id(ping_id: int): #helper
    if ping_id <= 0:
        raise HTTPException(status_code=400, detail="ping_id must be a positive integer.")
    return ping_id


@app.post(
    "/api/v1/location-pings",
    response_model=LocationPingResponse,
    status_code=201,
    response_description="Location ping created successfully.",
    responses={
        400: {"description": "Malformed geometry or invalid JSON."},
        404: {"description": "vehicle_id does not exist."},
    },
    tags=["Location Pings"],
)
def create_location_ping(ping: LocationPingCreate):
    return ping_handler.create_ping(ping.model_dump())


@app.get(
    "/api/v1/location-pings",
    response_model=LocationPingListResponse,
    response_description="Ping collection returned.",
    responses={400: {"description": "Invalid query parameter values."}},
    tags=["Location Pings"],
)
def get_location_pings(
    limit: str = Query(default="20"),
    offset: str = Query(default="0"),
    vehicle_id: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    bbox: str | None = Query(default=None, description="minLon,minLat,maxLon,maxLat"),
):
    return ping_handler.get_all_pings(limit, offset, vehicle_id, from_ts, to_ts, bbox)


@app.get(
    "/api/v1/location-pings/{ping_id}",
    response_model=LocationPingResponse,
    response_description="Ping returned successfully.",
    responses={404: {"description": "ping_id does not exist."}},
    tags=["Location Pings"],
)
def get_location_ping(ping_id: int):
    validate_ping_id(ping_id)
    return ping_handler.get_ping_by_id(ping_id)


@app.put(
    "/api/v1/location-pings/{ping_id}",
    response_model=LocationPingResponse,
    response_description="Ping updated successfully.",
    responses={
        400: {"description": "Malformed JSON or empty patch payload."},
        404: {"description": "ping_id or referenced vehicle_id does not exist."},
    },
    tags=["Location Pings"],
)
def update_location_ping(ping_id: int, ping: LocationPingUpdate):
    validate_ping_id(ping_id)
    return ping_handler.update_ping(ping_id, ping.model_dump(exclude_unset=True))


@app.delete(
    "/api/v1/location-pings/{ping_id}",
    response_model=LocationPingDeleteResponse,
    response_description="Ping deleted.",
    responses={404: {"description": "ping_id does not exist."}},
    tags=["Location Pings"],
)
def delete_location_ping(ping_id: int):
    validate_ping_id(ping_id)
    return ping_handler.delete_ping(ping_id)


@app.get(
    "/api/v1/vehicles/{vehicle_id}/pings",
    response_model=VehiclePingListResponse,
    response_description="Vehicle pings returned.",
    responses={
        400: {"description": "Invalid query parameters."},
        404: {"description": "vehicle_id does not exist."},
    },
    tags=["Location Pings"],
)
def get_vehicle_pings(
    vehicle_id: int,
    limit: str = Query(default="20"),
    offset: str = Query(default="0"),
    from_ts: str | None = None,
    to_ts: str | None = None,
):
    validate_vehicle_id(vehicle_id)
    return ping_handler.get_pings_by_vehicle(vehicle_id, limit, offset, from_ts, to_ts)


# ---------------------------------------------------------
# Validation error handler
# ---------------------------------------------------------


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    errors = exc.errors()
    path = request.url.path
    method = request.method

    is_vehicle_request = (
        path == "/api/v1/vehicles"
        or path.startswith("/api/v1/vehicles/")
    )

    is_driver_request = (
        path == "/api/v1/drivers"
        or path.startswith("/api/v1/drivers/")
    )

    malformed_json = any(
        error.get("type") == "json_invalid"
        for error in errors
    )

    # -----------------------------------------------------
    # Vehicle Assignment validation - rubric section 5.7
    # -----------------------------------------------------

    if (
        path == "/api/v1/vehicle-assignments"
        or path.startswith("/api/v1/vehicle-assignments/")
    ):
        path_error = any(
            error.get("loc", [None])[0] == "path" for error in errors
        )
        if path_error:
            return JSONResponse(
                status_code=400,
                content={"detail": "assignment_id must be a positive integer."},
            )

        if method == "GET" and path == "/api/v1/vehicle-assignments":
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid query parameter values."},
            )

        malformed_shape = any(
            error.get("type") in (
                "json_invalid", "model_attributes_type", "model_type",
                "dict_type", "list_type",
            )
            for error in errors
        )

        if method in ("POST", "PUT"):
            is_create = method == "POST"
            malformed_message = (
                "Malformed JSON or invalid payload shape."
                if is_create else "Malformed JSON or empty update payload."
            )
            interval_message = (
                "The assignment time interval is invalid."
                if is_create else "The resulting assignment interval is invalid."
            )

            if malformed_shape:
                return JSONResponse(
                    status_code=400, content={"detail": malformed_message}
                )

            # Invalid non-null timestamps (including invalid RFC 3339 strings)
            # use the rubric's interval-specific 422 response.
            timestamp_error = any(
                error.get("loc", [None])[-1] in (
                    "assigned_from", "assigned_to"
                )
                and error.get("type") != "missing"
                and error.get("input") is not None
                for error in errors
            )
            if timestamp_error:
                return JSONResponse(
                    status_code=422, content={"detail": interval_message}
                )

            # Missing/null required fields, invalid IDs and extra fields are
            # malformed payloads (400), not driver-specific 422 responses.
            return JSONResponse(
                status_code=400, content={"detail": malformed_message}
            )

    # Location Ping validation - rubric section 5.4

    if (
        path == "/api/v1/location-pings"
        or path.startswith("/api/v1/location-pings/")
    ):
        if any(error.get("loc", [None])[0] == "path" for error in errors):
            detail = "ping_id must be a positive integer."
        elif method == "GET":
            detail = "Invalid query parameter values."
        elif method == "PUT":
            detail = "Malformed JSON or empty patch payload."
        else:
            detail = "Malformed geometry or invalid JSON."
        return JSONResponse(status_code=400, content={"detail": detail})

    # -----------------------------------------------------
    # Vehicle validation - preserve existing behavior
    # -----------------------------------------------------

    if is_vehicle_request:
        if method == "POST" and path == "/api/v1/vehicles":
            status_code = 400
            detail = "Malformed JSON or invalid payload shape."

        elif method == "GET" and path == "/api/v1/vehicles":
            status_code = 400
            detail = "Invalid query parameter values."

        elif method == "GET" and path.endswith("/current-location"):
            status_code = 400
            detail = "vehicle_id is not a positive integer."

        elif method == "PUT":
            status_code = 400

            if any(
                error.get("loc", [None])[0] == "path"
                for error in errors
            ):
                detail = "vehicle_id must be a positive integer"
            else:
                detail = "Malformed JSON or empty payload."

        elif method in ("GET", "DELETE"):
            status_code = 400
            detail = "vehicle_id must be a positive integer"

        else:
            status_code = 400
            detail = "Malformed JSON or invalid payload shape."

        return JSONResponse(
            status_code=status_code,
            content={"detail": detail},
        )

    # -----------------------------------------------------
    # Driver validation
    # -----------------------------------------------------

    if is_driver_request:
        path_error = any(
            error.get("loc", [None])[0] == "path"
            for error in errors
        )

        if path_error:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "driver_id must be a positive integer"
                },
            )

        if method == "GET" and path == "/api/v1/drivers":
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "Invalid query parameter values."
                },
            )

        invalid_payload_shape = any(
            error.get("type") in (
                "model_attributes_type",
                "model_type",
                "dict_type",
                "list_type",
            )
            for error in errors
        )

        if method == "POST":
            if malformed_json or invalid_payload_shape:
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": (
                            "Malformed JSON or invalid payload shape."
                        )
                    },
                )

            return JSONResponse(
                status_code=422,
                content={
                    "detail": (
                        "A required field is null or invalid."
                    )
                },
            )

        if method == "PUT":
            if malformed_json or invalid_payload_shape:
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": (
                            "Malformed JSON or empty update payload."
                        )
                    },
                )

            return JSONResponse(
                status_code=422,
                content={
                    "detail": (
                        "A supplied field is null or invalid."
                    )
                },
            )

    # -----------------------------------------------------
    # Other endpoints
    # -----------------------------------------------------

    if malformed_json:
        return JSONResponse(
            status_code=400,
            content={"detail": "Malformed JSON request body"},
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



# ---------------------------------------------------------
# Customize Swagger UI / OpenAPI documentation
# ---------------------------------------------------------

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    for path, methods in openapi_schema["paths"].items():

        # Vehicle rubric does not document HTTP 422.
        if path.startswith("/api/v1/vehicles"):
            for method_details in methods.values():
                if isinstance(method_details, dict):
                    method_details.get("responses", {}).pop("422", None)

        # Location ping rubric does not document HTTP 422.
        if path.startswith("/api/v1/location-pings"):
            for method_details in methods.values():
                if isinstance(method_details, dict):
                    method_details.get("responses", {}).pop("422", None)

        # Assignment rubric documents HTTP 422 only for POST and PUT.
        if path.startswith("/api/v1/vehicle-assignments"):
            for method, method_details in methods.items():
                if isinstance(method_details, dict) and method.lower() not in ("post", "put"):
                    method_details.get("responses", {}).pop("422", None)

        # Driver rubric documents HTTP 422 only for POST and PUT.
        if path.startswith("/api/v1/drivers"):
            for method, method_details in methods.items():
                if (
                    isinstance(method_details, dict)
                    and method.lower() not in ("post", "put")
                ):
                    method_details.get("responses", {}).pop("422", None)

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi