"""Issue #20 HTTP integration tests for the isolated FastAPI test service.

Run from repository root:
    python -m unittest discover -s backend/tests -p test_vehicle_assignments.py -v

Safety: only contacts http://127.0.0.1:8001, the Docker Compose backend-test
service configured for `cartracking_test`. Never point port 8001 at production.
Each mutable test creates its own row and deletes it in a finally block.
"""

import json
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8001/api/v1/vehicle-assignments"
START = "2026-11-04T12:00:00Z"
END = "2026-11-04T18:00:00Z"
BEFORE = "2026-11-04T11:00:00Z"


def request(method="GET", path="", payload=None, params=None, raw_body=None):
    """Return (HTTP status, parsed JSON) for success and HTTP error responses."""
    url = BASE + path
    if params is not None:
        url += "?" + urlencode(params)
    if raw_body is not None:
        data = raw_body.encode("utf-8")
    elif payload is not None:
        data = json.dumps(payload).encode("utf-8")
    else:
        data = None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as res:
            status, body = res.status, res.read()
    except HTTPError as exc:
        status, body = exc.code, exc.read()
    return status, json.loads(body.decode("utf-8")) if body else None


class VehicleAssignmentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            status, payload = request(params={"limit": 2, "offset": 0})
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(
                "Start the isolated test service: "
                "docker compose --profile test up -d --build backend-test"
            ) from exc
        if status != 200 or not isinstance(payload, dict) or not payload.get("items"):
            raise RuntimeError(
                "The test API must be connected to a populated cartracking_test "
                "database. Refusing to modify an unverified environment."
            )
        cls.initial_count = payload["count"]
        cls.vehicle_id = payload["items"][0]["vehicle_id"]
        cls.driver_id = payload["items"][0]["driver_id"]
        # Extra guard: backend-test must be explicitly configured with DB_NAME.
        # Before running, independently verify compose config if port mappings changed.

    def make_payload(self, **changes):
        result = {
            "vehicle_id": self.vehicle_id,
            "driver_id": self.driver_id,
            "assigned_from": START,
            "assigned_to": None,
        }
        result.update(changes)
        return result

    def create_for_test(self):
        status, data = request("POST", payload=self.make_payload())
        self.assertEqual(status, 201, data)
        self.assertIn("assignment_id", data)
        return data["assignment_id"]

    def delete_if_present(self, assignment_id):
        if assignment_id is not None:
            status, _ = request("DELETE", path=f"/{assignment_id}")
            self.assertIn(status, (200, 404))

    def assert_error(self, method, code, *, path="", payload=None, params=None,
                     raw_body=None, detail=None):
        status, response = request(method, path, payload, params, raw_body)
        self.assertEqual(status, code, response)
        self.assertIsInstance(response, dict)
        self.assertIn("detail", response)
        if detail is not None:
            self.assertEqual(response["detail"], detail)
        return response

    def test_01_listing_and_pagination(self):
        status, result = request(params={"limit": 5, "offset": 0})
        self.assertEqual(status, 200)
        self.assertEqual(result["limit"], 5)
        self.assertEqual(result["offset"], 0)
        self.assertEqual(result["count"], self.initial_count)
        self.assertEqual(len(result["items"]), min(5, result["count"]))
        ids = [entry["assignment_id"] for entry in result["items"]]
        self.assertEqual(ids, sorted(ids))
        status, second = request(params={"limit": 5, "offset": 5})
        self.assertEqual(status, 200)
        self.assertEqual(second["count"], self.initial_count)
        self.assertTrue(set(ids).isdisjoint({e["assignment_id"] for e in second["items"]}))
        status, empty = request(params={"limit": 5, "offset": self.initial_count + 1000})
        self.assertEqual(status, 200)
        self.assertEqual(empty["items"], [])
        self.assertEqual(empty["count"], self.initial_count)

    def test_02_active_closed_and_combined_filters(self):
        status, active = request(params={"active": "true", "limit": 1000})
        self.assertEqual(status, 200)
        self.assertTrue(all(r["assigned_to"] is None for r in active["items"]))
        self.assertEqual(len(active["items"]), active["count"])
        status, closed = request(params={"active": "false", "limit": 1000})
        self.assertEqual(status, 200)
        self.assertTrue(all(r["assigned_to"] is not None for r in closed["items"]))
        self.assertEqual(active["count"] + closed["count"], self.initial_count)
        status, both = request(params={
            "vehicle_id": self.vehicle_id, "driver_id": self.driver_id,
            "active": "true", "limit": 1000,
        })
        self.assertEqual(status, 200)
        self.assertTrue(all(
            r["vehicle_id"] == self.vehicle_id
            and r["driver_id"] == self.driver_id
            and r["assigned_to"] is None
            for r in both["items"]
        ))
        self.assertEqual(len(both["items"]), both["count"])

    def test_03_crud_lifecycle_and_cleanup(self):
        assignment_id = None
        try:
            assignment_id = self.create_for_test()
            status, fetched = request(path=f"/{assignment_id}")
            self.assertEqual(status, 200)
            self.assertEqual(fetched["vehicle_id"], self.vehicle_id)
            self.assertEqual(fetched["driver_id"], self.driver_id)
            self.assertIsNone(fetched["assigned_to"])
            status, updated = request("PUT", f"/{assignment_id}", {"assigned_to": END})
            self.assertEqual(status, 200)
            self.assertEqual(updated["assigned_to"], END)
            status, fetched_again = request(path=f"/{assignment_id}")
            self.assertEqual(status, 200)
            self.assertEqual(fetched_again["assigned_to"], END)
        finally:
            self.delete_if_present(assignment_id)
        self.assert_error("GET", 404, path=f"/{assignment_id}",
                          detail="assignment_id does not exist.")
        status, result = request(params={"limit": 1})
        self.assertEqual(status, 200)
        self.assertEqual(result["count"], self.initial_count)

    def test_04_post_reference_and_interval_validation(self):
        self.assert_error(
            "POST", 404, payload=self.make_payload(vehicle_id=999999),
            detail="Referenced vehicle_id or driver_id does not exist.",
        )
        self.assert_error(
            "POST", 404, payload=self.make_payload(driver_id=999999),
            detail="Referenced vehicle_id or driver_id does not exist.",
        )
        for invalid in (
            self.make_payload(vehicle_id=-1),
            self.make_payload(driver_id=0),
            self.make_payload(assigned_from=None),
            {"vehicle_id": self.vehicle_id},
        ):
            with self.subTest(invalid=invalid):
                self.assert_error(
                    "POST", 400, payload=invalid,
                    detail="Malformed JSON or invalid payload shape.",
                )
        for invalid_timestamp in ("invalid", "1730721600",
                                  "2026-11-04 12:00:00Z",
                                  "2026-11-04T12:00:00"):
            with self.subTest(invalid_timestamp=invalid_timestamp):
                self.assert_error(
                    "POST", 422,
                    payload=self.make_payload(assigned_from=invalid_timestamp),
                    detail="The assignment time interval is invalid.",
                )
        for end in (BEFORE, START):
            self.assert_error(
                "POST", 422, payload=self.make_payload(assigned_to=end),
                detail="The assignment time interval is invalid.",
            )
        self.assert_error(
            "POST", 400, raw_body="{not valid json",
            detail="Malformed JSON or invalid payload shape.",
        )

    def test_05_list_filter_errors(self):
        for params in (
            {"limit": -1}, {"offset": -1}, {"limit": "bad"},
            {"vehicle_id": -1}, {"driver_id": 0}, {"active": "perhaps"},
        ):
            with self.subTest(params=params):
                self.assert_error("GET", 400, params=params,
                                  detail="Invalid query parameter values.")

    def test_06_not_found_and_empty_put(self):
        self.assert_error("GET", 404, path="/999999",
                          detail="assignment_id does not exist.")
        self.assert_error("DELETE", 404, path="/999999",
                          detail="assignment_id does not exist.")
        self.assert_error("PUT", 400, path="/1", payload={})

    def test_07_update_validation_and_no_mutation(self):
        assignment_id = None
        try:
            assignment_id = self.create_for_test()
            for foreign_key in ("vehicle_id", "driver_id"):
                self.assert_error(
                    "PUT", 404, path=f"/{assignment_id}",
                    payload={foreign_key: 999999},
                    detail="assignment_id or a referenced foreign key does not exist.",
                )
            for interval_changes in (
                {"assigned_to": BEFORE},
                {"assigned_from": END, "assigned_to": START},
                {"assigned_to": "2026-11-04 18:00:00Z"},
            ):
                self.assert_error(
                    "PUT", 422, path=f"/{assignment_id}",
                    payload=interval_changes,
                    detail="The resulting assignment interval is invalid.",
                )
            for invalid_changes in (
                {"assigned_from": None},
                {"vehicle_id": None},
                {"driver_id": None},
            ):
                self.assert_error(
                    "PUT", 400, path=f"/{assignment_id}",
                    payload=invalid_changes,
                    detail="Malformed JSON or empty update payload.",
                )
            self.assert_error(
                "PUT", 400, path=f"/{assignment_id}", raw_body="{broken",
                detail="Malformed JSON or empty update payload.",
            )
            status, entry = request(path=f"/{assignment_id}")
            self.assertEqual(status, 200)
            self.assertEqual(entry["assigned_from"], START)
            self.assertIsNone(entry["assigned_to"])
        finally:
            self.delete_if_present(assignment_id)

    def test_08_reopen_assignment_and_utc_normalization(self):
        assignment_id = None
        try:
            payload = self.make_payload(
                assigned_from="2026-11-04T08:00:00-04:00",
                assigned_to=END,
            )
            status, created = request("POST", payload=payload)
            self.assertEqual(status, 201, created)
            assignment_id = created["assignment_id"]
            self.assertEqual(created["assigned_from"], START)
            self.assertEqual(created["assigned_to"], END)
            status, reopened = request("PUT", f"/{assignment_id}", {"assigned_to": None})
            self.assertEqual(status, 200, reopened)
            self.assertIsNone(reopened["assigned_to"])
            status, active = request(params={"active": "true", "limit": 1000})
            self.assertEqual(status, 200)
            self.assertIn(assignment_id, {item["assignment_id"] for item in active["items"]})
        finally:
            self.delete_if_present(assignment_id)

    def test_09_noninteger_and_nonpositive_path_ids(self):
        for invalid_id in ("not-an-id", "0", "-1"):
            for method in ("GET", "PUT", "DELETE"):
                payload = {"assigned_to": END} if method == "PUT" else None
                with self.subTest(invalid_id=invalid_id, method=method):
                    self.assert_error(
                        method, 400, path=f"/{invalid_id}", payload=payload,
                        detail="assignment_id must be a positive integer.",
                    )

    def test_10_openapi_documented_responses(self):
        url = "http://127.0.0.1:8001/openapi.json"
        with urlopen(url, timeout=10) as response:
            spec = json.load(response)
        expected = {
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
        }
        for (path, method), descriptions in expected.items():
            with self.subTest(path=path, method=method):
                actual = {
                    status: response["description"]
                    for status, response in spec["paths"][path][method]["responses"].items()
                }
                self.assertEqual(actual, descriptions)


if __name__ == "__main__":
    unittest.main(verbosity=2)