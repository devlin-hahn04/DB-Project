
# Phase 2 — REST API Development and Deployment

[← Back to Project Overview](../../README.md)

## Overview

Phase 2 extends the PostgreSQL/PostGIS database from Phase 1 with a REST API for accessing and managing vehicle-tracking data. The API is built with Python, FastAPI, Pydantic, and a Handler/DAO architecture, and is deployed on Render alongside the hosted PostgreSQL database.

The implementation provides **39 required HTTP operations across seven resource groups**, including CRUD operations, vehicle location and history lookups, spatial filters, and GeoJSON export.

- **Live API:** https://car-tracking-api-82ra.onrender.com
- **Swagger UI:** https://car-tracking-api-82ra.onrender.com/docs
- **OpenAPI specification:** https://car-tracking-api-82ra.onrender.com/openapi.json
- **API prefix:** `/api/v1`

## 1. Architecture

Requests are handled by FastAPI routes, passed to handlers for application logic, and executed through DAOs against the PostgreSQL/PostGIS database. Pydantic models define request and response structures.

```text
Client / Swagger UI
        ↓ HTTP
FastAPI routes (backend/main.py)
        ↓
Handlers (backend/handler/)
        ↓
DAOs (backend/dao/)
        ↓ SQL / PostGIS
Render PostgreSQL database
```

The existing Phase 1 database schema and imported datasets are reused. Phase 2 adds API functionality rather than replacing the ETL or database design.

## 2. REST API Endpoints

All paths below are relative to `/api/v1`. A `{...}` segment represents a record ID supplied in the URL.

### Drivers — 5 operations

| Method | Endpoint | Purpose | Success |
|---|---|---|---|
| POST | `/drivers` | Create a driver | 201 |
| GET | `/drivers` | List or filter drivers | 200 |
| GET | `/drivers/{driver_id}` | Retrieve one driver | 200 |
| PUT | `/drivers/{driver_id}` | Update driver information | 200 |
| DELETE | `/drivers/{driver_id}` | Delete a driver if not referenced | 200 |

### Vehicles — 6 operations

| Method | Endpoint | Purpose | Success |
|---|---|---|---|
| POST | `/vehicles` | Register a vehicle | 201 |
| GET | `/vehicles` | List or filter vehicles | 200 |
| GET | `/vehicles/{vehicle_id}` | Retrieve a vehicle | 200 |
| PUT | `/vehicles/{vehicle_id}` | Update vehicle information | 200 |
| DELETE | `/vehicles/{vehicle_id}` | Delete a vehicle when dependencies allow | 200 |
| GET | `/vehicles/{vehicle_id}/current-location` | Retrieve its latest GPS ping | 200, or 204 if no pings exist |

### Vehicle Assignments — 5 operations

| Method | Endpoint | Purpose | Success |
|---|---|---|---|
| POST | `/vehicle-assignments` | Assign a driver to a vehicle | 201 |
| GET | `/vehicle-assignments` | List assignments, including active/inactive filters | 200 |
| GET | `/vehicle-assignments/{assignment_id}` | Retrieve an assignment | 200 |
| PUT | `/vehicle-assignments/{assignment_id}` | Update assignment details or time interval | 200 |
| DELETE | `/vehicle-assignments/{assignment_id}` | Delete an assignment | 200 |

### Location Pings — 6 operations

| Method | Endpoint | Purpose | Success |
|---|---|---|---|
| POST | `/location-pings` | Record a GPS observation | 201 |
| GET | `/location-pings` | List or filter GPS observations | 200 |
| GET | `/location-pings/{ping_id}` | Retrieve one observation | 200 |
| PUT | `/location-pings/{ping_id}` | Update an observation | 200 |
| DELETE | `/location-pings/{ping_id}` | Delete an observation | 200 |
| GET | `/vehicles/{vehicle_id}/pings` | Retrieve a vehicle's GPS history | 200 |

### Parking Areas — 5 operations

| Method | Endpoint | Purpose | Success |
|---|---|---|---|
| POST | `/parking-areas` | Create a parking-area polygon | 201 |
| GET | `/parking-areas` | List areas, including name and bounding-box filters | 200 |
| GET | `/parking-areas/{parking_area_id}` | Retrieve one area | 200 |
| PUT | `/parking-areas/{parking_area_id}` | Update area details or geometry | 200 |
| DELETE | `/parking-areas/{parking_area_id}` | Delete an area | 200 |

### Road Segments — 6 operations

| Method | Endpoint | Purpose | Success |
|---|---|---|---|
| POST | `/road-segments` | Create a road segment with line geometry | 201 |
| GET | `/road-segments` | List or filter roads by name, speed, or bounding box | 200 |
| GET | `/road-segments/{road_id}` | Retrieve one road segment | 200 |
| PUT | `/road-segments/{road_id}` | Update road attributes or geometry | 200 |
| DELETE | `/road-segments/{road_id}` | Delete a road segment | 200 |
| GET | `/road-segments/geojson` | Export road features as a GeoJSON FeatureCollection | 200 |

### Trips — 6 operations

| Method | Endpoint | Purpose | Success |
|---|---|---|---|
| POST | `/trips` | Record a vehicle trip | 201 |
| GET | `/trips` | List trips, with vehicle and time filters | 200 |
| GET | `/trips/{trip_id}` | Retrieve one trip | 200 |
| PUT | `/trips/{trip_id}` | Update trip details | 200 |
| DELETE | `/trips/{trip_id}` | Delete a trip | 200 |
| GET | `/vehicles/{vehicle_id}/trips` | Retrieve a vehicle's trip history | 200 |

**Additional utility routes** (not part of the 39 required resource operations): `GET /`, `GET /api/v1/health`, and `GET /api/v1/health/database`.

## 3. HTTP Status Codes and Response Messages

The API returns JSON for normal responses and errors. The tables below summarize the documented outcomes; exact request schemas, per-endpoint response bodies, and additional field rules are available in Swagger UI.

| Code | Meaning | Typical Use |
|---|---|---|
| 200 OK | Successful read, update, or deletion | GET, PUT, DELETE |
| 201 Created | New record created | POST |
| 204 No Content | Vehicle exists but has no location pings | Current-location lookup |
| 400 Bad Request | Invalid query parameter, malformed JSON, invalid geometry, or empty update | Filters and write validation |
| 404 Not Found | Requested record or referenced foreign key does not exist | ID lookups and writes |
| 409 Conflict | Duplicate unique value or blocked foreign-key deletion | Drivers and vehicles |
| 422 Unprocessable Entity | Field or interval validation fails on endpoints that specify 422 | Driver and assignment validation; trip updates; GeoJSON parameters |
| 500 Internal Server Error | Service could not complete the request | Documented for GeoJSON export |

### Examples of Documented Error Messages

| Resource / Situation | HTTP Code | `detail` Message |
|---|---|---|
| List endpoint with invalid query parameters | 400 | `Invalid query parameter values.` |
| Driver created with a duplicate license | 409 | `license_number already exists.` |
| Driver ID not found | 404 | `driver_id does not exist.` |
| Deleting a referenced driver | 409 | `The driver is referenced by a vehicle assignment.` |
| Vehicle created with a duplicate plate | 409 | `plate_number already exists.` |
| Vehicle ID not found | 404 | `vehicle_id does not exist.` |
| Vehicle deletion blocked by dependencies | 409 | `Deletion is blocked by business rules /foreign key constraints.` |
| Assignment with an invalid creation interval | 422 | `The assignment time interval is invalid.` |
| Assignment with an invalid updated interval | 422 | `The resulting assignment interval is invalid.` |
| Parking area malformed geometry / JSON | 400 | `Malformed geometry or invalid JSON.` |
| Road segment ID not found | 404 | `road_id does not exist.` |
| Location ping references an unknown vehicle | 404 | `vehicle_id does not exist.` |
| Trip update with invalid values | 422 | `Validation failed.` |
| GeoJSON invalid or inconsistent filters | 400 | `Invalid or inconsistent filter values.` |
| GeoJSON invalid typed or ranged parameter | 422 | `A query parameter fails type or range validation.` |

Some error messages vary depending on the HTTP method and resource. For example, an empty PUT payload may return `Malformed JSON or empty update payload.`, `Malformed JSON or empty payload.`, or `Malformed JSON or empty patch payload.` as defined by that endpoint. Consult `/docs` for the precise contract.

## 4. Pagination, Filtering, and Spatial Data

Collection endpoints support `limit` and `offset` for pagination. The API also supports resource-specific filters, including driver license numbers, vehicle plates, assignment activity, vehicle IDs, time ranges, road speed ranges, names, and geographic bounding boxes (`bbox`).

For spatial resources, PostGIS stores coordinates in SRID 4326 (WGS84). The API exposes GPS points, parking-area polygons, road lines, and a dedicated road-segment GeoJSON endpoint.

### Example Read-Only Requests

```http
GET /api/v1/drivers?limit=10&offset=0
GET /api/v1/vehicles?plate_number=EXAMPLE123
GET /api/v1/vehicle-assignments?active=true
GET /api/v1/vehicles/1/current-location
GET /api/v1/vehicles/1/pings?limit=20&offset=0
GET /api/v1/road-segments/geojson?limit=20&offset=0
```

## 5. Deployment and API Access

The application is hosted as a Render web service and connects to the Render-managed PostgreSQL/PostGIS database initialized in Phase 1.

1. Open [Swagger UI](https://car-tracking-api-82ra.onrender.com/docs) to inspect or execute API operations.
2. Use the `/api/v1` prefix when sending resource requests.
3. Use [OpenAPI JSON](https://car-tracking-api-82ra.onrender.com/openapi.json) for machine-readable endpoint definitions.

Database connection variables are configured privately in the hosting environment. Passwords and other credentials must not be committed to the repository. Local environment files remain excluded through `.gitignore`.

## 6. Verification and Results

Phase 2 was tested against the deployed Render API using a read-only test suite and a temporary write lifecycle test. The write tests created records, exercised updates and error cases, deleted the temporary data, verified baseline counts, and aligned the seven identity sequences.

| Verification | Result |
|---|---|
| Read-only live verification | **135 / 135 passed** |
| Full write, update, delete, and cleanup verification | **268 / 268 passed** |
| Required resource operations documented in OpenAPI | **39 / 39** |
| Required-resource OpenAPI response entries | **106** |
| Pagination parameter checks | **20 / 20** |
| Post-test table counts restored | **7 / 7 tables** |
| PostgreSQL identity sequences aligned with table maxima | **7 / 7 sequences** |

DataGrip was also used to independently verify table row counts, ID ranges, sequence values, and `is_called` flags on the hosted database.

Test-only scripts kept outside Git are not required to run the deployed API. These results describe the checks performed; they do not replace the course rubric's full endpoint specifications.

## 7. Related Documentation

- [Phase 1 — Database Setup, ETL, and Deployment](../phase1/README.md)
- [Project Overview](../../README.md)
