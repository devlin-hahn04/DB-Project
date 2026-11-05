
"""Strict Car Tracking REST API integration tests.

Run from the project root:
    $env:CARTRACKING_E2E_ALLOW_WRITES = "cartracking_test"
    python -m unittest discover -s backend/tests -p test_professor_grader.py -v

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
        
        "409": "Deletion is blocked by business rules/foreign key constraints.",
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

        for url in (D, V, A, P):
            status, response = http("GET", url, params={"limit": 1})
            if status != 200 or not response.get("items"):
                raise RuntimeError("Populated test database required: " + url)

        cls.seed_vehicle = http(
            "GET", V, params={"limit": 1}
        )[1]["items"][0]

        cls.seed_driver = http(
            "GET", D, params={"limit": 1}
        )[1]["items"][0]

        cls.resources = []

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

    # -------------------------------------------------------
    # Rubric and response structures
    # -------------------------------------------------------

    def test_01_openapi_exact_rubric(self):
        spec = self.call("GET", ROOT + "/openapi.json", 200)

        self.assertEqual(sum(map(len, EXPECTED.values())), 64)

        for (path, method), expected in EXPECTED.items():
            with self.subTest(path=path, method=method):
                actual = {
                    code: item["description"]
                    for code, item in
                    spec["paths"][path][method]["responses"].items()
                }

                self.assertEqual(actual, expected)

    def test_02_all_list_shapes_and_zero_limit(self):
        for url in (D, V, A, P):
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
        ping = self.new_ping()
        url = f"{P}/{ping['ping_id']}"

        self.assertEqual(
            set(ping),
            {
                "ping_id", "vehicle_id", "ts",
                "geom", "speed_kph", "heading_deg"
            }
        )

        self.assertEqual(ping["geom"], point())
        self.assertEqual(self.call("GET", url, 200), ping)

        updated = self.call(
            "PUT", url, 200,
            {"speed_kph": 0, "heading_deg": 0}
        )

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
            detail="Deletion is blocked by business rules/foreign key constraints."
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
            detail="Deletion is blocked by business rules/foreign key constraints."
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
        for url in (D, V, A, P):
            with self.subTest(url=url):
                self.call(
                    "GET", url, 400,
                    params={"limit": "-1"},
                    detail="Invalid query parameter values."
                )

        for url, message in [
            (P, "ping_id must be a positive integer."),
            (A, "assignment_id must be a positive integer."),
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

        for url in (D, V, A, P):
            response = self.call(
                "GET", url, 200,
                params={"limit": 0}
            )

            self.assertGreater(response["count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
