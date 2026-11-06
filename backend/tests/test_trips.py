"""Issue #23 Trip API integration tests.

Run after starting the isolated backend-test service on localhost:8001,
connected to cartracking_test (NEVER production):
    python -m unittest discover -s backend/tests -p test_trips.py -v
"""

import json
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8001/api/v1"
START = {"type": "Point", "coordinates": [-67.14, 18.21]}
END = {"type": "Point", "coordinates": [-67.13, 18.22]}


def request(method="GET", path="/trips", payload=None, params=None, raw=None):
    url = BASE + path + ("?" + urlencode(params) if params else "")
    body = (raw.encode() if raw is not None else
            json.dumps(payload).encode() if payload is not None else None)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as response:
            status, content = response.status, response.read()
    except HTTPError as error:
        status, content = error.code, error.read()
    return status, json.loads(content.decode()) if content else None


class TripIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            status, data = request(params={"limit": 1, "offset": 0})
        except (URLError, TimeoutError) as exc:
            raise RuntimeError("Start backend-test on port 8001 against cartracking_test") from exc
        if status != 200 or data.get("count", 0) < 1 or not data.get("items"):
            raise RuntimeError("Requires populated isolated test DB; refusing to proceed")
        cls.original_count = data["count"]
        cls.existing_trip = data["items"][0]["trip_id"]
        cls.vehicle_id = data["items"][0]["vehicle_id"]

    def payload(self, **changes):
        data = {
            "vehicle_id": self.vehicle_id,
            "start_ts": "2031-01-01T10:00:00Z",
            "end_ts": "2031-01-01T10:30:00Z",
            "start_geom": START,
            "end_geom": END,
            "distance_km": 2.5,
        }
        data.update(changes)
        return data

    def create(self, **changes):
        status, data = request("POST", payload=self.payload(**changes))
        self.assertEqual(status, 201, data)
        self.assertIsInstance(data.get("trip_id"), int)
        return data

    def cleanup(self, trip_id):
        if trip_id is not None:
            status, data = request("DELETE", f"/trips/{trip_id}")
            self.assertIn(status, (200, 404), data)

    def assert_error(self, status_expected, method="GET", path="/trips", payload=None, params=None, raw=None):
        status, data = request(method, path, payload, params, raw)
        self.assertEqual(status, status_expected, data)
        self.assertIsInstance(data, dict)
        self.assertIn("detail", data)

    def test_01_listing_pagination(self):
        status, data = request(params={"limit": 5, "offset": 0})
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], self.original_count)
        self.assertEqual(len(data["items"]), 5)
        self.assertEqual((data["limit"], data["offset"]), (5, 0))
        self.assertNotIn("start_geom", data["items"][0])
        status, page = request(params={"limit": 5, "offset": 5})
        self.assertEqual(status, 200)
        self.assertTrue(set(x["trip_id"] for x in data["items"]).isdisjoint(
            x["trip_id"] for x in page["items"]))

    def test_02_get_by_id_geojson(self):
        status, data = request(path=f"/trips/{self.existing_trip}")
        self.assertEqual(status, 200)
        self.assertEqual(data["trip_id"], self.existing_trip)
        for field in ("start_geom", "end_geom"):
            if data[field] is not None:
                self.assertEqual(data[field]["type"], "Point")
                self.assertEqual(len(data[field]["coordinates"]), 2)

    def test_03_vehicle_history(self):
        path = f"/vehicles/{self.vehicle_id}/trips"
        status, data = request(path=path, params={"limit": 5, "offset": 0})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["vehicle_id"], self.vehicle_id)
        self.assertTrue(all(i["vehicle_id"] == self.vehicle_id for i in data["items"]))
        self.assertLessEqual(len(data["items"]), 5)

    def test_04_create_read_update_delete_with_points(self):
        trip_id = None
        try:
            created = self.create()
            trip_id = created["trip_id"]
            self.assertEqual(created["start_geom"], START)
            self.assertEqual(created["end_geom"], END)
            status, read = request(path=f"/trips/{trip_id}")
            self.assertEqual(status, 200)
            self.assertEqual(read["distance_km"], 2.5)
            status, updated = request("PUT", f"/trips/{trip_id}", {
                "end_ts": "2031-01-01T10:45:00Z", "distance_km": 3.75,
                "end_geom": {"type": "Point", "coordinates": [-67.12, 18.23]},
            })
            self.assertEqual(status, 200, updated)
            self.assertEqual(updated["distance_km"], 3.75)
            self.assertEqual(updated["end_geom"]["coordinates"], [-67.12, 18.23])
            self.assertEqual(updated["start_geom"], START)
            status, deleted = request("DELETE", f"/trips/{trip_id}")
            self.assertEqual(status, 200, deleted)
            self.assertEqual(deleted["trip_id"], trip_id)
            trip_id = None
            self.assert_error(404, path=f"/trips/{deleted['trip_id']}")
        finally:
            self.cleanup(trip_id)

    def test_05_optional_values_and_timestamp_normalization(self):
        trip_id = None
        try:
            created = self.create(start_ts="2031-01-01T06:00:00-04:00",
                                  end_ts="2031-01-01T10:30:00Z",
                                  start_geom=None, end_geom=None, distance_km=None)
            trip_id = created["trip_id"]
            self.assertEqual(created["start_ts"], "2031-01-01T10:00:00Z")
            self.assertIsNone(created["start_geom"])
            self.assertIsNone(created["distance_km"])
        finally:
            self.cleanup(trip_id)

    def test_06_filter_by_vehicle_and_time(self):
        trip_id = None
        try:
            created = self.create()
            trip_id = created["trip_id"]
            status, data = request(params={
                "vehicle_id": self.vehicle_id,
                "from_ts": "2031-01-01T09:00:00Z",
                "to_ts": "2031-01-01T11:00:00Z",
                "limit": 100,
            })
            self.assertEqual(status, 200, data)
            self.assertIn(trip_id, [x["trip_id"] for x in data["items"]])
            self.assertTrue(all(x["vehicle_id"] == self.vehicle_id for x in data["items"]))
            status, history = request(path=f"/vehicles/{self.vehicle_id}/trips", params={
                "from_ts": "2031-01-01T09:00:00Z",
                "to_ts": "2031-01-01T11:00:00Z",
            })
            self.assertEqual(status, 200, history)
            self.assertIn(trip_id, [x["trip_id"] for x in history["items"]])
        finally:
            self.cleanup(trip_id)

    def test_07_invalid_create_requests(self):
        base = self.payload()
        for changes, expected in [
            ({"end_ts": "2031-01-01T09:00:00Z"}, 400),
            ({"end_ts": "2031-01-01T10:00:00Z"}, 400),
            ({"distance_km": -5}, 400),
            ({"vehicle_id": 999999}, 404),
            ({"start_geom": {"type": "Point", "coordinates": [200, 18.21]}}, 400),
            ({"start_geom": {"type": "Polygon", "coordinates": [-67.14, 18.21]}}, 400),
        ]:
            with self.subTest(changes=changes):
                self.assert_error(expected, "POST", payload={**base, **changes})
        self.assert_error(400, "POST", payload={"vehicle_id": self.vehicle_id})
        self.assert_error(400, "POST", raw='{"vehicle_id":')

    def test_08_invalid_queries_and_ids(self):
        for params in [
            {"offset": -1}, {"limit": -1}, {"vehicle_id": 0},
            {"from_ts": "2031-01-02T00:00:00Z", "to_ts": "2031-01-01T00:00:00Z"},
            {"from_ts": "not-a-date"},
        ]:
            with self.subTest(params=params):
                self.assert_error(400, params=params)
        self.assert_error(404, path="/trips/999999")
        self.assert_error(400, path="/trips/0")
        self.assert_error(400, path="/trips/abc")
        self.assert_error(404, path="/vehicles/999999/trips")

    def test_09_invalid_updates_do_not_change_data(self):
        trip_id = None
        try:
            created = self.create()
            trip_id = created["trip_id"]
            self.assert_error(400, "PUT", f"/trips/{trip_id}", {})
            self.assert_error(400, "PUT", f"/trips/{trip_id}", {"distance_km": -1})
            self.assert_error(422, "PUT", f"/trips/{trip_id}", {
                "end_ts": "2031-01-01T09:59:00Z"
            })
            self.assert_error(404, "PUT", f"/trips/999999", {"distance_km": 1})
            status, unchanged = request(path=f"/trips/{trip_id}")
            self.assertEqual(status, 200)
            self.assertEqual(unchanged["distance_km"], 2.5)
            self.assertEqual(unchanged["end_ts"], "2031-01-01T10:30:00Z")
        finally:
            self.cleanup(trip_id)


if __name__ == "__main__":
    unittest.main()