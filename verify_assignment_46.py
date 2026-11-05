"""One-time manual-test cleanup for assignment 46 on the isolated API.

Run from the DB-Project root: python verify_assignment_46.py
Requires Docker Compose and the local backend-test service.
"""
import json
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8001/api/v1/vehicle-assignments"
ASSIGNMENT_ID = 46
EXPECTED = {
    "assignment_id": 46,
    "vehicle_id": 1,
    "driver_id": 1,
    "assigned_from": "2026-11-05T12:00:00Z",
    "assigned_to": "2026-11-05T18:00:00Z",
}


def call(method, path="", payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            status, raw = response.status, response.read()
    except HTTPError as error:
        status, raw = error.code, error.read()
    return status, json.loads(raw) if raw else None


def check(label, actual, expected):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")
    print(f"[PASS] {label}")


def main():
    # Confirm the Compose service's DB configuration before ANY modification.
    proc = subprocess.run(
        ["docker", "compose", "--profile", "test", "exec", "-T", "backend-test", "printenv", "DB_NAME"],
        capture_output=True, text=True, timeout=20,
    )
    check("Test backend DB_NAME", (proc.returncode, proc.stdout.strip()), (0, "cartracking_test"))

    status, record = call("GET", f"/{ASSIGNMENT_ID}")
    check("GET temporary assignment status", status, 200)
    check("Temporary assignment identity and original data", record, EXPECTED)

    status, collection = call("GET", "?limit=0")
    check("Initial collection status", status, 200)
    check("Initial assignment count", collection["count"], 43)

    # An empty dict is intentionally sent as JSON, not an absent request body.
    status, result = call("PUT", f"/{ASSIGNMENT_ID}", {})
    check("PUT empty payload status", status, 400)
    check("PUT empty payload exact message", result, {"detail": "Malformed JSON or empty update payload."})

    status, record = call("GET", f"/{ASSIGNMENT_ID}")
    check("GET after rejected empty PUT", status, 200)
    check("Record unchanged after rejected empty PUT", record, EXPECTED)

    status, record = call("PUT", f"/{ASSIGNMENT_ID}", {"assigned_to": None})
    check("Reopen assignment status", status, 200)
    check("Reopened assignment response", record, {**EXPECTED, "assigned_to": None})

    status, record = call("GET", f"/{ASSIGNMENT_ID}")
    check("GET reopened assignment", status, 200)
    check("Reopening persisted", record, {**EXPECTED, "assigned_to": None})

    # This deletes ONLY the verified temporary assignment 46.
    status, result = call("DELETE", f"/{ASSIGNMENT_ID}")
    check("DELETE temporary assignment status", status, 200)
    check("DELETE exact response", result, {
        "message": "Vehicle assignment deleted successfully.",
        "assignment_id": ASSIGNMENT_ID,
    })

    status, result = call("GET", f"/{ASSIGNMENT_ID}")
    check("GET after DELETE status", status, 404)
    check("GET after DELETE exact message", result, {"detail": "assignment_id does not exist."})

    status, collection = call("GET", "?limit=0")
    check("Final collection status", status, 200)
    check("Final assignment count", collection["count"], 42)
    print("\nALL CHECKS PASSED — temporary Assignment 46 removed; original 42 remain.")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, URLError, OSError, subprocess.TimeoutExpired, ValueError, KeyError) as error:
        print(f"\n[STOPPED] {error}", file=sys.stderr)
        print("Review the state of Assignment 46 before rerunning.", file=sys.stderr)
        sys.exit(1)
