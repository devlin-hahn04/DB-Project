
#!/usr/bin/env python3
"""
CAR TRACKING API - COMPLETE INTEGRATION TEST SUITE

Tests:
    GET, POST, PUT, DELETE
    Driver CRUD
    Vehicle CRUD
    Pagination and filtering
    Input validation
    Duplicate constraints
    Foreign key constraints
    Current vehicle location

SAFETY:
    - Only targets http://localhost:8001
    - Verifies backend-test uses cartracking_test
    - Verifies the actual database connection
    - Backs up cartracking_test before write tests
    - Restores cartracking_test after testing
    - Never writes to the original cartracking database

Requirements:
    Python 3.12+
    Docker Compose
    Running postgres and backend-test services

Run:
    python test_car_tracking_api.py --confirm-isolated-test-db
"""

import argparse
import json
import subprocess
import sys
import tempfile
import uuid
import urllib.error
import urllib.parse
import urllib.request

from pathlib import Path


BASE_URL = "http://localhost:8001"
TEST_DB = "cartracking_test"


# =========================================================
# Docker helpers
# =========================================================

def docker(*args, input_data=None, check=True):
    command = ["docker", *args]

    result = subprocess.run(
        command,
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(command)}\n"
            + result.stderr.decode(errors="replace")
        )

    return result


def compose(*args):
    return docker("compose", *args)


def get_postgres_user():
    result = compose(
        "exec", "-T", "postgres",
        "printenv", "POSTGRES_USER",
    )
    username = result.stdout.decode().strip()

    if not username:
        raise RuntimeError("POSTGRES_USER is empty")

    return username


def verify_isolation():
    print("\nVerifying isolated test environment...")

    test_env = compose(
        "exec", "-T", "backend-test",
        "printenv", "DB_NAME",
    ).stdout.decode().strip()

    original_env = compose(
        "exec", "-T", "backend",
        "printenv", "DB_NAME",
    ).stdout.decode().strip()

    if test_env != TEST_DB:
        raise RuntimeError(
            f"UNSAFE: backend-test uses {test_env!r}"
        )

    if original_env != "cartracking":
        raise RuntimeError(
            f"Unexpected original database: {original_env!r}"
        )

    # Verify the database actually reached through the
    # test backend's configured application connection pool.
    python_code = (
        "from backend.config.dbconfig import "
        "initialize_connection_pool, "
        "get_db_connection, close_connection_pool; "
        "initialize_connection_pool(); "
        "c = get_db_connection(); "
        "conn = c.__enter__(); "
        "cur = conn.cursor(); "
        "cur.execute('SELECT current_database()'); "
        "print(cur.fetchone()[0]); "
        "cur.close(); "
        "c.__exit__(None, None, None); "
        "close_connection_pool()"
    )

    result = compose(
        "exec", "-T", "backend-test",
        "python", "-c", python_code,
    )

    actual_db = result.stdout.decode().strip()

    if actual_db != TEST_DB:
        raise RuntimeError(
            f"UNSAFE: Actual connection uses {actual_db!r}"
        )

    print("[PASS] Original backend uses cartracking")
    print("[PASS] Test backend uses cartracking_test")
    print("[PASS] Actual connection pool uses cartracking_test")


def backup_database(backup_path, username):
    print("\nBacking up test database...")

    # pg_dump writes the custom-format backup to stdout.
    # Store it on the Windows host, outside the container.
    with open(backup_path, "wb") as output:
        result = subprocess.run(
            [
                "docker", "compose", "exec", "-T",
                "postgres", "pg_dump",
                "-U", username,
                "-d", TEST_DB,
                "-Fc",
            ],
            stdout=output,
            stderr=subprocess.PIPE,
        )

    if result.returncode != 0:
        raise RuntimeError(
            "Database backup failed:\n"
            + result.stderr.decode(errors="replace")
        )

    if backup_path.stat().st_size == 0:
        raise RuntimeError("Database backup is empty")

    print("[PASS] Test database backup created")


def restore_database(backup_path, username):
    print("\nRestoring test database...")

    # Stop the test API so it releases its connections.
    compose(
        "--profile", "test",
        "stop", "backend-test",
    )

    # These commands operate ONLY on cartracking_test.
    if TEST_DB != "cartracking_test":
        raise RuntimeError("Unsafe restore database name")

    compose(
        "exec", "-T", "postgres",
        "dropdb", "-U", username,
        "--if-exists", TEST_DB,
    )

    compose(
        "exec", "-T", "postgres",
        "createdb", "-U", username,
        "-O", username, TEST_DB,
    )

    with open(backup_path, "rb") as backup:
        result = subprocess.run(
            [
                "docker", "compose", "exec", "-T",
                "postgres", "pg_restore",
                "-U", username,
                "-d", TEST_DB,
                "--no-owner",
                "--no-acl",
            ],
            stdin=backup,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    if result.returncode != 0:
        raise RuntimeError(
            "Database restoration failed:\n"
            + result.stderr.decode(errors="replace")
        )

    compose(
        "--profile", "test",
        "up", "-d", "backend-test",
    )

    verify_isolation()

    print("[PASS] Test database restored successfully")


# =========================================================
# HTTP test utilities
# =========================================================

class Tester:

    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def request(self, method, path, data=None, params=None):
        url = self.base + path

        if params:
            url += "?" + urllib.parse.urlencode(params)

        headers = {
            "Accept": "application/json",
        }

        payload = None

        if data is not None:
            payload = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url,
            data=payload,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request, timeout=15
            ) as response:
                raw = response.read()
                return (
                    response.status,
                    json.loads(raw) if raw else None,
                )

        except urllib.error.HTTPError as error:
            raw = error.read()

            try:
                body = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                body = raw.decode(errors="replace")

            return error.code, body

    def expect(
        self, method, path, expected,
        data=None, params=None, verify=None,
    ):
        status, body = self.request(
            method, path, data, params
        )

        assert status == expected, (
            f"{method} {path}: "
            f"Expected {expected}, got {status}. "
            f"Response: {body!r}"
        )

        if verify:
            verify(body)

        return body

    def check(self, name, function):
        try:
            function()
            self.passed += 1
            print(f"[PASS] {name}")
            return True

        except Exception as error:
            self.failed += 1
            print(f"[FAIL] {name}: {error}")
            return False

    def skip(self, name, reason):
        self.skipped += 1
        print(f"[SKIP] {name}: {reason}")


def verify_list(body, limit, offset):
    assert isinstance(body, dict)
    assert isinstance(body.get("items"), list)
    assert body["limit"] == limit
    assert body["offset"] == offset
    assert isinstance(body["count"], int)
    assert body["count"] >= 0
    assert len(body["items"]) <= limit


def verify_field(field, expected):
    def verify(body):
        assert body[field] == expected, (
            f"Expected {field}={expected!r}, "
            f"got {body.get(field)!r}"
        )
    return verify


# =========================================================
# Read-only GET tests
# =========================================================

def test_read_only(t):
    print("\n" + "=" * 60)
    print("READ-ONLY GET TESTS")
    print("=" * 60)

    for plural, id_key in (
        ("drivers", "driver_id"),
        ("vehicles", "vehicle_id"),
    ):
        root = f"/api/v1/{plural}"

        print(f"\n=== {plural.upper()} ===")

        t.check(
            "List first page",
            lambda root=root: t.expect(
                "GET", root, 200,
                params={"limit": 3, "offset": 0},
                verify=lambda b: verify_list(b, 3, 0),
            ),
        )

        t.check(
            "Zero limit",
            lambda root=root: t.expect(
                "GET", root, 200,
                params={"limit": 0, "offset": 0},
                verify=lambda b: verify_list(b, 0, 0),
            ),
        )

        t.check(
            "Negative limit rejected",
            lambda root=root: t.expect(
                "GET", root, 400,
                params={"limit": -1},
            ),
        )

        t.check(
            "Negative offset rejected",
            lambda root=root: t.expect(
                "GET", root, 400,
                params={"offset": -1},
            ),
        )

        t.check(
            "Noninteger limit rejected",
            lambda root=root: t.expect(
                "GET", root, 400,
                params={"limit": "abc"},
            ),
        )

        def large_offset(root=root):
            body = t.expect(
                "GET", root, 200,
                params={"limit": 3, "offset": 99999999},
            )
            verify_list(body, 3, 99999999)
            assert body["items"] == []

        t.check(
            "Large offset returns empty page",
            large_offset,
        )

        t.check(
            "Nonexistent ID returns 404",
            lambda root=root: t.expect(
                "GET", root + "/99999999", 404
            ),
        )

        t.check(
            "Zero ID returns 400",
            lambda root=root: t.expect(
                "GET", root + "/0", 400
            ),
        )

        t.check(
            "Negative ID returns 400",
            lambda root=root: t.expect(
                "GET", root + "/-1", 400
            ),
        )

        def existing_record(root=root, id_key=id_key):
            body = t.expect(
                "GET", root, 200,
                params={"limit": 1},
            )

            assert body["items"], "No seeded records"

            record_id = body["items"][0][id_key]

            t.expect(
                "GET",
                f"{root}/{record_id}",
                200,
                verify=verify_field(id_key, record_id),
            )

        t.check(
            "Existing ID returns correct record",
            existing_record,
        )

    print("\n=== DRIVER FILTERS ===")

    t.check(
        "Unmatched name filter",
        lambda: t.expect(
            "GET", "/api/v1/drivers", 200,
            params={
                "name": "NO-SUCH-DRIVER-XYZ-999999",
                "limit": 10,
            },
            verify=lambda b: (
                verify_list(b, 10, 0),
                b["count"] == 0 or
                (_ for _ in ()).throw(
                    AssertionError("Expected zero matches")
                ),
            ),
        ),
    )

    t.check(
        "Unmatched license filter",
        lambda: t.expect(
            "GET", "/api/v1/drivers", 200,
            params={
                "license_number": "NO-SUCH-LICENSE-XYZ",
                "limit": 10,
            },
            verify=lambda b: (
                verify_list(b, 10, 0),
                b["count"] == 0 or
                (_ for _ in ()).throw(
                    AssertionError("Expected zero matches")
                ),
            ),
        ),
    )

    print("\n=== VEHICLE FILTERS ===")

    def unmatched_plate():
        body = t.expect(
            "GET", "/api/v1/vehicles", 200,
            params={
                "plate_number": "NO-SUCH-PLATE-XYZ-999999",
                "limit": 10,
            },
        )
        verify_list(body, 10, 0)
        assert body["count"] == 0
        assert body["items"] == []

    t.check("Unmatched plate filter", unmatched_plate)

    t.check(
        "Partial plate filter",
        lambda: t.expect(
            "GET", "/api/v1/vehicles", 200,
            params={"plate_number": "PR-00", "limit": 10},
            verify=lambda b: verify_list(b, 10, 0),
        ),
    )

    print("\n=== CURRENT LOCATION ===")

    t.check(
        "Nonexistent vehicle location returns 404",
        lambda: t.expect(
            "GET",
            "/api/v1/vehicles/99999999/current-location",
            404,
        ),
    )

    t.check(
        "Invalid vehicle location ID returns 400",
        lambda: t.expect(
            "GET",
            "/api/v1/vehicles/0/current-location",
            400,
        ),
    )

    def verify_geojson():
        vehicles = t.expect(
            "GET", "/api/v1/vehicles", 200,
            params={"limit": 100},
        )

        found = None

        for vehicle in vehicles["items"]:
            vehicle_id = vehicle["vehicle_id"]

            status, location = t.request(
                "GET",
                f"/api/v1/vehicles/"
                f"{vehicle_id}/current-location",
            )

            if status == 200:
                found = (vehicle_id, location)
                break

            assert status == 204, (
                f"Unexpected location status {status}"
            )

        if found is None:
            raise RuntimeError(
                "No seeded vehicle with GPS data"
            )

        vehicle_id, location = found

        assert location["vehicle_id"] == vehicle_id

        geom = location["last_geom"]
        assert geom["type"] == "Point"
        assert len(geom["coordinates"]) >= 2

        for value in geom["coordinates"][:2]:
            assert isinstance(value, (int, float))

        for field in (
            "plate_number",
            "status",
            "vehicle_kind",
            "fuel_type",
            "last_ts",
            "speed_kph",
            "heading_deg",
        ):
            assert field in location

    t.check(
        "Current location returns valid GeoJSON",
        verify_geojson,
    )


# =========================================================
# Driver CRUD tests
# =========================================================

def test_driver_crud(t):
    print("\n" + "=" * 60)
    print("DRIVER CRUD TESTS")
    print("=" * 60)

    root = "/api/v1/drivers"
    unique = uuid.uuid4().hex[:12].upper()

    license_number = f"TEST-{unique}"
    updated_license = f"UPDATED-{unique}"

    payload = {
        "first_name": "Integration",
        "last_name": "TestDriver",
        "license_number": license_number,
        "hired_at": "2026-10-01T10:30:00-04:00",
    }

    created = {}

    def create_driver():
        body = t.expect(
            "POST", root, 201,
            data=payload,
        )

        assert isinstance(body["driver_id"], int)
        assert body["first_name"] == "Integration"
        assert body["license_number"] == license_number
        assert body["hired_at"] == "2026-10-01T14:30:00Z"

        created["id"] = body["driver_id"]

    created_ok = t.check(
        "POST create driver",
        create_driver,
    )

    if not created_ok:
        t.skip(
            "Driver-dependent CRUD tests",
            "Driver creation failed",
        )
        return

    driver_id = created["id"]
    path = f"{root}/{driver_id}"

    t.check(
        "GET newly created driver",
        lambda: t.expect(
            "GET", path, 200,
            verify=verify_field(
                "license_number", license_number
            ),
        ),
    )

    t.check(
        "POST duplicate license returns 409",
        lambda: t.expect(
            "POST", root, 409,
            data=payload,
        ),
    )

    t.check(
        "POST missing required field returns 422",
        lambda: t.expect(
            "POST", root, 422,
            data={
                "first_name": "Missing",
                "last_name": "License",
                "hired_at": "2026-10-01T10:30:00Z",
            },
        ),
    )

    t.check(
        "POST blank first name returns 422",
        lambda: t.expect(
            "POST", root, 422,
            data={
                **payload,
                "first_name": "   ",
            },
        ),
    )

    t.check(
        "POST timestamp without timezone returns 422",
        lambda: t.expect(
            "POST", root, 422,
            data={
                **payload,
                "hired_at": "2026-10-01T10:30:00",
            },
        ),
    )

    t.check(
        "POST extra field returns 400",
        lambda: t.expect(
            "POST", root, 400,
            data={
                **payload,
                "unknown_field": "invalid",
            },
        ),
    )

    t.check(
        "GET driver by license filter",
        lambda: t.expect(
            "GET", root, 200,
            params={"license_number": license_number},
            verify=lambda b: (
                verify_list(b, 20, 0),
                assert_driver_in_list(
                    b, driver_id
                ),
            ),
        ),
    )

    t.check(
        "GET driver by name filter",
        lambda: t.expect(
            "GET", root, 200,
            params={"name": "Integration"},
            verify=lambda b: assert_driver_in_list(
                b, driver_id
            ),
        ),
    )

    t.check(
        "PUT partial update driver",
        lambda: t.expect(
            "PUT", path, 200,
            data={
                "first_name": "UpdatedDriver",
                "license_number": updated_license,
            },
            verify=lambda b: (
                verify_field(
                    "first_name", "UpdatedDriver"
                )(b),
                verify_field(
                    "license_number", updated_license
                )(b),
            ),
        ),
    )

    t.check(
        "GET updated driver persists",
        lambda: t.expect(
            "GET", path, 200,
            verify=verify_field(
                "license_number", updated_license
            ),
        ),
    )

    t.check(
        "PUT empty body returns 400",
        lambda: t.expect(
            "PUT", path, 400,
            data={},
        ),
    )

    t.check(
        "PUT null first name returns 422",
        lambda: t.expect(
            "PUT", path, 422,
            data={"first_name": None},
        ),
    )

    t.check(
        "PUT invalid timestamp returns 422",
        lambda: t.expect(
            "PUT", path, 422,
            data={"hired_at": "not-a-timestamp"},
        ),
    )

    t.check(
        "PUT nonexistent driver returns 404",
        lambda: t.expect(
            "PUT", f"{root}/99999999", 404,
            data={"first_name": "Nobody"},
        ),
    )

    t.check(
        "PUT zero driver ID returns 400",
        lambda: t.expect(
            "PUT", f"{root}/0", 400,
            data={"first_name": "Invalid"},
        ),
    )

    t.check(
        "DELETE created driver",
        lambda: t.expect(
            "DELETE", path, 200,
            verify=verify_field(
                "driver_id", driver_id
            ),
        ),
    )

    t.check(
        "GET deleted driver returns 404",
        lambda: t.expect(
            "GET", path, 404,
        ),
    )

    t.check(
        "DELETE same driver again returns 404",
        lambda: t.expect(
            "DELETE", path, 404,
        ),
    )

    t.check(
        "DELETE zero driver ID returns 400",
        lambda: t.expect(
            "DELETE", f"{root}/0", 400,
        ),
    )


def assert_driver_in_list(body, driver_id):
    assert any(
        item["driver_id"] == driver_id
        for item in body["items"]
    ), f"Driver {driver_id} not found in filtered list"


# =========================================================
# Vehicle CRUD tests
# =========================================================

def test_vehicle_crud(t):
    print("\n" + "=" * 60)
    print("VEHICLE CRUD TESTS")
    print("=" * 60)

    root = "/api/v1/vehicles"
    unique = uuid.uuid4().hex[:12].upper()

    plate_number = f"TEST-{unique}"
    updated_plate = f"UPD-{unique}"

    # Reuse valid foreign keys from a seeded vehicle.
    # This avoids assuming vehicle_type_id=2 or
    # vehicle_status_id=1 exists.
    existing = t.expect(
        "GET", root, 200,
        params={"limit": 1},
    )

    if not existing["items"]:
        t.skip(
            "Vehicle CRUD",
            "No seeded vehicle to obtain valid foreign keys",
        )
        return

    seed = existing["items"][0]

    payload = {
        "vehicle_type_id": seed["vehicle_type_id"],
        "vehicle_status_id": seed["vehicle_status_id"],
        "plate_number": plate_number,
        "make": "TestMake",
        "model": "TestModel",
        "year": 2024,
    }

    created = {}

    def create_vehicle():
        body = t.expect(
            "POST", root, 201,
            data=payload,
        )

        assert isinstance(body["vehicle_id"], int)
        assert body["plate_number"] == plate_number
        assert body["make"] == "TestMake"
        assert body["year"] == 2024

        created["id"] = body["vehicle_id"]

    created_ok = t.check(
        "POST create vehicle",
        create_vehicle,
    )

    if not created_ok:
        t.skip(
            "Vehicle-dependent CRUD tests",
            "Vehicle creation failed",
        )
        return

    vehicle_id = created["id"]
    path = f"{root}/{vehicle_id}"

    t.check(
        "GET newly created vehicle",
        lambda: t.expect(
            "GET", path, 200,
            verify=verify_field(
                "plate_number", plate_number
            ),
        ),
    )

    t.check(
        "POST duplicate plate returns 409",
        lambda: t.expect(
            "POST", root, 409,
            data=payload,
        ),
    )

    t.check(
        "POST missing vehicle type returns 400",
        lambda: t.expect(
            "POST", root, 400,
            data={
                "vehicle_status_id":
                    seed["vehicle_status_id"],
                "plate_number": f"MISSING-{unique}",
            },
        ),
    )

    t.check(
        "POST invalid year returns 400",
        lambda: t.expect(
            "POST", root, 400,
            data={
                **payload,
                "year": 1900,
            },
        ),
    )

    t.check(
        "POST blank plate returns 400",
        lambda: t.expect(
            "POST", root, 400,
            data={
                **payload,
                "plate_number": "   ",
            },
        ),
    )

    t.check(
        "POST invalid vehicle type FK returns 404",
        lambda: t.expect(
            "POST", root, 404,
            data={
                **payload,
                "vehicle_type_id": 99999999,
                "plate_number": f"BADFK-{unique}",
            },
        ),
    )

    t.check(
        "POST invalid status FK returns 404",
        lambda: t.expect(
            "POST", root, 404,
            data={
                **payload,
                "vehicle_status_id": 99999999,
                "plate_number": f"BADST-{unique}",
            },
        ),
    )

    t.check(
        "GET vehicle by plate filter",
        lambda: t.expect(
            "GET", root, 200,
            params={"plate_number": plate_number},
            verify=lambda b: assert_vehicle_in_list(
                b, vehicle_id
            ),
        ),
    )

    t.check(
        "GET vehicle by status ID filter",
        lambda: t.expect(
            "GET", root, 200,
            params={
                "status": str(seed["vehicle_status_id"]),
                "limit": 100,
            },
            verify=lambda b: assert_vehicle_in_list(
                b, vehicle_id
            ),
        ),
    )

    t.check(
        "PUT partial vehicle update",
        lambda: t.expect(
            "PUT", path, 200,
            data={
                "plate_number": updated_plate,
                "make": "UpdatedMake",
                "year": 2025,
            },
            verify=lambda b: (
                verify_field(
                    "plate_number", updated_plate
                )(b),
                verify_field(
                    "make", "UpdatedMake"
                )(b),
                verify_field(
                    "year", 2025
                )(b),
            ),
        ),
    )

    t.check(
        "GET updated vehicle persists",
        lambda: t.expect(
            "GET", path, 200,
            verify=verify_field(
                "plate_number", updated_plate
            ),
        ),
    )

    t.check(
        "PUT empty body returns 400",
        lambda: t.expect(
            "PUT", path, 400,
            data={},
        ),
    )

    t.check(
        "PUT null required FK returns 400",
        lambda: t.expect(
            "PUT", path, 400,
            data={"vehicle_type_id": None},
        ),
    )

    t.check(
        "PUT invalid year returns 400",
        lambda: t.expect(
            "PUT", path, 400,
            data={"year": 1940},
        ),
    )

    t.check(
        "PUT invalid status FK returns 404",
        lambda: t.expect(
            "PUT", path, 404,
            data={"vehicle_status_id": 99999999},
        ),
    )

    t.check(
        "PUT nonexistent vehicle returns 404",
        lambda: t.expect(
            "PUT", f"{root}/99999999", 404,
            data={"make": "Nobody"},
        ),
    )

    t.check(
        "PUT zero vehicle ID returns 400",
        lambda: t.expect(
            "PUT", f"{root}/0", 400,
            data={"make": "Invalid"},
        ),
    )

    t.check(
        "GET current location without pings returns 204",
        lambda: t.expect(
            "GET", path + "/current-location", 204,
        ),
    )

    t.check(
        "DELETE created vehicle",
        lambda: t.expect(
            "DELETE", path, 200,
            verify=verify_field(
                "vehicle_id", vehicle_id
            ),
        ),
    )

    t.check(
        "GET deleted vehicle returns 404",
        lambda: t.expect(
            "GET", path, 404,
        ),
    )

    t.check(
        "DELETE same vehicle again returns 404",
        lambda: t.expect(
            "DELETE", path, 404,
        ),
    )

    t.check(
        "DELETE zero vehicle ID returns 400",
        lambda: t.expect(
            "DELETE", f"{root}/0", 400,
        ),
    )


def assert_vehicle_in_list(body, vehicle_id):
    assert any(
        item["vehicle_id"] == vehicle_id
        for item in body["items"]
    ), f"Vehicle {vehicle_id} not found in filtered list"


# =========================================================
# Main execution
# =========================================================

def main():
    parser = argparse.ArgumentParser(
        description="Complete Car Tracking API integration tests"
    )

    parser.add_argument(
        "--confirm-isolated-test-db",
        action="store_true",
        help="Required confirmation for CRUD testing",
    )

    args = parser.parse_args()

    if not args.confirm_isolated_test_db:
        print(
            "ERROR: CRUD tests require explicit confirmation.\n"
            "Run:\n"
            "python test_car_tracking_api.py "
            "--confirm-isolated-test-db"
        )
        return 2

    print("=" * 60)
    print("CAR TRACKING API - COMPLETE INTEGRATION TEST SUITE")
    print("=" * 60)
    print("API:", BASE_URL)
    print("Database:", TEST_DB)
    print("Methods: GET, POST, PUT, DELETE")

    tester = Tester(BASE_URL)

    try:
        verify_isolation()

        status, spec = tester.request(
            "GET", "/openapi.json"
        )

        if status != 200:
            raise RuntimeError(
                f"FastAPI unavailable: HTTP {status}"
            )

        if not isinstance(spec, dict):
            raise RuntimeError("Invalid OpenAPI response")

        required_routes = {
            "/api/v1/drivers": {"get", "post"},
            "/api/v1/drivers/{driver_id}": {
                "get", "put", "delete"
            },
            "/api/v1/vehicles": {"get", "post"},
            "/api/v1/vehicles/{vehicle_id}": {
                "get", "put", "delete"
            },
            "/api/v1/vehicles/{vehicle_id}/current-location": {
                "get"
            },
        }

        paths = spec.get("paths", {})

        for path, methods in required_routes.items():
            actual = set(paths.get(path, {}))
            missing = methods - actual

            if missing:
                raise RuntimeError(
                    f"Missing endpoint methods for {path}: "
                    f"{sorted(missing)}"
                )

        username = get_postgres_user()

        with tempfile.TemporaryDirectory() as directory:
            backup_path = (
                Path(directory) / "cartracking_test.dump"
            )

            backup_database(backup_path, username)

            # No write tests are performed until
            # the backup has completed successfully.
            try:
                test_read_only(tester)
                test_driver_crud(tester)
                test_vehicle_crud(tester)

            finally:
                # Attempt restoration even if a test fails.
                restore_database(backup_path, username)

    except Exception as error:
        print(f"\n[FATAL] {error}")
        return 2

    print("\n" + "=" * 60)
    print("FINAL TEST RESULTS")
    print("=" * 60)

    print(f"Passed:  {tester.passed}")
    print(f"Failed:  {tester.failed}")
    print(f"Skipped: {tester.skipped}")

    total = (
        tester.passed
        + tester.failed
        + tester.skipped
    )

    print(f"Total:   {total}")
    print("=" * 60)

    if tester.failed:
        print("RESULT: SOME TESTS FAILED")
        return 1

    print("RESULT: ALL EXECUTED TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
