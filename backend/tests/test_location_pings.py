"""Issue #22 HTTP integration tests for the isolated FastAPI test service.

Run from repository root:
    python -m unittest discover -s backend/tests -p test_location_pings.py -v

Safety: only contacts http://127.0.0.1:8001, the Docker Compose backend-test
service configured for `cartracking_test`. Never point port 8001 at production.
Each mutable test creates its own pings and deletes them in a finally block.
Test pings use a 2031 timestamp and a point east of the Phase 1 data extent so
time-range and bbox filters only match rows created by the test.
"""

import json
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "http://127.0.0.1:8001/api/v1"
BASE = API + "/location-pings"
MISSING_ID = 999999999
TS = "2031-01-01T10:00:00Z"
LON, LAT = -65.5, 18.4
TEST_BBOX = "-65.6,18.3,-65.4,18.5"


def request(method="GET", url=BASE, payload=None, params=None, raw_body=None):
    """Return (HTTP status, parsed JSON) for success and HTTP error responses."""
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


def point(lon=LON, lat=LAT):
    return {"type": "Point", "coordinates": [lon, lat]}


class LocationPingIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            status, payload = request(url=API + "/vehicles", params={"limit": 1})
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(
                "Start the isolated test service: "
                "docker compose --profile test up -d --build backend-test"
            ) from exc
        if status != 200 or not payload.get("items"):
            raise RuntimeError(
                "The test API must be connected to a populated cartracking_test "
                "database. Refusing to modify an unverified environment."
            )
        status, health = request(url=API + "/health/database")
        if status != 200 or health.get("database") != "cartracking_test":
            raise RuntimeError("Port 8001 is not connected to cartracking_test.")
        cls.vehicle_id = payload["items"][0]["vehicle_id"]

    def make_payload(self, **changes):
        result = {
            "vehicle_id": self.vehicle_id,
            "ts": TS,
            "geom": point(),
            "speed_kph": 42.8,
            "heading_deg": 185.4,
        }
        result.update(changes)
        return result

    def create(self, **changes):
        status, data = request("POST", payload=self.make_payload(**changes))
        self.assertEqual(status, 201, data)
        return data

    def delete(self, ping_id):
        request("DELETE", f"{BASE}/{ping_id}")

    # ----- POST /location-pings -----

    def test_create_returns_201_with_geojson_point(self):
        data = self.create()
        try:
            self.assertEqual(
                set(data),
                {"ping_id", "vehicle_id", "ts", "geom", "speed_kph", "heading_deg"},
            )
            self.assertEqual(data["vehicle_id"], self.vehicle_id)
            self.assertEqual(data["ts"], TS)
            self.assertEqual(data["geom"], point())
            self.assertEqual(data["speed_kph"], 42.8)
            self.assertEqual(data["heading_deg"], 185.4)
        finally:
            self.delete(data["ping_id"])

    def test_create_accepts_spec_timestamp_without_offset_as_utc(self):
        data = self.create(ts="2031-01-01T09:58:20")
        try:
            self.assertEqual(data["ts"], "2031-01-01T09:58:20Z")
        finally:
            self.delete(data["ping_id"])

    def test_create_normalizes_offset_to_utc(self):
        data = self.create(ts="2031-01-01T06:00:00-04:00")
        try:
            self.assertEqual(data["ts"], TS)
        finally:
            self.delete(data["ping_id"])

    def test_create_optional_telemetry_may_be_omitted(self):
        payload = self.make_payload()
        del payload["speed_kph"], payload["heading_deg"]
        status, data = request("POST", payload=payload)
        try:
            self.assertEqual(status, 201, data)
            self.assertIsNone(data["speed_kph"])
            self.assertIsNone(data["heading_deg"])
        finally:
            if status == 201:
                self.delete(data["ping_id"])

    def test_create_unknown_vehicle_returns_404(self):
        status, data = request("POST", payload=self.make_payload(vehicle_id=MISSING_ID))
        self.assertEqual(status, 404, data)
        self.assertEqual(data["detail"], "vehicle_id does not exist.")

    def test_create_invalid_payloads_return_400(self):
        missing_ts = self.make_payload()
        del missing_ts["ts"]
        missing_geom = self.make_payload()
        del missing_geom["geom"]
        cases = {
            "missing ts": missing_ts,
            "missing geom": missing_geom,
            "null geom": self.make_payload(geom=None),
            "linestring": self.make_payload(
                geom={"type": "LineString", "coordinates": [[-65.5, 18.4], [-65.4, 18.5]]}
            ),
            "one coordinate": self.make_payload(geom={"type": "Point", "coordinates": [-65.5]}),
            "string coordinate": self.make_payload(geom={"type": "Point", "coordinates": ["a", 18.4]}),
            "longitude out of range": self.make_payload(geom=point(lon=-181)),
            "latitude out of range": self.make_payload(geom=point(lat=91)),
            "negative speed": self.make_payload(speed_kph=-1),
            "heading 360": self.make_payload(heading_deg=360),
            "negative heading": self.make_payload(heading_deg=-0.1),
            "date only ts": self.make_payload(ts="2031-01-01"),
            "invalid ts": self.make_payload(ts="2031-02-30T10:00:00Z"),
            "numeric ts": self.make_payload(ts=1700000000),
            "vehicle_id zero": self.make_payload(vehicle_id=0),
            "array body": [self.make_payload()],
        }
        for name, payload in cases.items():
            with self.subTest(name):
                status, data = request("POST", payload=payload)
                self.assertEqual(status, 400, data)
                self.assertEqual(data["detail"], "Malformed geometry or invalid JSON.")

    def test_create_malformed_json_returns_400(self):
        status, data = request("POST", raw_body='{"vehicle_id": 1,')
        self.assertEqual(status, 400, data)

    # ----- GET /location-pings/{ping_id} -----

    def test_get_by_id(self):
        created = self.create()
        try:
            status, data = request(url=f"{BASE}/{created['ping_id']}")
            self.assertEqual(status, 200, data)
            self.assertEqual(data, created)
        finally:
            self.delete(created["ping_id"])

    def test_get_missing_returns_404(self):
        status, data = request(url=f"{BASE}/{MISSING_ID}")
        self.assertEqual(status, 404, data)
        self.assertEqual(data["detail"], "ping_id does not exist.")

    def test_get_non_positive_or_non_integer_id_returns_400(self):
        for ping_id in ("0", "-1", "abc"):
            with self.subTest(ping_id):
                status, data = request(url=f"{BASE}/{ping_id}")
                self.assertEqual(status, 400, data)

    # ----- PUT /location-pings/{ping_id} -----

    def test_partial_update_changes_only_supplied_fields(self):
        created = self.create()
        try:
            status, data = request(
                "PUT", f"{BASE}/{created['ping_id']}",
                payload={"speed_kph": 45.1, "heading_deg": 190.0},
            )
            self.assertEqual(status, 200, data)
            self.assertEqual(data["speed_kph"], 45.1)
            self.assertEqual(data["heading_deg"], 190.0)
            self.assertEqual(data["ts"], created["ts"])
            self.assertEqual(data["geom"], created["geom"])
        finally:
            self.delete(created["ping_id"])

    def test_full_update_including_geom_and_ts(self):
        created = self.create()
        try:
            changes = {
                "vehicle_id": self.vehicle_id,
                "ts": "2031-01-02T08:30:00Z",
                "geom": point(-65.45, 18.45),
                "speed_kph": 0,
                "heading_deg": 0,
            }
            status, data = request("PUT", f"{BASE}/{created['ping_id']}", payload=changes)
            self.assertEqual(status, 200, data)
            self.assertEqual(data["ts"], changes["ts"])
            self.assertEqual(data["geom"], changes["geom"])
            self.assertEqual(data["speed_kph"], 0)
            self.assertEqual(data["heading_deg"], 0)
            status, stored = request(url=f"{BASE}/{created['ping_id']}")
            self.assertEqual(stored, data)
        finally:
            self.delete(created["ping_id"])

    def test_update_invalid_payloads_return_400(self):
        created = self.create()
        try:
            cases = {
                "empty": {},
                "null ts": {"ts": None},
                "null geom": {"geom": None},
                "null vehicle_id": {"vehicle_id": None},
                "negative speed": {"speed_kph": -5},
                "heading 360": {"heading_deg": 360},
                "polygon": {"geom": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
                "invalid ts": {"ts": "yesterday"},
            }
            for name, payload in cases.items():
                with self.subTest(name):
                    status, data = request("PUT", f"{BASE}/{created['ping_id']}", payload=payload)
                    self.assertEqual(status, 400, data)
                    self.assertEqual(data["detail"], "Malformed JSON or empty patch payload.")
            status, data = request("PUT", f"{BASE}/{created['ping_id']}", raw_body="{bad json")
            self.assertEqual(status, 400, data)
        finally:
            self.delete(created["ping_id"])

    def test_update_missing_ping_or_vehicle_returns_404(self):
        status, data = request("PUT", f"{BASE}/{MISSING_ID}", payload={"speed_kph": 10})
        self.assertEqual(status, 404, data)
        created = self.create()
        try:
            status, data = request(
                "PUT", f"{BASE}/{created['ping_id']}", payload={"vehicle_id": MISSING_ID}
            )
            self.assertEqual(status, 404, data)
            self.assertEqual(data["detail"], "ping_id or referenced vehicle_id does not exist.")
        finally:
            self.delete(created["ping_id"])

    # ----- DELETE /location-pings/{ping_id} -----

    def test_delete_then_404(self):
        created = self.create()
        status, data = request("DELETE", f"{BASE}/{created['ping_id']}")
        self.assertEqual(status, 200, data)
        self.assertEqual(
            data,
            {"message": "Location ping deleted successfully.", "ping_id": created["ping_id"]},
        )
        status, data = request("DELETE", f"{BASE}/{created['ping_id']}")
        self.assertEqual(status, 404, data)
        status, data = request(url=f"{BASE}/{created['ping_id']}")
        self.assertEqual(status, 404, data)

    # ----- GET /location-pings -----

    def test_list_shape_and_pagination(self):
        status, data = request(params={"limit": 3, "offset": 5})
        self.assertEqual(status, 200, data)
        self.assertEqual(set(data), {"items", "limit", "offset", "count"})
        self.assertEqual((data["limit"], data["offset"]), (3, 5))
        self.assertEqual(len(data["items"]), 3)
        self.assertGreaterEqual(data["count"], 28041)
        status, zero = request(params={"limit": 0})
        self.assertEqual(status, 200, zero)
        self.assertEqual(zero["items"], [])
        self.assertEqual(zero["count"], data["count"])

    def test_list_filters_by_vehicle_time_and_bbox(self):
        inside = self.create(ts="2031-01-01T10:00:00Z")
        later = self.create(ts="2031-01-01T12:00:00Z")
        on_edge = self.create(ts="2031-01-01T11:00:00Z", geom=point(-65.6, 18.4))
        outside = self.create(ts="2031-01-01T11:30:00Z", geom=point(-65.0, 18.4))
        created = [inside, later, on_edge, outside]
        ids = lambda payload: [item["ping_id"] for item in payload["items"]]
        try:
            status, data = request(params={"bbox": TEST_BBOX, "limit": 100})
            self.assertEqual(status, 200, data)
            self.assertEqual(ids(data), [inside["ping_id"], later["ping_id"], on_edge["ping_id"]])
            self.assertEqual(data["count"], 3)

            status, data = request(params={
                "vehicle_id": self.vehicle_id,
                "from_ts": "2031-01-01T10:00:00Z",
                "to_ts": "2031-01-01T11:30:00Z",
                "limit": 100,
            })
            self.assertEqual(status, 200, data)
            self.assertEqual(ids(data), [inside["ping_id"], on_edge["ping_id"], outside["ping_id"]])

            status, data = request(params={
                "vehicle_id": self.vehicle_id,
                "from_ts": "2031-01-01T10:30:00Z",
                "to_ts": "2031-01-01T12:00:00Z",
                "bbox": TEST_BBOX,
            })
            self.assertEqual(status, 200, data)
            self.assertEqual(ids(data), [later["ping_id"], on_edge["ping_id"]])
            self.assertTrue(all(item["vehicle_id"] == self.vehicle_id for item in data["items"]))
        finally:
            for ping in created:
                self.delete(ping["ping_id"])

    def test_list_invalid_query_parameters_return_400(self):
        cases = {
            "negative limit": {"limit": -1},
            "text offset": {"offset": "abc"},
            "vehicle_id zero": {"vehicle_id": 0},
            "vehicle_id text": {"vehicle_id": "x"},
            "invalid from_ts": {"from_ts": "not-a-date"},
            "reversed range": {"from_ts": "2031-01-02T00:00:00Z", "to_ts": "2031-01-01T00:00:00Z"},
            "bbox three values": {"bbox": "-65.6,18.3,-65.4"},
            "bbox text": {"bbox": "a,b,c,d"},
            "bbox min above max": {"bbox": "-65.4,18.3,-65.6,18.5"},
            "bbox latitude out of range": {"bbox": "-65.6,18.3,-65.4,91"},
            "bbox longitude out of range": {"bbox": "-181,18.3,-65.4,18.5"},
        }
        for name, params in cases.items():
            with self.subTest(name):
                status, data = request(params=params)
                self.assertEqual(status, 400, data)
                self.assertEqual(data["detail"], "Invalid query parameter values.")

    # ----- GET /vehicles/{vehicle_id}/pings -----

    def test_vehicle_pings_shape_order_and_time_filter(self):
        first = self.create(ts="2031-01-01T10:00:00Z")
        second = self.create(ts="2031-01-01T09:00:00Z")
        try:
            status, data = request(
                url=f"{API}/vehicles/{self.vehicle_id}/pings",
                params={"from_ts": "2031-01-01T00:00:00Z", "to_ts": "2031-01-01T23:59:59Z"},
            )
            self.assertEqual(status, 200, data)
            self.assertEqual(set(data), {"vehicle_id", "items", "limit", "offset", "count"})
            self.assertEqual(data["vehicle_id"], self.vehicle_id)
            self.assertEqual(data["count"], 2)
            self.assertEqual(
                [item["ping_id"] for item in data["items"]],
                [second["ping_id"], first["ping_id"]],
            )
            self.assertEqual(
                set(data["items"][0]), {"ping_id", "ts", "geom", "speed_kph", "heading_deg"}
            )
        finally:
            self.delete(first["ping_id"])
            self.delete(second["ping_id"])

    def test_vehicle_pings_pagination(self):
        status, data = request(
            url=f"{API}/vehicles/{self.vehicle_id}/pings", params={"limit": 2, "offset": 1}
        )
        self.assertEqual(status, 200, data)
        self.assertEqual((data["limit"], data["offset"]), (2, 1))
        self.assertLessEqual(len(data["items"]), 2)

    def test_vehicle_pings_missing_vehicle_returns_404(self):
        status, data = request(url=f"{API}/vehicles/{MISSING_ID}/pings")
        self.assertEqual(status, 404, data)
        self.assertEqual(data["detail"], "vehicle_id does not exist.")

    def test_vehicle_pings_invalid_parameters_return_400(self):
        url = f"{API}/vehicles/{self.vehicle_id}/pings"
        for params in (
            {"limit": -1},
            {"offset": "x"},
            {"from_ts": "bad"},
            {"from_ts": "2031-01-02T00:00:00Z", "to_ts": "2031-01-01T00:00:00Z"},
        ):
            with self.subTest(params):
                status, data = request(url=url, params=params)
                self.assertEqual(status, 400, data)
        for vehicle_id in ("0", "abc"):
            with self.subTest(vehicle_id):
                status, data = request(url=f"{API}/vehicles/{vehicle_id}/pings")
                self.assertEqual(status, 400, data)


if __name__ == "__main__":
    unittest.main()
