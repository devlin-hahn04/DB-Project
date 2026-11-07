"""Issue #23 / rubric 5.5: four extra Trip API edge-case checks.

Execute at the project root with the test backend listening on localhost:8001:

  $env:CARTRACKING_E2E_ALLOW_WRITES = "cartracking_test"
  try { python backend/tests/verify_trip_edge_cases.py }
  finally { Remove-Item Env:CARTRACKING_E2E_ALLOW_WRITES -ErrorAction SilentlyContinue }

Only creates and deletes one temporary Trip. Uses existing vehicle IDs read-only.
Never targets the production API or database.
"""
import json
import os
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "http://127.0.0.1:8001/api/v1"
TRIPS = API + "/trips"
VEHICLES = API + "/vehicles"
EXPECTED_400 = "Malformed JSON or empty patch payload."
EXPECTED_MISSING = "trip_id or referenced vehicle_id does not exist."


def request(method, url, *, body=None, raw=None, params=None):
    if params is not None:
        url += "?" + urlencode(params)
    data = raw.encode("utf-8") if raw is not None else (
        json.dumps(body).encode("utf-8") if body is not None else None
    )
    req = Request(url, method=method, data=data,
                  headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urlopen(req, timeout=20) as r:
            status, content = r.status, r.read()
    except HTTPError as e:
        status, content = e.code, e.read()
    return status, json.loads(content) if content else None


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def expect(method, url, status, *, body=None, raw=None, params=None, detail=None):
    code, payload = request(method, url, body=body, raw=raw, params=params)
    require(code == status,
            f"{method} {url}: expected HTTP {status}, got {code}: {payload}")
    if detail is not None:
        require(payload == {"detail": detail},
                f"{method} {url}: expected detail {detail!r}, got {payload!r}")
    return payload


def safety_check():
    require(os.environ.get("CARTRACKING_E2E_ALLOW_WRITES") == "cartracking_test",
            "Refusing writes: set CARTRACKING_E2E_ALLOW_WRITES=cartracking_test")

    config = subprocess.run(
        ["docker", "compose", "--profile", "test", "exec", "-T",
         "backend-test", "printenv", "DB_NAME"],
        capture_output=True, text=True, timeout=20,
    )
    require(config.returncode == 0 and config.stdout.strip() == "cartracking_test",
            f"Refusing writes: backend-test DB_NAME not cartracking_test: {config.stdout} {config.stderr}")

    health = expect("GET", API + "/health/database", 200)
    require(health.get("database") == "cartracking_test",
            f"Refusing writes: API database is {health.get('database')!r}")

    code = (
        "from backend.config.dbconfig import initialize_connection_pool,get_db_connection,close_connection_pool;"
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
    pool = subprocess.run(
        ["docker", "compose", "--profile", "test", "exec", "-T",
         "backend-test", "python", "-c", code],
        capture_output=True, text=True, timeout=30,
    )
    require(pool.returncode == 0 and pool.stdout.strip() == "cartracking_test",
            f"Refusing writes: backend connection pool database unverified: {pool.stdout} {pool.stderr}")
    print("PASS | Safety: env, Docker service, API health, and connection pool all use cartracking_test")


def main():
    safety_check()
    baseline = expect("GET", TRIPS, 200, params={"limit": 0})["count"]
    vehicle_result = expect("GET", VEHICLES, 200, params={"limit": 100, "offset": 0})
    vehicle_ids = list(dict.fromkeys(row["vehicle_id"] for row in vehicle_result["items"]))
    require(len(vehicle_ids) >= 2, "Two existing distinct vehicles required for safe reassignment test")
    original_vehicle_id, new_vehicle_id = vehicle_ids[:2]
    print(f"Baseline Trip count: {baseline}; reassignment vehicles: {original_vehicle_id} -> {new_vehicle_id}")

    new_trip_id = None
    failures = []
    try:
        # Only temporary Trip created. No changes to existing vehicle records.
        created = expect("POST", TRIPS, 201, body={
            "vehicle_id": original_vehicle_id,
            "start_ts": "2035-06-01T08:00:00Z",
            "end_ts": "2035-06-01T08:45:00Z",
            "start_geom": {"type": "Point", "coordinates": [-65.5, 18.4]},
            "end_geom": {"type": "Point", "coordinates": [-65.4, 18.5]},
            "distance_km": 6.7,
        })
        new_trip_id = created["trip_id"]
        url = f"{TRIPS}/{new_trip_id}"
        print(f"Temporary Trip ID: {new_trip_id}")

        # D1: reassignment to another valid vehicle, with persisted read and collection checks.
        updated = expect("PUT", url, 200, body={"vehicle_id": new_vehicle_id})
        require(updated["vehicle_id"] == new_vehicle_id, "PUT did not return reassigned vehicle_id")
        require(expect("GET", url, 200)["vehicle_id"] == new_vehicle_id,
                "Vehicle reassignment was not persisted")
        global_after = expect("GET", TRIPS, 200, params={"vehicle_id": new_vehicle_id, "limit": 10000})
        require(new_trip_id in {x["trip_id"] for x in global_after["items"]},
                "Reassigned Trip missing from new vehicle's global-filtered collection")
        history_after = expect("GET", f"{VEHICLES}/{new_vehicle_id}/trips", 200,
                               params={"limit": 10000})
        require(new_trip_id in {x["trip_id"] for x in history_after["items"]},
                "Reassigned Trip missing from new vehicle's history")
        old_history = expect("GET", f"{VEHICLES}/{original_vehicle_id}/trips", 200,
                             params={"limit": 10000})
        require(new_trip_id not in {x["trip_id"] for x in old_history["items"]},
                "Reassigned Trip still appears in old vehicle's history")
        print("PASS | D1: valid PUT vehicle reassignment persisted and collection membership updated")

        # D2: strict invalid path IDs across GET, PUT and DELETE.
        for bad in ("0", "-1", "abc"):
            expect("GET", f"{TRIPS}/{bad}", 400)
            expect("DELETE", f"{TRIPS}/{bad}", 400)
            expect("PUT", f"{TRIPS}/{bad}", 400, body={"distance_km": 3.5})
        print("PASS | D2: Trip GET/PUT/DELETE reject zero, negative, and noninteger IDs (HTTP 400)")

       # D3: invalid IDs and invalid query params on vehicle Trip history.
        for bad in ("0", "-1", "abc"):
            expect("GET", f"{VEHICLES}/{bad}/trips", 400,
                detail="Invalid query parameters.")

        expect("GET", f"{VEHICLES}/{new_vehicle_id}/trips", 400,
            params={"limit": "-1"}, detail="Invalid query parameters.")

        print("PASS | D3: invalid vehicle history IDs and query params return rubric HTTP 400")
        expect("GET", f"{VEHICLES}/{new_vehicle_id}/trips", 400,
               params={"limit": "-1"}, detail="Invalid query parameters.")
        print("PASS | D3: invalid vehicle history IDs and query params return rubric HTTP 400")

        # D4: malformed raw JSON != syntactically valid empty patch.
        before = expect("GET", url, 200)
        expect("PUT", url, 400, raw="{broken JSON", detail=EXPECTED_400)
        require(expect("GET", url, 200) == before,
                "Malformed PUT unexpectedly mutated temporary Trip")
        expect("PUT", url, 400, body={}, detail=EXPECTED_400)
        require(expect("GET", url, 200) == before,
                "Empty PUT unexpectedly mutated temporary Trip")
        print("PASS | D4: malformed raw JSON and empty patch both return exact HTTP 400 body; no mutation")

    finally:
        if new_trip_id is not None:
            code, deleted = request("DELETE", f"{TRIPS}/{new_trip_id}")
            if code != 200:
                failures.append(f"Failed to delete temporary Trip {new_trip_id}: HTTP {code}: {deleted}")
            else:
                print(f"PASS | Cleanup: temporary Trip {new_trip_id} deleted")
        end_count = expect("GET", TRIPS, 200, params={"limit": 0})["count"]
        if end_count != baseline:
            failures.append(f"Trip count changed: before={baseline}, after={end_count}")
        else:
            print(f"PASS | Preservation: Trip count unchanged ({baseline})")
        if failures:
            raise AssertionError("; ".join(failures))
    print("\nALL ISSUE D CHECKS PASSED (4 cases plus safety and cleanup).")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nFAILED | {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
