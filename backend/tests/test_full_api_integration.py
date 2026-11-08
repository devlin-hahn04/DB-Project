
"""Strict Car Tracking REST API integration tests.

Run from the project root:
    $env:CARTRACKING_E2E_ALLOW_WRITES = "cartracking_test"
    python -m unittest discover -s backend/tests -p test_full_api_integration.py -v

Uses only the isolated backend-test on 127.0.0.1:8001.
Creates temporary rows and cleans them up.
Do not run alongside database backup/restore tests.
"""

import json
import os
import subprocess
import unittest
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode

ROOT = "http://127.0.0.1:8001"
API = ROOT + "/api/v1"
D = API + "/drivers"
V = API + "/vehicles"
A = API + "/vehicle-assignments"
P = API + "/location-pings"
PA = API + "/parking-areas"
T = API + "/trips"
RS = API + "/road-segments"
MISSING = 999999999
START = "2032-05-20T12:00:00Z"
END = "2032-05-20T13:00:00Z"

EXPECTED = {
    ("/api/v1/drivers", "post"): {
        "201": "Driver was created successfully.",
        "400": "Malformed JSON or invalid payload shape.",
        "409": "license_number already exists.",
        "422": "A required field is null or invalid.",
    },
    ("/api/v1/drivers", "get"): {
        "200": "Driver collection returned successfully.",
        "400": "Invalid query parameter values.",
    },
    ("/api/v1/drivers/{driver_id}", "get"): {
        "200": "Driver returned successfully.",
        "404": "driver_id does not exist.",
    },
    ("/api/v1/drivers/{driver_id}", "put"): {
        "200": "Driver updated successfully.",
        "400": "Malformed JSON or empty update payload.",
        "404": "driver_id does not exist.",
        "409": "Updated license_number conflicts with another driver.",
        "422": "A supplied field is null or invalid.",
    },
    ("/api/v1/drivers/{driver_id}", "delete"): {
        "200": "Driver deleted successfully.",
        "404": "driver_id does not exist.",
        "409": "The driver is referenced by a vehicle assignment.",
    },
    ("/api/v1/vehicles", "post"): {
        "201": "Vehicle was created successfully.",
        "400": "Malformed JSON or invalid payload shape.",
        "404": "Referenced vehicle_type_id or vehicle_status_id does not exist.",
        "409": "plate_number already exists.",
    },
    ("/api/v1/vehicles", "get"): {
        "200": "Vehicle collection returned successfully.",
        "400": "Invalid query parameter values.",
    },
    ("/api/v1/vehicles/{vehicle_id}", "get"): {
        "200": "Vehicle returned successfully.",
        "404": "vehicle_id does not exist.",
    },
    ("/api/v1/vehicles/{vehicle_id}", "put"): {
        "200": "Vehicle updated successfully.",
        "400": "Malformed JSON or empty payload.",
        "404": "vehicle_id or referenced foreign key does not exist.",
        "409": "Updated plate_number conflicts with another vehicle.",
    },
    ("/api/v1/vehicles/{vehicle_id}", "delete"): {
        "200": "Vehicle deleted successfully.",
        "404": "vehicle_id does not exist.",
        
        "409": "Deletion is blocked by business rules /foreign key constraints.",
    },
    ("/api/v1/vehicles/{vehicle_id}/current-location", "get"): {
        "200": "Current location returned.",
        "204": "Vehicle exists but has no recorded pings yet.",
        "400": "vehicle_id is not a positive integer.",
        "404": "vehicle_id does not exist.",
    },
    ("/api/v1/vehicle-assignments", "post"): {
        "201": "Vehicle assignment was created successfully.",
        "400": "Malformed JSON or invalid payload shape.",
        "404": "Referenced vehicle_id or driver_id does not exist.",
        "422": "The assignment time interval is invalid.",
    },
    ("/api/v1/vehicle-assignments", "get"): {
        "200": "Vehicle assignment collection returned successfully.",
        "400": "Invalid query parameter values.",
    },
    ("/api/v1/vehicle-assignments/{assignment_id}", "get"): {
        "200": "Vehicle assignment returned successfully.",
        "404": "assignment_id does not exist.",
    },
    ("/api/v1/vehicle-assignments/{assignment_id}", "put"): {
        "200": "Vehicle assignment updated successfully.",
        "400": "Malformed JSON or empty update payload.",
        "404": "assignment_id or a referenced foreign key does not exist.",
        "422": "The resulting assignment interval is invalid.",
    },
    ("/api/v1/vehicle-assignments/{assignment_id}", "delete"): {
        "200": "Vehicle assignment deleted successfully.",
        "404": "assignment_id does not exist.",
    },
    ("/api/v1/location-pings", "post"): {
        "201": "Location ping created successfully.",
        "400": "Malformed geometry or invalid JSON.",
        "404": "vehicle_id does not exist.",
    },
    ("/api/v1/location-pings", "get"): {
        "200": "Ping collection returned.",
        "400": "Invalid query parameter values.",
    },
    ("/api/v1/location-pings/{ping_id}", "get"): {
        "200": "Ping returned successfully.",
        "404": "ping_id does not exist.",
    },
    ("/api/v1/location-pings/{ping_id}", "put"): {
        "200": "Ping updated successfully.",
        "400": "Malformed JSON or empty patch payload.",
        "404": "ping_id or referenced vehicle_id does not exist.",
    },
    ("/api/v1/location-pings/{ping_id}", "delete"): {
        "200": "Ping deleted.",
        "404": "ping_id does not exist.",
    },
    ("/api/v1/vehicles/{vehicle_id}/pings", "get"): {
        "200": "Vehicle pings returned.",
        "400": "Invalid query parameters.",
        "404": "vehicle_id does not exist.",
    },
}


# Trips REST resource: exact documented response contract.
EXPECTED.update({
    ("/api/v1/trips", "post"): {
        "201": "Trip created successfully.",
        "400": "Malformed geometry or invalid JSON.",
        "404": "vehicle_id does not exist.",
    },
    ("/api/v1/trips", "get"): {
        "200": "Trip collection returned.",
        "400": "Invalid query parameter values.",
    },
    ("/api/v1/trips/{trip_id}", "get"): {
        "200": "Trip returned successfully.",
        "404": "trip_id does not exist.",
    },
    ("/api/v1/trips/{trip_id}", "put"): {
        "200": "Trip updated successfully.",
        "400": "Malformed JSON or empty patch payload.",
        "404": "trip_id or referenced vehicle_id does not exist.",
        "422": "Validation failed.",
    },
    ("/api/v1/trips/{trip_id}", "delete"): {
        "200": "Trip deleted.",
        "404": "trip_id does not exist.",
    },
    ("/api/v1/vehicles/{vehicle_id}/trips", "get"): {
        "200": "Vehicle trips returned.",
        "400": "Invalid query parameters.",
        "404": "vehicle_id does not exist.",
    },
})


# Professor's Parking Area rubric (Section 5.3): 10 additional response codes.
EXPECTED.update({
    ("/api/v1/parking-areas", "post"): {
        "201": "Parking area created successfully.",
        "400": "Malformed geometry or invalid JSON.",
    },
    ("/api/v1/parking-areas", "get"): {
        "200": "Parking area collection returned.",
        "400": "Invalid query parameter values.",
    },
    ("/api/v1/parking-areas/{parking_area_id}", "get"): {
        "200": "Parking area returned.",
        "404": "parking_area_id does not exist.",
    },
    ("/api/v1/parking-areas/{parking_area_id}", "put"): {
        "200": "Parking area updated successfully.",
        "400": "Malformed JSON or empty patch payload.",
        "404": "parking_area_id does not exist.",
    },
    ("/api/v1/parking-areas/{parking_area_id}", "delete"): {
        "200": "Parking area deleted.",
        "404": "parking_area_id does not exist.",
    },
})


# Road Segment rubric (Section 5.2): 15 additional response codes.
EXPECTED.update({
    ("/api/v1/road-segments", "post"): {
        "201": "Road segment created successfully.",
        "400": "Malformed geometry or invalid JSON.",
    },
    ("/api/v1/road-segments", "get"): {
        "200": "Road segment collection returned.",
        "400": "Invalid query parameter values.",
    },
    ("/api/v1/road-segments/{road_id}", "get"): {
        "200": "Road segment returned.",
        "404": "road_id does not exist.",
    },
    ("/api/v1/road-segments/{road_id}", "put"): {
        "200": "Road segment updated successfully.",
        "400": "Malformed JSON or empty patch payload.",
        "404": "road_id does not exist.",
    },
    ("/api/v1/road-segments/{road_id}", "delete"): {
        "200": "Road segment deleted.",
        "404": "road_id does not exist.",
    },
    ("/api/v1/road-segments/geojson", "get"): {
        "200": "GeoJSON FeatureCollection returned successfully.",
        "400": "Invalid or inconsistent filter values.",
        "422": "A query parameter fails type or range validation.",
        "500": "The service could not complete the request.",
    },
})


PAGINATION_DEFAULTS = {
    ("/api/v1/drivers", "get"): {"limit": 20, "offset": 0},
    ("/api/v1/vehicles", "get"): {"limit": 20, "offset": 0},
    ("/api/v1/vehicle-assignments", "get"): {"limit": 20, "offset": 0},
    ("/api/v1/parking-areas", "get"): {"limit": 20, "offset": 0},
    ("/api/v1/road-segments", "get"): {"limit": 20, "offset": 0},
    ("/api/v1/road-segments/geojson", "get"): {
        "limit": 15000,
        "offset": 0,
    },
    ("/api/v1/location-pings", "get"): {"limit": 20, "offset": 0},
    ("/api/v1/vehicles/{vehicle_id}/pings", "get"): {
        "limit": 20,
        "offset": 0,
    },
    ("/api/v1/trips", "get"): {"limit": 20, "offset": 0},
    ("/api/v1/vehicles/{vehicle_id}/trips", "get"): {
        "limit": 20,
        "offset": 0,
    },
}


def http(method, url, body=None, params=None, raw=None):
    """Send an HTTP request and return status plus decoded JSON."""
    if params is not None:
        url += "?" + urlencode(params)

    if raw is not None:
        data = raw.encode("utf-8")
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
    else:
        data = None

    headers = {"Content-Type": "application/json"} if data is not None else {}

    req = Request(url, data=data, method=method, headers=headers)

    try:
        with urlopen(req, timeout=15) as response:
            status = response.status
            payload = response.read()
    except HTTPError as error:
        status = error.code
        payload = error.read()

    return status, json.loads(payload) if payload else None


def point(lon=-65.5, lat=18.4):
    return {"type": "Point", "coordinates": [lon, lat]}


class ProfessorGrader(unittest.TestCase):
    """Strict E2E tests against the isolated cartracking_test database."""

    @classmethod
    def setUpClass(cls):
        if os.environ.get("CARTRACKING_E2E_ALLOW_WRITES") != "cartracking_test":
            raise RuntimeError(
                "Refusing writes: set "
                "CARTRACKING_E2E_ALLOW_WRITES=cartracking_test"
            )

        probe = subprocess.run(
            [
                "docker", "compose", "--profile", "test",
                "exec", "-T", "backend-test",
                "printenv", "DB_NAME",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        if probe.returncode != 0 or probe.stdout.strip() != "cartracking_test":
            raise RuntimeError(
                "Unsafe environment: backend-test is not configured "
                "for cartracking_test."
            )

        status, health = http("GET", API + "/health/database")

        if status != 200 or health.get("database") != "cartracking_test":
            raise RuntimeError(
                "Unsafe environment: test API does not report cartracking_test."
            )

        # Verify the database actually used by the connection pool.
        code = (
            "from backend.config.dbconfig import "
            "initialize_connection_pool,get_db_connection,"
            "close_connection_pool;"
            "initialize_connection_pool();"
            "ctx=get_db_connection();"
            "c=ctx.__enter__();"
            "cur=c.cursor();"
            "cur.execute('SELECT current_database()');"
            "print(cur.fetchone()[0]);"
            "cur.close();"
            "ctx.__exit__(None,None,None);"
            "close_connection_pool()"
        )

        actual = subprocess.run(
            [
                "docker", "compose", "--profile", "test",
                "exec", "-T", "backend-test",
                "python", "-c", code,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if (
            actual.returncode != 0
            or actual.stdout.strip() != "cartracking_test"
        ):
            raise RuntimeError(
                "Unsafe environment: actual database connection "
                "is not cartracking_test."
            )

        for url in (D, V, A, P, PA, T, RS):
            status, response = http("GET", url, params={"limit": 1})
            if status != 200 or not response.get("items"):
                raise RuntimeError("Populated test database required: " + url)

        cls.seed_vehicle = http(
            "GET", V, params={"limit": 1}
        )[1]["items"][0]

        cls.seed_driver = http(
            "GET", D, params={"limit": 1}
        )[1]["items"][0]

        cls.seed_trip = http(
            "GET", T, params={"limit": 1}
        )[1]["items"][0]

        cls.resources = []

        cls.initial_parking_count = http(
            "GET", PA, params={"limit": 0}
        )[1]["count"]

        cls.initial_trip_count = http(
            "GET", T, params={"limit": 0}
        )[1]["count"]

        cls.initial_road_count = http(
            "GET", RS, params={"limit": 0}
        )[1]["count"]

    @classmethod
    def tearDownClass(cls):
        cls.cleanup()

    @classmethod
    def cleanup(cls):
        """Remove temporary resources in reverse creation order."""
        for url in reversed(cls.resources):
            try:
                status, _ = http("DELETE", url)
                if status not in (200, 404):
                    print("CLEANUP WARNING:", status, url)
            except Exception as error:
                print("CLEANUP WARNING:", url, str(error))

        cls.resources.clear()

    def call(
        self, method, url, expected,
        body=None, params=None, detail=None, raw=None
    ):
        status, payload = http(method, url, body, params, raw)

        self.assertEqual(
            status, expected,
            f"{method} {url}: expected {expected}, "
            f"received {status}, body={payload}"
        )

        if detail is not None:
            self.assertEqual(payload, {"detail": detail})

        return payload

    def new_driver(self):
        license_no = "GRD-" + uuid.uuid4().hex[:14]

        record = self.call("POST", D, 201, {
            "first_name": "Professor",
            "last_name": "Grader",
            "license_number": license_no,
            "hired_at": "2032-05-20T08:00:00-04:00",
        })

        self.resources.append(f"{D}/{record['driver_id']}")
        return record

    def new_vehicle(self):
        plate = "GRD-" + uuid.uuid4().hex[:12]

        record = self.call("POST", V, 201, {
            "vehicle_type_id": self.seed_vehicle["vehicle_type_id"],
            "vehicle_status_id": self.seed_vehicle["vehicle_status_id"],
            "plate_number": plate,
            "make": "Grader",
            "model": "E2E",
            "year": 2024,
        })

        self.resources.append(f"{V}/{record['vehicle_id']}")
        return record

    def new_assignment(self, vehicle_id=None, driver_id=None):
        record = self.call("POST", A, 201, {
            "vehicle_id": vehicle_id or self.seed_vehicle["vehicle_id"],
            "driver_id": driver_id or self.seed_driver["driver_id"],
            "assigned_from": START,
            "assigned_to": None,
        })

        self.resources.append(f"{A}/{record['assignment_id']}")
        return record

    def new_ping(self, vehicle_id=None, ts=START, geom=None):
        record = self.call("POST", P, 201, {
            "vehicle_id": vehicle_id or self.seed_vehicle["vehicle_id"],
            "ts": ts,
            "geom": geom if geom is not None else point(),
            "speed_kph": 42.8,
            "heading_deg": 185.4,
        })

        self.resources.append(f"{P}/{record['ping_id']}")
        return record

    def new_trip(
        self, vehicle_id=None, start_ts=START, end_ts=END,
        start_geom=None, end_geom=None, distance_km=6.7
    ):
        """Create a temporary Trip and register it for reverse-order cleanup."""
        payload = {
            "vehicle_id": vehicle_id or self.seed_vehicle["vehicle_id"],
            "start_ts": start_ts,
            "end_ts": end_ts,
            "start_geom": start_geom if start_geom is not None else point(-65.51, 18.41),
            "end_geom": end_geom if end_geom is not None else point(-65.49, 18.42),
            "distance_km": distance_km,
        }
        record = self.call("POST", T, 201, payload)
        self.resources.append(f"{T}/{record['trip_id']}")
        return record

    @staticmethod
    def parking_polygon(lon=100.0, lat=20.0, size=0.01):
        """Small closed square; deliberately far from Puerto Rico seed data."""
        return {"type": "Polygon", "coordinates": [[
            [lon, lat], [lon + size, lat],
            [lon + size, lat + size], [lon, lat + size], [lon, lat],
        ]]}

    def new_parking(self, name=None, capacity=30, geom=None, omit_capacity=False):
        """Create an isolated record with guaranteed unittest cleanup."""
        payload = {
            "name": name or ("Professor Parking " + uuid.uuid4().hex),
            "geom": geom if geom is not None else self.parking_polygon(),
        }
        if not omit_capacity:
            payload["capacity"] = capacity
        created = self.call("POST", PA, 201, payload)
        url = f"{PA}/{created['parking_area_id']}"
        self.addCleanup(self.remove_parking, url)
        return created

    def remove_parking(self, url):
        """Fail the test if a temporary parking area cannot be removed."""
        status, payload = http("DELETE", url)
        self.assertIn(status, (200, 404), f"Cleanup failed {url}: {payload}")

    
    def assert_polygon_equal(self, actual, expected):
        """
        Compare GeoJSON Polygon coordinates numerically,
        allowing tiny floating-point representation differences.

        Still checks:
        - Geometry type
        - Number of rings
        - Number of positions
        - Longitude and latitude values
        """
        self.assertEqual(actual["type"], "Polygon")
        self.assertEqual(expected["type"], "Polygon")

        actual_rings = actual["coordinates"]
        expected_rings = expected["coordinates"]

        self.assertEqual(len(actual_rings), len(expected_rings))

        for actual_ring, expected_ring in zip(
            actual_rings, expected_rings
        ):
            self.assertEqual(len(actual_ring), len(expected_ring))

            for actual_point, expected_point in zip(
                actual_ring, expected_ring
            ):
                self.assertEqual(len(actual_point), 2)
                self.assertEqual(len(expected_point), 2)

                for actual_value, expected_value in zip(
                    actual_point, expected_point
                ):
                    self.assertAlmostEqual(
                        actual_value,
                        expected_value,
                        places=10,
                    )

    # -------------------------------------------------------
    # Rubric and response structures
    # -------------------------------------------------------

    def test_01_openapi_exact_rubric(self):
        spec = self.call("GET", ROOT + "/openapi.json", 200)

        self.assertEqual(sum(map(len, EXPECTED.values())), 106)

        for (path, method), expected in EXPECTED.items():
            with self.subTest(path=path, method=method):
                actual = {
                    code: item["description"]
                    for code, item in
                    spec["paths"][path][method]["responses"].items()
                }

                self.assertEqual(actual, expected)

        pagination_parameter_count = 0
        for (path, method), defaults in PAGINATION_DEFAULTS.items():
            with self.subTest(path=path, method=method, contract="pagination"):
                parameters = {
                    parameter["name"]: parameter
                    for parameter in spec["paths"][path][method]["parameters"]
                }

                for name, default in defaults.items():
                    parameter = parameters[name]
                    schema = parameter["schema"]

                    self.assertEqual(parameter["in"], "query")
                    self.assertFalse(parameter["required"])
                    self.assertEqual(schema["type"], "integer")
                    self.assertEqual(schema["minimum"], 0)
                    self.assertEqual(schema["default"], default)
                    self.assertIsInstance(schema["default"], int)
                    self.assertNotIn("maximum", schema)
                    pagination_parameter_count += 1

        self.assertEqual(pagination_parameter_count, 20)

    def test_02_all_list_shapes_and_zero_limit(self):
        for url in (D, V, A, P, PA, T, RS):
            with self.subTest(url=url):
                response = self.call(
                    "GET", url, 200,
                    params={"limit": 0, "offset": 0}
                )

                self.assertEqual(
                    set(response),
                    {"items", "limit", "offset", "count"}
                )

                self.assertEqual(response["items"], [])
                self.assertGreater(response["count"], 0)
                self.assertEqual(response["limit"], 0)
                self.assertEqual(response["offset"], 0)

                self.call(
                    "GET", url, 400,
                    params={"limit": -1},
                    detail="Invalid query parameter values."
                )

                self.call(
                    "GET", url, 400,
                    params={"offset": "bad"},
                    detail="Invalid query parameter values."
                )

    # -------------------------------------------------------
    # Driver tests
    # -------------------------------------------------------

    def test_03_driver_lifecycle_and_filters(self):
        driver = self.new_driver()
        driver_id = driver["driver_id"]

        self.assertEqual(
            set(driver),
            {
                "driver_id", "first_name", "last_name",
                "license_number", "hired_at"
            }
        )
        self.assertEqual(driver["hired_at"], "2032-05-20T12:00:00Z")

        self.assertEqual(
            self.call("GET", f"{D}/{driver_id}", 200),
            driver
        )

        filtered = self.call(
            "GET", D, 200,
            params={"license_number": driver["license_number"]}
        )

        self.assertIn(
            driver_id,
            [x["driver_id"] for x in filtered["items"]]
        )

        changed = self.call(
            "PUT", f"{D}/{driver_id}", 200,
            {"first_name": "Updated"}
        )

        self.assertEqual(changed["first_name"], "Updated")

        changed_time = self.call(
            "PUT", f"{D}/{driver_id}", 200,
            {"hired_at": "2032-05-21T08:00:00-04:00"}
        )
        self.assertEqual(changed_time["hired_at"], "2032-05-21T12:00:00Z")

        self.assertEqual(
            self.call("GET", f"{D}/{driver_id}", 200)["first_name"],
            "Updated"
        )

    def test_04_driver_conflicts_and_atomicity(self):
        first = self.new_driver()
        second = self.new_driver()

        self.call(
            "POST", D, 409,
            {
                "first_name": "Duplicate",
                "last_name": "License",
                "license_number": first["license_number"],
                "hired_at": START,
            },
            detail="license_number already exists."
        )

        url = f"{D}/{second['driver_id']}"
        before = self.call("GET", url, 200)

        self.call(
            "PUT", url, 409,
            {"license_number": first["license_number"]},
            detail="Updated license_number conflicts with another driver."
        )

        self.assertEqual(self.call("GET", url, 200), before)

        self.call(
            "PUT", url, 400, {},
            detail="Malformed JSON or empty update payload."
        )

        self.call(
            "PUT", url, 422,
            {"first_name": None},
            detail="A supplied field is null or invalid."
        )

        self.assertEqual(self.call("GET", url, 200), before)

        self.call(
            "PUT", url, 422,
            {"hired_at": "2032-05-20T12:00:00"},
            detail="A supplied field is null or invalid."
        )

        self.assertEqual(self.call("GET", url, 200), before)

    def test_05_driver_invalid_inputs(self):
        self.call(
            "GET", f"{D}/{MISSING}", 404,
            detail="driver_id does not exist."
        )

        self.call(
            "DELETE", f"{D}/{MISSING}", 404,
            detail="driver_id does not exist."
        )

        self.call(
            "POST", D, 400,
            raw="{broken",
            detail="Malformed JSON or invalid payload shape."
        )

        self.call(
            "POST", D, 422,
            {"first_name": "A", "last_name": "B"},
            detail="A required field is null or invalid."
        )

        self.call(
            "POST", D, 422,
            {
                "first_name": "A",
                "last_name": "B",
                "license_number": "NO-TZ-" + uuid.uuid4().hex[:12],
                "hired_at": "2032-05-20T12:00:00",
            },
            detail="A required field is null or invalid."
        )

    # -------------------------------------------------------
    # Vehicle tests
    # -------------------------------------------------------

    def test_06_vehicle_lifecycle_and_uniqueness(self):
        vehicle = self.new_vehicle()
        vehicle_id = vehicle["vehicle_id"]

        self.assertEqual(
            self.call("GET", f"{V}/{vehicle_id}", 200),
            vehicle
        )

        changed = self.call(
            "PUT", f"{V}/{vehicle_id}", 200,
            {"make": "UpdatedMake"}
        )

        self.assertEqual(changed["make"], "UpdatedMake")

        self.assertEqual(
            self.call("GET", f"{V}/{vehicle_id}", 200)["make"],
            "UpdatedMake"
        )

        self.call(
            "POST", V, 409,
            {
                "vehicle_type_id": vehicle["vehicle_type_id"],
                "vehicle_status_id": vehicle["vehicle_status_id"],
                "plate_number": vehicle["plate_number"],
                "make": "Duplicate",
                "model": "Test",
                "year": 2024,
            },
            detail="plate_number already exists."
        )

    def test_07_vehicle_invalid_updates_are_atomic(self):
        vehicle = self.new_vehicle()
        url = f"{V}/{vehicle['vehicle_id']}"
        before = self.call("GET", url, 200)

        self.call(
            "PUT", url, 400, {},
            detail="Malformed JSON or empty payload."
        )

        self.call(
            "PUT", url, 404,
            {"vehicle_type_id": MISSING},
            detail="vehicle_id or referenced foreign key does not exist."
        )

        self.assertEqual(self.call("GET", url, 200), before)

        self.call(
            "GET", f"{V}/{MISSING}", 404,
            detail="vehicle_id does not exist."
        )

    # -------------------------------------------------------
    # Vehicle Assignment tests
    # -------------------------------------------------------

    def test_08_assignment_lifecycle_and_interval(self):
        assignment = self.new_assignment()
        url = f"{A}/{assignment['assignment_id']}"

        self.assertIsNone(assignment["assigned_to"])
        self.assertEqual(self.call("GET", url, 200), assignment)

        closed = self.call(
            "PUT", url, 200,
            {"assigned_to": END}
        )

        self.assertEqual(closed["assigned_to"], END)

        self.call(
            "PUT", url, 422,
            {"assigned_to": START},
            detail="The resulting assignment interval is invalid."
        )

        self.assertEqual(self.call("GET", url, 200), closed)

        reopened = self.call(
            "PUT", url, 200,
            {"assigned_to": None}
        )

        self.assertIsNone(reopened["assigned_to"])

        matches = self.call(
            "GET", A, 200,
            params={"active": "true", "limit": 1000}
        )

        self.assertIn(
            assignment["assignment_id"],
            [x["assignment_id"] for x in matches["items"]]
        )

    def test_09_assignment_invalid_inputs(self):
        self.call(
            "POST", A, 404,
            {
                "vehicle_id": MISSING,
                "driver_id": self.seed_driver["driver_id"],
                "assigned_from": START,
                "assigned_to": None,
            },
            detail="Referenced vehicle_id or driver_id does not exist."
        )

        self.call(
            "POST", A, 422,
            {
                "vehicle_id": self.seed_vehicle["vehicle_id"],
                "driver_id": self.seed_driver["driver_id"],
                "assigned_from": START,
                "assigned_to": START,
            },
            detail="The assignment time interval is invalid."
        )

        self.call(
            "GET", A, 400,
            params={"active": "perhaps"},
            detail="Invalid query parameter values."
        )

        self.call(
            "GET", f"{A}/{MISSING}", 404,
            detail="assignment_id does not exist."
        )

    # -------------------------------------------------------
    # Location Ping tests
    # -------------------------------------------------------

    def test_10_ping_crud_geojson_and_persistence(self):
        ping = self.new_ping(ts="2032-05-20T08:00:00-04:00")
        url = f"{P}/{ping['ping_id']}"

        self.assertEqual(
            set(ping),
            {
                "ping_id", "vehicle_id", "ts",
                "geom", "speed_kph", "heading_deg"
            }
        )

        self.assertEqual(ping["geom"], point())
        self.assertEqual(ping["ts"], START)
        self.assertEqual(self.call("GET", url, 200), ping)

        updated = self.call(
            "PUT", url, 200,
            {
                "ts": "2032-05-20T09:00:00-04:00",
                "speed_kph": 0,
                "heading_deg": 0,
            }
        )

        self.assertEqual(updated["ts"], END)
        self.assertEqual(updated["speed_kph"], 0)
        self.assertEqual(updated["heading_deg"], 0)
        self.assertEqual(self.call("GET", url, 200), updated)

    def test_11_ping_invalid_payload_matrix(self):
        template = {
            "vehicle_id": self.seed_vehicle["vehicle_id"],
            "ts": START,
            "geom": point(),
            "speed_kph": 1,
            "heading_deg": 90,
        }

        invalid = [
            {**template, "geom": point(181, 18)},
            {**template, "geom": point(-65, 91)},
            {
                **template,
                "geom": {
                    "type": "LineString",
                    "coordinates": [-65, 18]
                }
            },
            {
                **template,
                "geom": {**point(), "altitude": 100}
            },
            {**template, "speeed_kph": 20},
            {**template, "speed_kph": -1},
            {**template, "heading_deg": 360},
            {**template, "heading_deg": -0.1},
            {**template, "ts": "not-a-date"},
            {**template, "ts": "2032-05-20T12:00:00"},
            {**template, "vehicle_id": 0},
        ]

        for payload in invalid:
            with self.subTest(payload=payload):
                self.call(
                    "POST", P, 400, payload,
                    detail="Malformed geometry or invalid JSON."
                )

        self.call(
            "POST", P, 404,
            {**template, "vehicle_id": MISSING},
            detail="vehicle_id does not exist."
        )

    def test_12_ping_invalid_put_no_mutation(self):
        ping = self.new_ping()
        url = f"{P}/{ping['ping_id']}"

        invalid_updates = [
            {},
            {"geom": None},
            {"heading_deg": 360},
            {"vehicle_id": None},
            {"ts": "2032-05-20T12:00:00"},
            {"unknown": 5},
        ]

        for changes in invalid_updates:
            with self.subTest(changes=changes):
                self.call(
                    "PUT", url, 400, changes,
                    detail="Malformed JSON or empty patch payload."
                )

                self.assertEqual(
                    self.call("GET", url, 200),
                    ping
                )

        self.call(
            "PUT", url, 404,
            {"vehicle_id": MISSING},
            detail="ping_id or referenced vehicle_id does not exist."
        )

        self.assertEqual(self.call("GET", url, 200), ping)

    def test_13_spatial_temporal_combined_filters(self):
        vehicle = self.new_vehicle()
        vehicle_id = vehicle["vehicle_id"]

        p1 = self.new_ping(
            vehicle_id, START, point(-65.50, 18.40)
        )

        p2 = self.new_ping(
            vehicle_id, END, point(-65.45, 18.42)
        )

        p3 = self.new_ping(
            vehicle_id, END, point(-65.0, 18.42)
        )

        params = {
            "vehicle_id": vehicle_id,
            "from_ts": START,
            "to_ts": END,
            "bbox": "-65.6,18.3,-65.4,18.5",
            "limit": 10,
        }

        result = self.call("GET", P, 200, params=params)

        self.assertEqual(result["count"], 2)

        self.assertEqual(
            {x["ping_id"] for x in result["items"]},
            {p1["ping_id"], p2["ping_id"]}
        )

        self.assertNotIn(
            p3["ping_id"],
            {x["ping_id"] for x in result["items"]}
        )

        offset_result = self.call(
            "GET", P, 200,
            params={
                **params,
                "from_ts": "2032-05-20T08:00:00-04:00",
                "to_ts": "2032-05-20T09:00:00-04:00",
            }
        )
        self.assertEqual(
            {x["ping_id"] for x in offset_result["items"]},
            {p1["ping_id"], p2["ping_id"]}
        )

        self.call(
            "GET", P, 400,
            params={"from_ts": "2032-05-20T12:00:00"},
            detail="Invalid query parameter values."
        )

        excluded = self.call(
            "GET", P, 200,
            params={
                **params,
                "bbox": "-66,17,-65.9,17.1"
            }
        )

        self.assertEqual(excluded["items"], [])
        self.assertEqual(excluded["count"], 0)

    def test_14_vehicle_ping_history_order(self):
        vehicle = self.new_vehicle()
        vehicle_id = vehicle["vehicle_id"]

        later = self.new_ping(vehicle_id, END)
        earlier = self.new_ping(vehicle_id, START)

        url = f"{V}/{vehicle_id}/pings"

        first_page = self.call(
            "GET", url, 200,
            params={"limit": 1, "offset": 0}
        )

        self.assertEqual(first_page["count"], 2)
        self.assertEqual(
            first_page["items"][0]["ping_id"],
            earlier["ping_id"]
        )

        self.assertNotIn("vehicle_id", first_page["items"][0])

        second_page = self.call(
            "GET", url, 200,
            params={"limit": 1, "offset": 1}
        )

        self.assertEqual(
            second_page["items"][0]["ping_id"],
            later["ping_id"]
        )

        self.call(
            "GET", url, 400,
            params={"limit": -1},
            detail="Invalid query parameters."
        )

        self.call(
            "GET", url, 400,
            params={"from_ts": "2032-05-20T12:00:00"},
            detail="Invalid query parameters."
        )

        self.call(
            "GET", f"{V}/{MISSING}/pings", 404,
            detail="vehicle_id does not exist."
        )

    def test_15_current_location_latest_timestamp(self):
        vehicle = self.new_vehicle()
        vehicle_id = vehicle["vehicle_id"]

        url = f"{V}/{vehicle_id}/current-location"

        self.assertIsNone(self.call("GET", url, 204))

        # Insert newer ping first.
        self.new_ping(
            vehicle_id, END, point(-65.45, 18.45)
        )

        # Insert older ping afterward.
        self.new_ping(
            vehicle_id, START, point(-65.50, 18.40)
        )

        result = self.call("GET", url, 200)

        self.assertEqual(result["vehicle_id"], vehicle_id)
        self.assertEqual(
            result["last_geom"],
            point(-65.45, 18.45)
        )
        self.assertEqual(result["last_ts"], END)

    # -------------------------------------------------------
    # Cross-resource database integrity
    # -------------------------------------------------------

    def test_16_foreign_key_deletion_protection(self):
        driver = self.new_driver()
        vehicle = self.new_vehicle()

        assignment = self.new_assignment(
            vehicle["vehicle_id"],
            driver["driver_id"]
        )

        self.call(
            "DELETE", f"{D}/{driver['driver_id']}", 409,
            detail="The driver is referenced by a vehicle assignment."
        )

        self.call(
            "DELETE", f"{V}/{vehicle['vehicle_id']}", 409,
            detail="Deletion is blocked by business rules /foreign key constraints."
        )

        self.call(
            "DELETE", f"{A}/{assignment['assignment_id']}", 200
        )

        self.call(
            "DELETE", f"{D}/{driver['driver_id']}", 200
        )

        self.call(
            "DELETE", f"{V}/{vehicle['vehicle_id']}", 200
        )

    def test_17_ping_foreign_key_protection(self):
        vehicle = self.new_vehicle()
        ping = self.new_ping(vehicle["vehicle_id"])

        self.call(
            "DELETE", f"{V}/{vehicle['vehicle_id']}", 409,
            detail="Deletion is blocked by business rules /foreign key constraints."
        )

        self.call(
            "DELETE", f"{P}/{ping['ping_id']}", 200
        )

        self.call(
            "DELETE", f"{V}/{vehicle['vehicle_id']}", 200
        )

    def test_18_exact_delete_response_bodies(self):
        driver = self.new_driver()
        vehicle = self.new_vehicle()
        assignment = self.new_assignment()
        ping = self.new_ping()

        cases = [
            (
                f"{D}/{driver['driver_id']}",
                "driver_id",
                driver["driver_id"],
                "Driver deleted successfully."
            ),
            (
                f"{V}/{vehicle['vehicle_id']}",
                "vehicle_id",
                vehicle["vehicle_id"],
                "Vehicle deleted successfully."
            ),
            (
                f"{A}/{assignment['assignment_id']}",
                "assignment_id",
                assignment["assignment_id"],
                "Vehicle assignment deleted successfully."
            ),
            (
                f"{P}/{ping['ping_id']}",
                "ping_id",
                ping["ping_id"],
                "Location ping deleted successfully."
            ),
        ]

        for url, id_field, id_value, message in cases:
            with self.subTest(url=url):
                body = self.call("DELETE", url, 200)

                self.assertEqual(
                    body,
                    {
                        "message": message,
                        id_field: id_value
                    }
                )

                status, _ = http("GET", url)
                self.assertEqual(status, 404)

    def test_19_invalid_query_and_path_boundaries(self):
        for url in (D, V, A, P, PA, T, RS):
            with self.subTest(url=url):
                self.call(
                    "GET", url, 400,
                    params={"limit": "-1"},
                    detail="Invalid query parameter values."
                )

        for url, message in [
            (P, "ping_id must be a positive integer."),
            (A, "assignment_id must be a positive integer."),
            (RS, "road_id must be a positive integer."),
        ]:
            with self.subTest(url=url):
                self.call(
                    "GET", url + "/0", 400,
                    detail=message
                )

                self.call(
                    "GET", url + "/abc", 400,
                    detail=message
                )

    def test_20_cleanup_and_preservation(self):
        self.cleanup()

        for url in (D, V, A, P, PA, T, RS):
            response = self.call(
                "GET", url, 200,
                params={"limit": 0}
            )

            self.assertGreater(response["count"], 0)


    # -------------------------------------------------------
    # Parking Area: professor-style, adversarial end-to-end cases
    # -------------------------------------------------------

    def test_21_parking_create_get_exact_contract(self):
        item = self.new_parking()
        url = f"{PA}/{item['parking_area_id']}"
        self.assertEqual(set(item), {
            "parking_area_id", "name", "capacity", "geom", "created_at"
        })
        self.assertIsInstance(item["parking_area_id"], int)
        self.assertGreater(item["parking_area_id"], 0)
        self.assertEqual(item["capacity"], 30)
        self.assertEqual(item["geom"], self.parking_polygon())
        self.assertTrue(item["created_at"].endswith("Z"))
        self.assertEqual(self.call("GET", url, 200), item)

    def test_22_parking_capacity_omitted_null_and_zero(self):
        for kind in ("omitted", "null", "zero"):
            with self.subTest(kind=kind):
                item = self.new_parking(
                    name="Capacity " + uuid.uuid4().hex,
                    omit_capacity=(kind == "omitted"),
                    capacity=None if kind == "null" else 0,
                )
                self.assertEqual(
                    item["capacity"], 0 if kind == "zero" else None
                )
                fetched = self.call("GET", f"{PA}/{item['parking_area_id']}", 200)
                self.assertEqual(fetched["capacity"], item["capacity"])

    def test_23_parking_create_invalid_payload_matrix(self):
        polygon = self.parking_polygon()
        base = {"name": "Rejected", "capacity": 10, "geom": polygon}
        cases = {
            "missing name": {"capacity": 10, "geom": polygon},
            "null name": {**base, "name": None},
            "empty name": {**base, "name": ""},
            "whitespace name": {**base, "name": "  "},
            "negative capacity": {**base, "capacity": -1},
            "fractional capacity": {**base, "capacity": 1.5},
            "missing geometry": {"name": "Rejected", "capacity": 10},
            "null geometry": {**base, "geom": None},
            "point instead polygon": {**base, "geom": point()},
            "empty coordinates": {**base, "geom": {"type": "Polygon", "coordinates": []}},
            "unclosed ring": {**base, "geom": {"type": "Polygon", "coordinates": [[
                [100, 20], [100.01, 20], [100.01, 20.01], [100, 20.01]
            ]]}},
            "too few ring positions": {**base, "geom": {"type": "Polygon", "coordinates": [[
                [100, 20], [100.01, 20], [100, 20],
            ]]}},
            "longitude out of range": {**base, "geom": self.parking_polygon(181, 20)},
            "latitude out of range": {**base, "geom": self.parking_polygon(100, 91)},
            "three dimensional coordinate": {**base, "geom": {"type": "Polygon", "coordinates": [[
                [100, 20, 2], [100.01, 20], [100.01, 20.01],
                [100, 20.01], [100, 20, 2]
            ]]}},
            "unexpected top-level field": {**base, "admin": True},
            "unexpected nested field": {**base, "geom": {**polygon, "crs": "wrong"}},
        }
        before = self.call("GET", PA, 200, params={"limit": 0})["count"]
        for label, body in cases.items():
            with self.subTest(label=label):
                self.call("POST", PA, 400, body,
                          detail="Malformed geometry or invalid JSON.")
        self.call("POST", PA, 400, raw="{bad JSON",
                  detail="Malformed geometry or invalid JSON.")
        after = self.call("GET", PA, 200, params={"limit": 0})["count"]
        self.assertEqual(after, before, "Invalid POST changed parking_area count")

    def test_24_parking_invalid_topology_rejected(self):
        # Closed rings may still be invalid (self intersections or holes outside shell).
        invalids = {
            "bow tie": {"type": "Polygon", "coordinates": [[
                [100, 20], [100.02, 20.02], [100, 20.02],
                [100.02, 20], [100, 20]
            ]]},
            "collinear ring": {"type": "Polygon", "coordinates": [[
                [100, 20], [100.01, 20], [100.02, 20],
                [100.03, 20], [100, 20]
            ]]},
            "hole outside shell": {"type": "Polygon", "coordinates": [
                self.parking_polygon()["coordinates"][0],
                self.parking_polygon(101, 21)["coordinates"][0],
            ]},
        }
        for label, geom in invalids.items():
            with self.subTest(topology=label):
                self.call("POST", PA, 400, {
                    "name": "Bad Topology", "capacity": 1, "geom": geom
                }, detail="Malformed geometry or invalid JSON.")

    def test_25_parking_partial_full_updates_and_timestamp(self):
        item = self.new_parking()
        url = f"{PA}/{item['parking_area_id']}"
        partial = self.call("PUT", url, 200, {"capacity": 0})
        self.assertEqual(partial["capacity"], 0)
        self.assertEqual(partial["name"], item["name"])
        self.assertEqual(partial["geom"], item["geom"])
        self.assertEqual(partial["created_at"], item["created_at"])
        new_geom = self.parking_polygon(102, 22)
        new_name = "Updated " + uuid.uuid4().hex
        full = self.call("PUT", url, 200, {
            "name": new_name, "capacity": 77, "geom": new_geom
        })
        self.assertEqual(full["name"], new_name)
        self.assertEqual(full["capacity"], 77)
        self.assertEqual(full["geom"], new_geom)
        self.assertEqual(full["created_at"], item["created_at"])
        self.assertEqual(self.call("GET", url, 200), full)
        cleared = self.call("PUT", url, 200, {"capacity": None})
        self.assertIsNone(cleared["capacity"])
        self.assertEqual(cleared["geom"], new_geom)

    def test_26_parking_update_invalid_atomicity(self):
        item = self.new_parking()
        url = f"{PA}/{item['parking_area_id']}"
        bowtie = {"type": "Polygon", "coordinates": [[
            [100, 20], [100.02, 20.02], [100, 20.02],
            [100.02, 20], [100, 20]
        ]]}
        invalids = [
            {}, {"name": None}, {"name": "  "},
            {"capacity": -1}, {"capacity": 2.3},
            {"geom": None}, {"geom": bowtie},
            {"name": "DO NOT SAVE", "capacity": 90, "geom": bowtie},
            {"invalid_field": 1},
        ]
        for change in invalids:
            with self.subTest(change=change):
                self.call("PUT", url, 400, change,
                          detail="Malformed JSON or empty patch payload.")
                self.assertEqual(self.call("GET", url, 200), item)
        self.call("PUT", url, 400, raw="{not JSON",
                  detail="Malformed JSON or empty patch payload.")
        self.assertEqual(self.call("GET", url, 200), item)

    def test_27_parking_name_filter_case_and_substring(self):
        marker = "ProfessorPark" + uuid.uuid4().hex[:12]
        created = self.new_parking(name="  " + marker + " Alpha  ")
        self.assertEqual(created["name"], marker + " Alpha")
        for substring in (marker, marker.lower(), "ALPHA"):
            with self.subTest(substring=substring):
                page = self.call("GET", PA, 200, params={
                    "name": substring, "limit": 20, "offset": 0
                })
                self.assertEqual(page["count"], 1)
                self.assertEqual(page["items"][0]["parking_area_id"],
                                 created["parking_area_id"])
                self.assertNotIn("geom", page["items"][0])

    def test_28_parking_combined_filters_are_intersection(self):
        token = "FilterTest" + uuid.uuid4().hex[:12]
        a = self.new_parking(name=token + " A", geom=self.parking_polygon(100, 20))
        b = self.new_parking(name=token + " B", geom=self.parking_polygon(102, 22))
        c = self.new_parking(name="Other " + uuid.uuid4().hex,
                             geom=self.parking_polygon(100, 20.03))
        match_bbox = "99.99,19.99,100.02,20.02"
        named = self.call("GET", PA, 200, params={"name": token, "limit": 20})
        self.assertEqual(named["count"], 2)
        self.assertEqual({x["parking_area_id"] for x in named["items"]},
                         {a["parking_area_id"], b["parking_area_id"]})
        boxed = self.call("GET", PA, 200, params={"bbox": match_bbox, "limit": 1000})
        self.assertIn(a["parking_area_id"], {x["parking_area_id"] for x in boxed["items"]})
        combined = self.call("GET", PA, 200, params={
            "name": token, "bbox": match_bbox, "limit": 20
        })
        self.assertEqual(combined["count"], 1)
        self.assertEqual(combined["items"][0]["parking_area_id"],
                         a["parking_area_id"])
        excluded = self.call("GET", PA, 200, params={
            "name": token, "bbox": "-100,1,-99,2", "limit": 20
        })
        self.assertEqual(excluded["count"], 0)
        self.assertEqual(excluded["items"], [])

    def test_29_parking_bbox_boundary_intersection(self):
        marker = "Edge" + uuid.uuid4().hex[:12]
        item = self.new_parking(name=marker, geom=self.parking_polygon(100, 20))
        touching = self.call("GET", PA, 200, params={
            "name": marker, "bbox": "100.01,20.001,100.02,20.009"
        })
        self.assertEqual(touching["count"], 1,
                         "ST_Intersects should include touching boundaries")
        self.assertEqual(touching["items"][0]["parking_area_id"],
                         item["parking_area_id"])
        not_touching = self.call("GET", PA, 200, params={
            "name": marker, "bbox": "100.011,20.001,100.02,20.009"
        })
        self.assertEqual(not_touching["count"], 0)

    def test_30_parking_invalid_query_matrix(self):
        params_cases = [
            {"limit": -1}, {"offset": -1},
            {"limit": "abc"}, {"offset": "2.5"},
            {"limit": "1e2"}, {"limit": "-0"},
            {"bbox": ""}, {"bbox": "100,20,101"},
            {"bbox": "x,20,101,21"}, {"bbox": "nan,20,101,21"},
            {"bbox": "100,20,inf,21"}, {"bbox": "101,20,100,21"},
            {"bbox": "100,21,101,20"},
            {"bbox": "100,20,100,21"},
            {"bbox": "180.1,20,180.5,21"},
            {"bbox": "100,-91,101,-90"},
        ]
        for params in params_cases:
            with self.subTest(params=params):
                self.call("GET", PA, 400, params=params,
                          detail="Invalid query parameter values.")

    def test_31_parking_pagination_consistency_and_zero_limit(self):
        marker = "Page" + uuid.uuid4().hex[:12]
        items = [self.new_parking(name=marker + f" {i}") for i in range(3)]
        expected = sorted(x["parking_area_id"] for x in items)
        pages = [self.call("GET", PA, 200, params={
            "name": marker, "limit": 1, "offset": i
        }) for i in range(4)]
        self.assertEqual([p["count"] for p in pages], [3] * 4)
        self.assertEqual([p["items"][0]["parking_area_id"] for p in pages[:3]], expected)
        self.assertEqual(pages[3]["items"], [])
        zero = self.call("GET", PA, 200, params={"name": marker, "limit": 0})
        self.assertEqual(zero["items"], [])
        self.assertEqual(zero["count"], 3)
        self.assertEqual(zero["limit"], 0)

    def test_32_parking_ids_nonexistent_and_delete_contract(self):
        for bad_id in ("0", "-1", "abc", "1.3"):
            for method in ("GET", "DELETE"):
                with self.subTest(method=method, id=bad_id):
                    self.call(method, f"{PA}/{bad_id}", 400,
                              detail="parking_area_id must be a positive integer.")
        for method, body in (("GET", None), ("PUT", {"capacity": 1}),
                             ("DELETE", None)):
            with self.subTest(method=method):
                self.call(method, f"{PA}/{MISSING}", 404, body,
                          detail="parking_area_id does not exist.")
        item = self.new_parking()
        url = f"{PA}/{item['parking_area_id']}"
        deleted = self.call("DELETE", url, 200)
        self.assertEqual(deleted, {
            "message": "Parking area deleted successfully.",
            "parking_area_id": item["parking_area_id"],
        })
        self.call("GET", url, 404, detail="parking_area_id does not exist.")
        self.call("DELETE", url, 404, detail="parking_area_id does not exist.")

    def test_33_parking_geometry_with_valid_hole_roundtrips(self):
        # A valid exterior and inner ring, both closed and strictly inside.
        exterior = self.parking_polygon(100, 20, 0.1)["coordinates"][0]
        hole = list(reversed(self.parking_polygon(100.02, 20.02, 0.02)["coordinates"][0]))
        geom = {"type": "Polygon", "coordinates": [exterior, hole]}
        item = self.new_parking(geom=geom)
        self.assert_polygon_equal(item["geom"], geom)
        self.assert_polygon_equal(
            self.call(
                "GET",
                f"{PA}/{item['parking_area_id']}",
                200,
            )["geom"],
            geom,
        )

    def test_34_parking_sql_injection_like_name_is_data(self):
        # This should be treated as a name substring, never as SQL syntax.
        suspicious = "' OR 1=1 -- " + uuid.uuid4().hex
        result = self.call("GET", PA, 200, params={"name": suspicious, "limit": 1})
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["items"], [])
        self.assertGreater(self.call("GET", PA, 200, params={"limit": 0})["count"], 0)

    def test_35_parking_seed_records_unchanged_after_new_records(self):
        # Snapshot one of the ETL records, then exercise a separate record.
        baseline = self.call("GET", PA, 200, params={"limit": 1})["items"][0]
        url = f"{PA}/{baseline['parking_area_id']}"
        original = self.call("GET", url, 200)
        item = self.new_parking()
        self.call("PUT", f"{PA}/{item['parking_area_id']}", 200, {"capacity": 87})
        self.assertEqual(self.call("GET", url, 200), original)

    # -------------------------------------------------------
    # Trips: professor-style, adversarial end-to-end cases
    # -------------------------------------------------------

    def test_36_trip_create_get_exact_contract_and_geojson(self):
        vehicle = self.new_vehicle()
        start = point(-65.5123456789, 18.4123456789)
        end = point(-65.4987654321, 18.4234567891)
        payload = {
            "vehicle_id": vehicle["vehicle_id"],
            "start_ts": "2032-05-20T08:00:00-04:00",
            "end_ts": "2032-05-20T08:45:00-04:00",
            "start_geom": start,
            "end_geom": end,

            "distance_km": 6.7,
        }

        created = self.call("POST", T, 201, payload)
        self.resources.append(f"{T}/{created['trip_id']}")
        self.assertEqual(set(created), {
            "trip_id", "vehicle_id", "start_ts", "end_ts",
            "start_geom", "end_geom", "distance_km",
        })
        self.assertIsInstance(created["trip_id"], int)
        self.assertGreater(created["trip_id"], 0)
        self.assertEqual(created["vehicle_id"], vehicle["vehicle_id"])
        self.assertEqual(created["start_ts"], "2032-05-20T12:00:00Z")
        self.assertEqual(created["end_ts"], "2032-05-20T12:45:00Z")
        # Verify GeoJSON structure and coordinate precision.
        for actual, expected in (
            (created["start_geom"], start),
            (created["end_geom"], end),
        ):
            self.assertEqual(set(actual), {"type", "coordinates"})
            self.assertEqual(actual["type"], "Point")
            self.assertEqual(len(actual["coordinates"]), 2)

            for actual_coordinate, expected_coordinate in zip(
                actual["coordinates"], expected["coordinates"]
            ):
                self.assertAlmostEqual(
                    actual_coordinate,
                    expected_coordinate,
                    delta=5e-10,
                )
        self.assertEqual(created["distance_km"], 6.7)

        fetched = self.call("GET", f"{T}/{created['trip_id']}", 200)
        self.assertEqual(fetched, created)

    def test_37_trip_optional_values_zero_and_null_roundtrip(self):
        vehicle_id = self.seed_vehicle["vehicle_id"]

        zero = self.call("POST", T, 201, {
            "vehicle_id": vehicle_id,
            "start_ts": START,
            "end_ts": END,
            "start_geom": point(-67.15, 18.205),
            "end_geom": point(-67.14, 18.21),
            "distance_km": 0,
        })
        self.resources.append(f"{T}/{zero['trip_id']}")
        self.assertEqual(zero["distance_km"], 0)
        self.assertEqual(zero["start_geom"], point(-67.15, 18.205))
        self.assertEqual(zero["end_geom"], point(-67.14, 18.21))

        nulls = self.call("POST", T, 201, {
            "vehicle_id": vehicle_id,
            "start_ts": "2032-05-21T12:00:00Z",
            "end_ts": "2032-05-21T12:30:00Z",
            "start_geom": None,
            "end_geom": None,
            "distance_km": None,
        })
        self.resources.append(f"{T}/{nulls['trip_id']}")
        self.assertIsNone(nulls["start_geom"])
        self.assertIsNone(nulls["end_geom"])
        self.assertIsNone(nulls["distance_km"])
        self.assertEqual(
            self.call("GET", f"{T}/{nulls['trip_id']}", 200), nulls
        )

    def test_38_trip_create_invalid_payload_matrix_is_atomic(self):
        vehicle_id = self.seed_vehicle["vehicle_id"]
        valid = {
            "vehicle_id": vehicle_id,
            "start_ts": START,
            "end_ts": END,
            "start_geom": point(),
            "end_geom": point(-65.4, 18.5),
            "distance_km": 1.0,
        }
        invalid = {
            "missing vehicle_id": {k: v for k, v in valid.items() if k != "vehicle_id"},
            "missing start timestamp": {k: v for k, v in valid.items() if k != "start_ts"},
            "missing end timestamp": {k: v for k, v in valid.items() if k != "end_ts"},
            "null vehicle id": {**valid, "vehicle_id": None},
            "zero vehicle id": {**valid, "vehicle_id": 0},
            "invalid start timestamp": {**valid, "start_ts": "not-a-date"},
            "start timestamp without timezone": {
                **valid, "start_ts": "2032-05-20T12:00:00"
            },
            "end timestamp without timezone": {
                **valid, "end_ts": "2032-05-20T13:00:00"
            },
            "impossible calendar date": {**valid, "start_ts": "2032-02-30T12:00:00Z"},
            "end equals start": {**valid, "end_ts": START},
            "end before start": {**valid, "start_ts": END, "end_ts": START},
            "negative distance": {**valid, "distance_km": -0.01},
            "infinite distance": {**valid, "distance_km": float("inf")},
            "NaN distance": {**valid, "distance_km": float("nan")},
            "longitude above range": {**valid, "start_geom": point(180.000001, 18)},
            "longitude below range": {**valid, "start_geom": point(-180.000001, 18)},
            "latitude above range": {**valid, "start_geom": point(-65, 90.000001)},
            "latitude below range": {**valid, "start_geom": point(-65, -90.000001)},
            "wrong geometry type": {**valid, "start_geom": {"type": "LineString", "coordinates": [[-65, 18], [-64, 19]]}},
            "three-dimensional point": {**valid, "start_geom": {"type": "Point", "coordinates": [-65, 18, 5]}},
            "one coordinate only": {**valid, "start_geom": {"type": "Point", "coordinates": [-65]}},
            "boolean coordinate": {**valid, "start_geom": {"type": "Point", "coordinates": [True, 18]}},
            "unexpected nested geometry field": {**valid, "start_geom": {**point(), "crs": "EPSG:4326"}},
            "unexpected top-level field": {**valid, "admin": True},
        }

        before = self.call("GET", T, 200, params={"limit": 0})["count"]
        for label, payload in invalid.items():
            with self.subTest(case=label):
                self.call(
                    "POST", T, 400, payload,
                    detail="Malformed geometry or invalid JSON.",
                )

        self.call(
            "POST", T, 400, raw="{broken JSON",
            detail="Malformed geometry or invalid JSON.",
        )
        self.call(
            "POST", T, 404,
            {**valid, "vehicle_id": MISSING},
            detail="vehicle_id does not exist.",
        )
        after = self.call("GET", T, 200, params={"limit": 0})["count"]
        self.assertEqual(after, before, "Rejected Trip POST changed the Trip table")

    def test_39_trip_update_partial_full_and_persistence(self):
        vehicle = self.new_vehicle()
        trip = self.new_trip(vehicle_id=vehicle["vehicle_id"])
        url = f"{T}/{trip['trip_id']}"

        partial = self.call("PUT", url, 200, {"distance_km": 0})
        self.assertEqual(partial["distance_km"], 0)
        self.assertEqual(partial["vehicle_id"], trip["vehicle_id"])
        self.assertEqual(partial["start_ts"], trip["start_ts"])
        self.assertEqual(partial["end_ts"], trip["end_ts"])
        self.assertEqual(partial["start_geom"], trip["start_geom"])
        self.assertEqual(partial["end_geom"], trip["end_geom"])

        changed_start = point(-66.1, 19.1)
        changed_end = point(-66.0, 19.2)
        full = self.call("PUT", url, 200, {
            "start_ts": "2032-05-20T12:05:00Z",
            "end_ts": "2032-05-20T13:05:00Z",
            "start_geom": changed_start,
            "end_geom": changed_end,
            "distance_km": 12.25,
        })
        self.assertEqual(full["start_ts"], "2032-05-20T12:05:00Z")
        self.assertEqual(full["end_ts"], "2032-05-20T13:05:00Z")
        self.assertEqual(full["start_geom"], changed_start)
        self.assertEqual(full["end_geom"], changed_end)
        self.assertEqual(full["distance_km"], 12.25)
        self.assertEqual(self.call("GET", url, 200), full)

        cleared = self.call("PUT", url, 200, {
            "start_geom": None,
            "end_geom": None,
            "distance_km": None,
        })
        self.assertIsNone(cleared["start_geom"])
        self.assertIsNone(cleared["end_geom"])
        self.assertIsNone(cleared["distance_km"])
        self.assertEqual(self.call("GET", url, 200), cleared)

    def test_40_trip_invalid_updates_are_atomic(self):
        trip = self.new_trip()
        url = f"{T}/{trip['trip_id']}"
        before = self.call("GET", url, 200)

        invalid_updates = {
            "empty patch": ({}, 400, "Malformed JSON or empty patch payload."),
            "negative distance": ({"distance_km": -1}, 400, "Malformed JSON or empty patch payload."),
            "infinite distance": ({"distance_km": float("inf")}, 400, "Malformed JSON or empty patch payload."),
            "null vehicle id": ({"vehicle_id": None}, 400, "Malformed JSON or empty patch payload."),
            "null start timestamp": ({"start_ts": None}, 400, "Malformed JSON or empty patch payload."),
            "null end timestamp": ({"end_ts": None}, 400, "Malformed JSON or empty patch payload."),
            "invalid timestamp": ({"end_ts": "not-a-date"}, 400, "Malformed JSON or empty patch payload."),
            "timestamp without timezone": ({"end_ts": "2032-05-20T13:05:00"}, 400, "Malformed JSON or empty patch payload."),
            "invalid geometry": ({"start_geom": point(181, 18)}, 400, "Malformed JSON or empty patch payload."),
            "wrong geometry type": ({"end_geom": {"type": "LineString", "coordinates": []}}, 400, "Malformed JSON or empty patch payload."),
            "unknown field": ({"not_a_trip_column": 1}, 400, "Malformed JSON or empty patch payload."),
        }

        for label, (changes, expected, detail) in invalid_updates.items():
            with self.subTest(case=label):
                self.call("PUT", url, expected, changes, detail=detail)
                self.assertEqual(
                    self.call("GET", url, 200), before,
                    f"Invalid update mutated Trip: {label}",
                )

        self.call(
            "PUT", url, 422, {"end_ts": before["start_ts"]},
            detail="Validation failed.",
        )
        self.assertEqual(self.call("GET", url, 200), before)

        self.call(
            "PUT", url, 422, {"start_ts": before["end_ts"]},
            detail="Validation failed.",
        )
        self.assertEqual(self.call("GET", url, 200), before)

        self.call(
            "PUT", url, 404, {"vehicle_id": MISSING},
            detail="trip_id or referenced vehicle_id does not exist.",
        )
        self.assertEqual(self.call("GET", url, 200), before)

        self.call(
            "PUT", f"{T}/{MISSING}", 404, {"distance_km": 1},
            detail="trip_id or referenced vehicle_id does not exist.",
        )

    def test_41_trip_pagination_and_start_timestamp_filters(self):
        vehicle = self.new_vehicle()
        vehicle_id = vehicle["vehicle_id"]
        trips = [
            self.new_trip(vehicle_id, "2032-05-20T12:00:00Z", "2032-05-20T12:30:00Z"),
            self.new_trip(vehicle_id, "2032-05-20T13:00:00Z", "2032-05-20T13:30:00Z"),
            self.new_trip(vehicle_id, "2032-05-20T14:00:00Z", "2032-05-20T14:30:00Z"),
        ]
        ids = [item["trip_id"] for item in trips]

        first = self.call("GET", T, 200, params={
            "vehicle_id": vehicle_id, "limit": 2, "offset": 0,
        })
        second = self.call("GET", T, 200, params={
            "vehicle_id": vehicle_id, "limit": 2, "offset": 2,
        })
        beyond = self.call("GET", T, 200, params={
            "vehicle_id": vehicle_id, "limit": 2, "offset": 20,
        })
        self.assertEqual(first["count"], 3)
        self.assertEqual(second["count"], 3)
        self.assertEqual([x["trip_id"] for x in first["items"]], ids[:2])
        self.assertEqual([x["trip_id"] for x in second["items"]], ids[2:])
        self.assertEqual(beyond["items"], [])
        self.assertEqual(beyond["count"], 3)
        self.assertEqual(first["limit"], 2)
        self.assertEqual(first["offset"], 0)
        self.assertEqual(second["offset"], 2)
        self.assertTrue(all(set(item) == {
            "trip_id", "vehicle_id", "start_ts", "end_ts", "distance_km"
        } for item in first["items"] + second["items"]))

        zero = self.call("GET", T, 200, params={
            "vehicle_id": vehicle_id, "limit": 0, "offset": 0,
        })
        self.assertEqual(zero["items"], [])
        self.assertEqual(zero["count"], 3)

        # The current Trip API defines from_ts/to_ts against start_ts inclusively.
        lower = self.call("GET", T, 200, params={
            "vehicle_id": vehicle_id, "from_ts": "2032-05-20T13:00:00Z",
            "limit": 10,
        })
        upper = self.call("GET", T, 200, params={
            "vehicle_id": vehicle_id, "to_ts": "2032-05-20T13:00:00Z",
            "limit": 10,
        })
        exact = self.call("GET", T, 200, params={
            "vehicle_id": vehicle_id,
            "from_ts": "2032-05-20T13:00:00Z",
            "to_ts": "2032-05-20T13:00:00Z",
            "limit": 10,
        })
        self.assertEqual({x["trip_id"] for x in lower["items"]}, set(ids[1:]))
        self.assertEqual({x["trip_id"] for x in upper["items"]}, set(ids[:2]))
        self.assertEqual([x["trip_id"] for x in exact["items"]], [ids[1]])
        self.assertEqual(exact["count"], 1)

        offset_exact = self.call("GET", T, 200, params={
            "vehicle_id": vehicle_id,
            "from_ts": "2032-05-20T09:00:00-04:00",
            "to_ts": "2032-05-20T09:00:00-04:00",
            "limit": 10,
        })
        self.assertEqual(
            [x["trip_id"] for x in offset_exact["items"]],
            [ids[1]],
        )

        combined = self.call("GET", T, 200, params={
            "vehicle_id": vehicle_id,
            "from_ts": "2032-05-20T12:30:00Z",
            "to_ts": "2032-05-20T14:00:00Z",
            "limit": 10,
        })
        self.assertEqual({x["trip_id"] for x in combined["items"]}, set(ids[1:]))
        self.assertEqual(combined["count"], 2)

    def test_42_trip_vehicle_history_shape_order_and_filters(self):
        vehicle = self.new_vehicle()
        vehicle_id = vehicle["vehicle_id"]
        # Insert in deliberately non-chronological timestamp order. The endpoint
        # currently promises stable trip_id ordering, not timestamp ordering.
        later = self.new_trip(
            vehicle_id, "2032-05-20T14:00:00Z", "2032-05-20T14:30:00Z"
        )
        earlier = self.new_trip(
            vehicle_id, "2032-05-20T12:00:00Z", "2032-05-20T12:30:00Z"
        )
        middle = self.new_trip(
            vehicle_id, "2032-05-20T13:00:00Z", "2032-05-20T13:30:00Z"
        )
        url = f"{V}/{vehicle_id}/trips"

        history = self.call("GET", url, 200, params={"limit": 10, "offset": 0})
        self.assertEqual(set(history), {"vehicle_id", "items", "limit", "offset", "count"})
        self.assertEqual(history["vehicle_id"], vehicle_id)
        self.assertEqual(history["count"], 3)
        self.assertEqual(
            [x["trip_id"] for x in history["items"]],
            [later["trip_id"], earlier["trip_id"], middle["trip_id"]],
        )
        for item in history["items"]:
            self.assertEqual(set(item), {"trip_id", "start_ts", "end_ts", "distance_km"})
            self.assertNotIn("vehicle_id", item)
            self.assertNotIn("start_geom", item)
            self.assertNotIn("end_geom", item)

        page = self.call("GET", url, 200, params={"limit": 1, "offset": 1})
        self.assertEqual(page["count"], 3)
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["items"][0]["trip_id"], earlier["trip_id"])

        filtered = self.call("GET", url, 200, params={
            "from_ts": "2032-05-20T13:00:00Z",
            "to_ts": "2032-05-20T14:00:00Z",
            "limit": 10,
        })
        self.assertEqual(
            {x["trip_id"] for x in filtered["items"]},
            {later["trip_id"], middle["trip_id"]},
        )
        self.assertEqual(filtered["count"], 2)

        self.call(
            "GET", url, 400,
            params={"from_ts": "2032-05-20T13:00:00"},
            detail="Invalid query parameters.",
        )

        self.call(
            "GET", f"{V}/{MISSING}/trips", 404,
            detail="vehicle_id does not exist.",
        )
        self.call("GET", url, 400, params={"limit": -1})

    def test_43_trip_invalid_query_matrix_and_missing_ids(self):
        invalid_queries = [
            {"limit": -1},
            {"offset": -1},
            {"limit": "abc"},
            {"offset": "2.5"},
            {"limit": "1e2"},
            {"limit": "-0"},
            {"vehicle_id": 0},
            {"vehicle_id": "abc"},
            {"from_ts": "not-a-date"},
            {"from_ts": "2032-05-20T13:00:00"},
            {"from_ts": "2032-02-30T10:00:00Z"},
            {"from_ts": "2032-05-21T13:00:00Z", "to_ts": "2032-05-21T12:00:00Z"},
        ]
        for params in invalid_queries:
            with self.subTest(params=params):
                self.call(
                    "GET", T, 400, params=params,
                    detail="Invalid query parameter values.",
                )

        self.call(
            "GET", f"{T}/{MISSING}", 404,
            detail="trip_id does not exist.",
        )
        self.call(
            "DELETE", f"{T}/{MISSING}", 404,
            detail="trip_id does not exist.",
        )

    def test_44_trip_delete_exact_contract_and_foreign_key_protection(self):
        vehicle = self.new_vehicle()
        trip = self.new_trip(vehicle_id=vehicle["vehicle_id"])
        trip_url = f"{T}/{trip['trip_id']}"
        vehicle_url = f"{V}/{vehicle['vehicle_id']}"

        # A trip's FK must prevent deleting its vehicle.
        self.call(
            "DELETE", vehicle_url, 409,
            detail="Deletion is blocked by business rules /foreign key constraints.",
        )
        self.assertEqual(self.call("GET", trip_url, 200), trip)

        deleted = self.call("DELETE", trip_url, 200)
        self.assertEqual(deleted, {
            "message": "Trip deleted successfully.",
            "trip_id": trip["trip_id"],
        })
        self.call("GET", trip_url, 404, detail="trip_id does not exist.")
        self.call("DELETE", trip_url, 404, detail="trip_id does not exist.")
        self.call("DELETE", vehicle_url, 200)

    def test_45_trip_seed_record_is_unchanged_by_other_operations(self):
        seed_id = self.seed_trip["trip_id"]
        seed_url = f"{T}/{seed_id}"
        original = self.call("GET", seed_url, 200)
        temporary = self.new_trip()
        self.call(
            "PUT", f"{T}/{temporary['trip_id']}", 200,
            {"distance_km": 123.456},
        )
        self.assertEqual(
            self.call("GET", seed_url, 200), original,
            "Creating/updating a separate Trip changed a seeded ETL Trip",
        )

    def test_98_trip_count_preserved_at_end(self):
        # Clean any remaining temporary resources before comparing with baseline.
        self.cleanup()
        current = self.call("GET", T, 200, params={"limit": 0})
        self.assertEqual(
            current["count"], self.initial_trip_count,
            "Trip rows leaked or seeded Trip records were unexpectedly deleted",
        )

    def test_99_parking_count_preserved_at_end(self):
        # All per-test addCleanup handlers should already have run.
        current = self.call("GET", PA, 200, params={"limit": 0})
        self.assertEqual(current["count"], self.initial_parking_count,
                         "Parking Area records leaked or were unexpectedly deleted")



    # -------------------------------------------------------
    # Road Segments: professor-style, adversarial E2E tests
    # -------------------------------------------------------

    @staticmethod
    def road_line(*coordinates):
        """Build a GeoJSON LineString using longitude/latitude pairs."""
        return {
            "type": "LineString",
            "coordinates": [list(point) for point in coordinates],
        }

    def new_road_segment(self, **overrides):
        """Create a temporary Road Segment and register it for cleanup."""
        payload = {
            "name": "Professor Road " + uuid.uuid4().hex,
            "speed_limit_kph": 60,
            "is_oneway": True,
            "direction": "forward",
            "geom": self.road_line(
                (-65.55, 18.38),
                (-65.50, 18.40),
                (-65.45, 18.42),
            ),
        }

        payload.update(overrides)

        created = self.call("POST", RS, 201, payload)

        self.resources.append(
            f"{RS}/{created['road_id']}"
        )

        return created

    # -------------------------------------------------------
    # 46. POST: Exact creation contract
    # -------------------------------------------------------

    def test_46_road_create_exact_contract_and_unique_ids(self):
        first = self.new_road_segment()

        second = self.new_road_segment()

        self.assertEqual(
            set(first),
            {
                "road_id",
                "name",
                "speed_limit_kph",
                "is_oneway",
                "direction",
                "geom",
                "created_at",
            },
        )

        self.assertIsInstance(first["road_id"], int)
        self.assertGreater(first["road_id"], 0)

        self.assertNotEqual(
            first["road_id"],
            second["road_id"],
        )

        self.assertEqual(first["speed_limit_kph"], 60)
        self.assertIs(first["is_oneway"], True)
        self.assertEqual(first["direction"], "forward")

        self.assertEqual(
            first["geom"],
            self.road_line(
                (-65.55, 18.38),
                (-65.50, 18.40),
                (-65.45, 18.42),
            ),
        )

        self.assertTrue(first["created_at"].endswith("Z"))

        fetched = self.call(
            "GET",
            f"{RS}/{first['road_id']}",
            200,
        )

        # GET by ID should omit is_oneway and direction (rubric example)
        self.assertEqual(
            set(fetched),
            {
                "road_id",
                "name",
                "speed_limit_kph",
                "geom",
                "created_at",
            },
        )
        self.assertEqual(fetched["road_id"], first["road_id"])
        self.assertEqual(fetched["name"], first["name"])
        self.assertEqual(fetched["speed_limit_kph"], first["speed_limit_kph"])
        self.assertEqual(fetched["geom"], first["geom"])
        self.assertEqual(fetched["created_at"], first["created_at"])

    # -------------------------------------------------------
    # 47. POST: Optional fields and name normalization
    # -------------------------------------------------------

    def test_47_road_create_optional_fields_and_name_trimming(self):
        token = "OptionalRoad" + uuid.uuid4().hex[:10]

        created = self.call(
            "POST",
            RS,
            201,
            {
                "name": f"  {token}  ",
                "geom": self.road_line(
                    (-65.55, 18.38),
                    (-65.50, 18.40),
                ),
            },
        )

        self.resources.append(
            f"{RS}/{created['road_id']}"
        )

        self.assertEqual(created["name"], token)

        self.assertIsNone(created["speed_limit_kph"])
        self.assertIsNone(created["is_oneway"])
        self.assertIsNone(created["direction"])

        fetched = self.call(
            "GET",
            f"{RS}/{created['road_id']}",
            200,
        )

        # GET by ID should omit is_oneway and direction (rubric example)
        self.assertEqual(
            set(fetched),
            {
                "road_id",
                "name",
                "speed_limit_kph",
                "geom",
                "created_at",
            },
        )
        self.assertEqual(fetched["road_id"], created["road_id"])
        self.assertEqual(fetched["name"], created["name"])
        self.assertEqual(fetched["speed_limit_kph"], created["speed_limit_kph"])
        self.assertEqual(fetched["geom"], created["geom"])
        self.assertEqual(fetched["created_at"], created["created_at"])

    # -------------------------------------------------------
    # 48. POST: Adversarial invalid payload matrix
    # -------------------------------------------------------

    def test_48_road_create_invalid_payload_matrix_is_atomic(self):
        valid = {
            "name": "Rejected Road " + uuid.uuid4().hex,
            "speed_limit_kph": 60,
            "is_oneway": True,
            "direction": "forward",
            "geom": self.road_line(
                (-65.55, 18.38),
                (-65.50, 18.40),
            ),
        }

        missing_name = valid.copy()
        del missing_name["name"]

        missing_geom = valid.copy()
        del missing_geom["geom"]

        invalid = {
            "missing name": missing_name,

            "null name": {
                **valid,
                "name": None,
            },

            "empty name": {
                **valid,
                "name": "",
            },

            "whitespace name": {
                **valid,
                "name": "   ",
            },

            "numeric name": {
                **valid,
                "name": 123,
            },

            "missing geometry": missing_geom,

            "null geometry": {
                **valid,
                "geom": None,
            },

            "Point instead of LineString": {
                **valid,
                "geom": point(),
            },

            "one coordinate": {
                **valid,
                "geom": self.road_line(
                    (-65.5, 18.4),
                ),
            },

            "duplicate coordinates": {
                **valid,
                "geom": self.road_line(
                    (-65.5, 18.4),
                    (-65.5, 18.4),
                ),
            },

            "three-dimensional coordinates": {
                **valid,
                "geom": {
                    "type": "LineString",
                    "coordinates": [
                        [-65.5, 18.4, 10],
                        [-65.4, 18.5, 10],
                    ],
                },
            },

            "string coordinate": {
                **valid,
                "geom": {
                    "type": "LineString",
                    "coordinates": [
                        ["invalid", 18.4],
                        [-65.4, 18.5],
                    ],
                },
            },

            "longitude above range": {
                **valid,
                "geom": self.road_line(
                    (181, 18.4),
                    (-65.4, 18.5),
                ),
            },

            "longitude below range": {
                **valid,
                "geom": self.road_line(
                    (-181, 18.4),
                    (-65.4, 18.5),
                ),
            },

            "latitude above range": {
                **valid,
                "geom": self.road_line(
                    (-65.5, 91),
                    (-65.4, 18.5),
                ),
            },

            "latitude below range": {
                **valid,
                "geom": self.road_line(
                    (-65.5, -91),
                    (-65.4, 18.5),
                ),
            },

            "negative speed": {
                **valid,
                "speed_limit_kph": -1,
            },

            "fractional speed": {
                **valid,
                "speed_limit_kph": 60.5,
            },

            "invalid direction": {
                **valid,
                "direction": "backward",
            },

            "unknown direction": {
                **valid,
                "direction": "north",
            },

            "unexpected field": {
                **valid,
                "lanes": 3,
            },

            "unexpected geometry field": {
                **valid,
                "geom": {
                    **valid["geom"],
                    "crs": "EPSG:4326",
                },
            },

            "array instead of object": [
                valid,
            ],
        }

        before = self.call(
            "GET",
            RS,
            200,
            params={"limit": 0},
        )["count"]

        for label, payload in invalid.items():
            with self.subTest(case=label):
                self.call(
                    "POST",
                    RS,
                    400,
                    payload,
                    detail="Malformed geometry or invalid JSON.",
                )

        self.call(
            "POST",
            RS,
            400,
            raw="{broken JSON",
            detail="Malformed geometry or invalid JSON.",
        )

        after = self.call(
            "GET",
            RS,
            200,
            params={"limit": 0},
        )["count"]

        self.assertEqual(
            after,
            before,
            "Rejected Road Segment POST changed the database.",
        )

    # -------------------------------------------------------
    # 49. GET: Collection structure and pagination
    # -------------------------------------------------------

    def test_49_road_collection_pagination_and_zero_limit(self):
        token = "PaginationRoad" + uuid.uuid4().hex[:10]

        roads = [
            self.new_road_segment(name=f"{token} {i}")
            for i in range(3)
        ]

        expected_ids = sorted(
            road["road_id"] for road in roads
        )

        pages = []

        for offset in range(4):
            page = self.call(
                "GET",
                RS,
                200,
                params={
                    "name": token,
                    "limit": 1,
                    "offset": offset,
                },
            )

            pages.append(page)

            self.assertEqual(page["count"], 3)
            self.assertEqual(page["limit"], 1)
            self.assertEqual(page["offset"], offset)

        self.assertEqual(
            [
                page["items"][0]["road_id"]
                for page in pages[:3]
            ],
            expected_ids,
        )

        self.assertEqual(pages[3]["items"], [])

        self.assertEqual(
            set(pages[0]["items"][0]),
            {
                "road_id",
                "name",
                "speed_limit_kph",
                "created_at",
            },
        )

        self.assertNotIn(
            "geom",
            pages[0]["items"][0],
        )

        zero = self.call(
            "GET",
            RS,
            200,
            params={
                "name": token,
                "limit": 0,
                "offset": 0,
            },
        )

        self.assertEqual(zero["items"], [])
        self.assertEqual(zero["count"], 3)
        self.assertEqual(zero["limit"], 0)

    # -------------------------------------------------------
    # 50. GET: Combined filters and AND semantics
    # -------------------------------------------------------

    def test_50_road_combined_filters_are_intersection(self):
        token = "FilterRoad" + uuid.uuid4().hex[:10]

        inside = self.new_road_segment(
            name=f"{token} Inside",
            speed_limit_kph=40,
            geom=self.road_line(
                (-65.55, 18.38),
                (-65.50, 18.40),
            ),
        )

        crossing = self.new_road_segment(
            name=f"{token} Crossing",
            speed_limit_kph=60,
            geom=self.road_line(
                (-65.70, 18.40),
                (-65.50, 18.40),
            ),
        )

        outside = self.new_road_segment(
            name=f"{token} Outside",
            speed_limit_kph=80,
            geom=self.road_line(
                (-65.10, 18.40),
                (-65.00, 18.45),
            ),
        )

        ids = lambda response: [
            item["road_id"]
            for item in response["items"]
        ]

        result = self.call(
            "GET",
            RS,
            200,
            params={
                "name": token.lower(),
                "limit": 20,
            },
        )

        self.assertEqual(
            ids(result),
            [
                inside["road_id"],
                crossing["road_id"],
                outside["road_id"],
            ],
        )

        speed_filtered = self.call(
            "GET",
            RS,
            200,
            params={
                "name": token,
                "min_speed_kph": 50,
                "max_speed_kph": 80,
            },
        )

        self.assertEqual(
            ids(speed_filtered),
            [
                crossing["road_id"],
                outside["road_id"],
            ],
        )

        bbox = "-65.6,18.3,-65.4,18.5"

        spatial = self.call(
            "GET",
            RS,
            200,
            params={
                "bbox": bbox,
                "name": token,
            },
        )

        self.assertEqual(
            ids(spatial),
            [
                inside["road_id"],
                crossing["road_id"],
            ],
        )

        combined = self.call(
            "GET",
            RS,
            200,
            params={
                "bbox": bbox,
                "name": token,
                "min_speed_kph": 50,
                "max_speed_kph": 70,
            },
        )

        self.assertEqual(combined["count"], 1)

        self.assertEqual(
            ids(combined),
            [crossing["road_id"]],
        )

        excluded = self.call(
            "GET",
            RS,
            200,
            params={
                "name": token,
                "bbox": "-100,1,-99,2",
            },
        )

        self.assertEqual(excluded["items"], [])
        self.assertEqual(excluded["count"], 0)

    # -------------------------------------------------------
    # 51. GET: Bounding box boundary intersection
    # -------------------------------------------------------

    def test_51_road_bbox_includes_boundary_intersections(self):
        token = "BoundaryRoad" + uuid.uuid4().hex[:10]

        road = self.new_road_segment(
            name=token,
            geom=self.road_line(
                (-65.70, 18.40),
                (-65.60, 18.40),
            ),
        )

        # The endpoint touches the minimum longitude boundary.
        touching = self.call(
            "GET",
            RS,
            200,
            params={
                "name": token,
                "bbox": "-65.6,18.3,-65.4,18.5",
            },
        )

        self.assertEqual(touching["count"], 1)

        self.assertEqual(
            touching["items"][0]["road_id"],
            road["road_id"],
        )

        # Moving the box slightly away must exclude the road.
        separated = self.call(
            "GET",
            RS,
            200,
            params={
                "name": token,
                "bbox": "-65.59,18.3,-65.4,18.5",
            },
        )

        self.assertEqual(separated["count"], 0)
        self.assertEqual(separated["items"], [])

    # -------------------------------------------------------
    # 52. GET: Invalid collection query parameters
    # -------------------------------------------------------

    def test_52_road_invalid_query_parameter_matrix(self):
        invalid_queries = [
            {"limit": -1},
            {"offset": -1},
            {"limit": "abc"},
            {"offset": "2.5"},
            {"limit": "1e2"},
            {"limit": "-0"},
            {"min_speed_kph": -1},
            {"max_speed_kph": -1},
            {"min_speed_kph": "fast"},
            {"max_speed_kph": "slow"},
            {"min_speed_kph": 100, "max_speed_kph": 50},
            {"bbox": ""},
            {"bbox": "invalid"},
            {"bbox": "-67,18,-65"},
            {"bbox": "x,18,-65,19"},
            {"bbox": "nan,18,-65,19"},
            {"bbox": "-67,18,inf,19"},
            {"bbox": "-65,18,-67,19"},
            {"bbox": "-65,20,-64,19"},
            {"bbox": "-200,18,-65,19"},
            {"bbox": "-67,18,-65,91"},
        ]

        for params in invalid_queries:
            with self.subTest(params=params):
                self.call(
                    "GET",
                    RS,
                    400,
                    params=params,
                    detail="Invalid query parameter values.",
                )

    # -------------------------------------------------------
    # 53. GET / PUT / DELETE: Invalid and missing road IDs
    # -------------------------------------------------------

    def test_53_road_invalid_ids_exact_error_across_methods(self):
        expected_detail = (
            "road_id must be a positive integer."
        )

        methods = [
            ("GET", None),
            ("PUT", {"speed_limit_kph": 50}),
            ("DELETE", None),
        ]

        for method, body in methods:
            for road_id in ("0", "-1", "abc"):
                with self.subTest(
                    method=method,
                    road_id=road_id,
                ):
                    self.call(
                        method,
                        f"{RS}/{road_id}",
                        400,
                        body,
                        detail=expected_detail,
                    )

        missing_detail = "road_id does not exist."

        for method, body in methods:
            with self.subTest(
                method=method,
                road_id=MISSING,
            ):
                self.call(
                    method,
                    f"{RS}/{MISSING}",
                    404,
                    body,
                    detail=missing_detail,
                )

    # -------------------------------------------------------
    # 54. PUT: Partial, full and nullable updates
    # -------------------------------------------------------

    def test_54_road_partial_full_updates_and_persistence(self):
        road = self.new_road_segment()

        url = f"{RS}/{road['road_id']}"

        # Partial update: only speed should change.
        partial = self.call(
            "PUT",
            url,
            200,
            {
                "speed_limit_kph": 80,
            },
        )

        self.assertEqual(
            partial["speed_limit_kph"],
            80,
        )

        # PUT response should omit is_oneway and direction (rubric example)
        self.assertEqual(
            set(partial),
            {
                "road_id",
                "name",
                "speed_limit_kph",
                "geom",
                "created_at",
            },
        )
        self.assertEqual(partial["road_id"], road["road_id"])
        self.assertEqual(partial["name"], road["name"])
        self.assertEqual(partial["geom"], road["geom"])
        self.assertEqual(partial["created_at"], road["created_at"])

        # Full update.
        new_geom = self.road_line(
            (-65.58, 18.35),
            (-65.52, 18.40),
            (-65.42, 18.45),
        )

        changes = {
            "name": "Updated Road " + uuid.uuid4().hex,
            "speed_limit_kph": 0,
            "is_oneway": False,
            "direction": "both",
            "geom": new_geom,
        }

        updated = self.call(
            "PUT",
            url,
            200,
            changes,
        )

        # PUT response should omit is_oneway and direction (rubric example)
        self.assertEqual(
            set(updated),
            {
                "road_id",
                "name",
                "speed_limit_kph",
                "geom",
                "created_at",
            },
        )
        self.assertEqual(updated["name"], changes["name"])
        self.assertEqual(updated["speed_limit_kph"], changes["speed_limit_kph"])
        self.assertEqual(updated["geom"], changes["geom"])
        self.assertEqual(
            updated["created_at"],
            road["created_at"],
        )

        self.assertEqual(
            self.call("GET", url, 200),
            updated,
        )

        # Optional database fields can be explicitly cleared.
        cleared = self.call(
            "PUT",
            url,
            200,
            {
                "speed_limit_kph": None,
            },
        )

        # PUT response should omit is_oneway and direction (rubric example)
        self.assertEqual(
            set(cleared),
            {
                "road_id",
                "name",
                "speed_limit_kph",
                "geom",
                "created_at",
            },
        )
        self.assertIsNone(cleared["speed_limit_kph"])
        self.assertEqual(
            cleared["geom"],
            new_geom,
        )

        self.assertEqual(
            self.call("GET", url, 200),
            cleared,
        )

    # -------------------------------------------------------
    # 55. PUT: Invalid updates and atomicity
    # -------------------------------------------------------

    def test_55_road_invalid_updates_are_atomic(self):
        road = self.new_road_segment()

        url = f"{RS}/{road['road_id']}"

        before = self.call(
            "GET",
            url,
            200,
        )

        invalid_updates = {
            "empty patch": {},

            "null name": {
                "name": None,
            },

            "empty name": {
                "name": "",
            },

            "whitespace name": {
                "name": "  ",
            },

            "null geometry": {
                "geom": None,
            },

            "negative speed": {
                "speed_limit_kph": -1,
            },

            "fractional speed": {
                "speed_limit_kph": 60.5,
            },

            "invalid direction": {
                "direction": "backward",
            },

            "invalid direction value": {
                "direction": "north",
            },

            "wrong geometry type": {
                "geom": point(),
            },

            "one coordinate": {
                "geom": self.road_line(
                    (-65.5, 18.4),
                ),
            },

            "unknown field": {
                "lanes": 3,
            },

            "valid fields mixed with invalid geometry": {
                "name": "MUST NOT BE SAVED",
                "speed_limit_kph": 0,
                "geom": {
                    "type": "LineString",
                    "coordinates": [],
                },
            },
        }

        for label, changes in invalid_updates.items():
            with self.subTest(case=label):
                self.call(
                    "PUT",
                    url,
                    400,
                    changes,
                    detail="Malformed JSON or empty patch payload.",
                )

                self.assertEqual(
                    self.call("GET", url, 200),
                    before,
                    f"Invalid update mutated Road Segment: {label}",
                )

        self.call(
            "PUT",
            url,
            400,
            raw="{bad JSON",
            detail="Malformed JSON or empty patch payload.",
        )

        self.assertEqual(
            self.call("GET", url, 200),
            before,
            "Malformed JSON modified the original record.",
        )

        # A nonexistent road must not be created by an update.
        self.call(
            "PUT",
            f"{RS}/{MISSING}",
            404,
            {
                "speed_limit_kph": 50,
            },
            detail="road_id does not exist.",
        )

    # -------------------------------------------------------
    # 56. GeoJSON: Exact FeatureCollection contract
    # -------------------------------------------------------

    def test_56_road_geojson_exact_feature_collection_contract(self):
        token = "GeoJSONRoad" + uuid.uuid4().hex[:10]

        road = self.new_road_segment(
            name=token,
        )

        url = (
            f"{RS}/geojson?"
            + urlencode({"name": token})
        )

        request = Request(url, method="GET")

        with urlopen(request, timeout=15) as response:
            self.assertEqual(response.status, 200)

            self.assertTrue(
                response.headers.get("Content-Type", "").startswith(
                    "application/geo+json"
                )
            )

            data = json.loads(
                response.read()
            )

        self.assertEqual(
            set(data),
            {
                "type",
                "count",
                "limit",
                "offset",
                "features",
            },
        )

        self.assertEqual(
            data["type"],
            "FeatureCollection",
        )

        self.assertEqual(data["count"], 1)
        self.assertEqual(data["limit"], 15000)
        self.assertEqual(data["offset"], 0)

        self.assertEqual(len(data["features"]), 1)

        feature = data["features"][0]

        self.assertEqual(
            set(feature),
            {
                "type",
                "geometry",
                "properties",
            },
        )

        self.assertEqual(
            feature["type"],
            "Feature",
        )

        self.assertEqual(
            feature["geometry"],
            road["geom"],
        )

        expected_properties = {
            key: road[key]
            for key in (
                "road_id",
                "name",
                "speed_limit_kph",
                "is_oneway",
                "direction",
                "created_at",
            )
        }

        self.assertEqual(
            feature["properties"],
            expected_properties,
        )

    # -------------------------------------------------------
    # 57. GeoJSON: Filters and pagination
    # -------------------------------------------------------

    def test_57_road_geojson_filters_and_count_before_pagination(self):
        token = "GeoFilter" + uuid.uuid4().hex[:10]

        slow = self.new_road_segment(
            name=f"{token} Slow",
            speed_limit_kph=30,
        )

        fast = self.new_road_segment(
            name=f"{token} Fast",
            speed_limit_kph=70,
        )

        filtered = self.call(
            "GET",
            f"{RS}/geojson",
            200,
            params={
                "name": token.lower(),
                "min_speed_kph": 40,
                "max_speed_kph": 80,
            },
        )

        self.assertEqual(filtered["count"], 1)

        self.assertEqual(
            [
                feature["properties"]["road_id"]
                for feature in filtered["features"]
            ],
            [fast["road_id"]],
        )

        paginated = self.call(
            "GET",
            f"{RS}/geojson",
            200,
            params={
                "name": token,
                "limit": 1,
                "offset": 1,
            },
        )

        self.assertEqual(paginated["count"], 2)
        self.assertEqual(paginated["limit"], 1)
        self.assertEqual(paginated["offset"], 1)

        self.assertEqual(
            len(paginated["features"]),
            1,
        )

        self.assertEqual(
            paginated["features"][0]["properties"]["road_id"],
            fast["road_id"],
        )

        zero = self.call(
            "GET",
            f"{RS}/geojson",
            200,
            params={
                "name": token,
                "limit": 0,
            },
        )

        self.assertEqual(zero["features"], [])
        self.assertEqual(zero["count"], 2)

    # -------------------------------------------------------
    # 58. GeoJSON: Exact filter and validation errors
    # -------------------------------------------------------

    def test_58_road_geojson_invalid_filter_matrix(self):
        invalid_filters = [
            {
                "params": {
                    "bbox": "-65.6,18.3,-65.4,18.5",
                },
                "status": 400,
                "detail": "Invalid or inconsistent filter values.",
            },
            {
                "params": {
                    "min_speed_kph": 80,
                    "max_speed_kph": 40,
                },
                "status": 400,
                "detail": "Invalid or inconsistent filter values.",
            },
            {
                "params": {
                    "limit": -1,
                },
                "status": 422,
                "detail": "A query parameter fails type or range validation.",
            },
            {
                "params": {
                    "limit": "many",
                },
                "status": 422,
                "detail": "A query parameter fails type or range validation.",
            },
            {
                "params": {
                    "offset": "x",
                },
                "status": 422,
                "detail": "A query parameter fails type or range validation.",
            },
            {
                "params": {
                    "min_speed_kph": "slow",
                },
                "status": 422,
                "detail": "A query parameter fails type or range validation.",
            },
            {
                "params": {
                    "max_speed_kph": -10,
                },
                "status": 422,
                "detail": "A query parameter fails type or range validation.",
            },
        ]

        for case in invalid_filters:
            with self.subTest(params=case["params"]):
                self.call(
                    "GET",
                    f"{RS}/geojson",
                    case["status"],
                    params=case["params"],
                    detail=case["detail"],
                )

    # -------------------------------------------------------
    # 59. DELETE: Exact response and repeated deletion
    # -------------------------------------------------------

    def test_59_road_delete_exact_contract_and_repeated_delete(self):
        road = self.new_road_segment()

        url = f"{RS}/{road['road_id']}"

        deleted = self.call(
            "DELETE",
            url,
            200,
        )

        self.assertEqual(
            deleted,
            {
                "message": "Road segment deleted successfully.",
                "road_id": road["road_id"],
            },
        )

        self.call(
            "GET",
            url,
            404,
            detail="road_id does not exist.",
        )

        self.call(
            "DELETE",
            url,
            404,
            detail="road_id does not exist.",
        )

    # -------------------------------------------------------
    # 60. Database integrity: Seed record preservation
    # -------------------------------------------------------

    def test_60_road_seed_record_unchanged_by_other_operations(self):
        baseline_list = self.call(
            "GET",
            RS,
            200,
            params={
                "limit": 1,
                "offset": 0,
            },
        )

        self.assertTrue(baseline_list["items"])

        seed_id = baseline_list["items"][0]["road_id"]

        seed_url = f"{RS}/{seed_id}"

        original = self.call(
            "GET",
            seed_url,
            200,
        )

        temporary = self.new_road_segment()

        self.call(
            "PUT",
            f"{RS}/{temporary['road_id']}",
            200,
            {
                "name": "Temporary Updated Road",
                "speed_limit_kph": 100,
                "direction": "both",
                "is_oneway": False,
            },
        )

        self.assertEqual(
            self.call("GET", seed_url, 200),
            original,
            "Creating/updating a different road modified a seeded Road Segment.",
        )

    # -------------------------------------------------------
    # 61. Security: SQL injection-like filter values
    # -------------------------------------------------------

    def test_61_road_sql_injection_like_name_is_treated_as_data(self):
        suspicious = (
            "' OR 1=1 -- "
            + uuid.uuid4().hex
        )

        result = self.call(
            "GET",
            RS,
            200,
            params={
                "name": suspicious,
                "limit": 20,
            },
        )

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["items"], [])

        # The collection must still contain its original records.
        total = self.call(
            "GET",
            RS,
            200,
            params={
                "limit": 0,
            },
        )

        self.assertGreater(total["count"], 0)

    # -------------------------------------------------------
    # Final Road Segment database preservation
    # -------------------------------------------------------

    def test_zz_road_count_preserved_at_end(self):
        # Remove any remaining temporary resources before comparing.
        self.cleanup()

        current = self.call(
            "GET",
            RS,
            200,
            params={
                "limit": 0,
            },
        )

        self.assertEqual(
            current["count"],
            self.initial_road_count,
            (
                "Road Segment records leaked, seeded records were deleted, "
                "or the original database count changed."
            ),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
