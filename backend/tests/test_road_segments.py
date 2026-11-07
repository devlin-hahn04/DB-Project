import json
import unittest
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "http://127.0.0.1:8001/api/v1"
BASE = API + "/road-segments"
GEOJSON = BASE + "/geojson"
MISSING_ID = 999999999
TEST_BBOX = "-65.6,18.3,-65.4,18.5"

CREATE_ERROR = "Malformed geometry or invalid JSON."
UPDATE_ERROR = "Malformed JSON or empty patch payload."
LIST_ERROR = "Invalid query parameter values."
GEOJSON_FILTER_ERROR = "Invalid or inconsistent filter values."
GEOJSON_PARAM_ERROR = "A query parameter fails type or range validation."


def send(method="GET", url=BASE, payload=None, params=None, raw_body=None):
    """Return (HTTP status, response headers, parsed JSON)."""
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
        with urlopen(req, timeout=15) as res:
            status, response_headers, body = res.status, res.headers, res.read()
    except HTTPError as exc:
        status, response_headers, body = exc.code, exc.headers, exc.read()
    return status, response_headers, json.loads(body.decode("utf-8")) if body else None


def request(*args, **kwargs):
    status, _, data = send(*args, **kwargs)
    return status, data


def line(*points):
    return {"type": "LineString", "coordinates": [list(point) for point in points]}


INSIDE_LINE = line((-65.55, 18.38), (-65.50, 18.40), (-65.45, 18.42))
CROSSING_LINE = line((-65.70, 18.40), (-65.50, 18.40))
OUTSIDE_LINE = line((-65.10, 18.40), (-65.00, 18.45))


class RoadSegmentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            status, health = request(url=API + "/health/database")
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(
                "Start the isolated test service: "
                "docker compose --profile test up -d --build backend-test"
            ) from exc
        if status != 200 or health.get("database") != "cartracking_test":
            raise RuntimeError("Port 8001 is not connected to cartracking_test.")
        status, payload = request(params={"limit": 1})
        if status != 200 or not payload.get("items"):
            raise RuntimeError(
                "The test API must be connected to a populated cartracking_test "
                "database. Refusing to modify an unverified environment."
            )
        cls.initial_count = payload["count"]

    def setUp(self):
        self.token = "ZZTEST-" + uuid.uuid4().hex[:10]

    def make_payload(self, **changes):
        result = {
            "name": f"{self.token} Segment A",
            "speed_limit_kph": 60,
            "is_oneway": True,
            "direction": "forward",
            "geom": INSIDE_LINE,
        }
        result.update(changes)
        return result

    def create(self, **changes):
        status, data = request("POST", payload=self.make_payload(**changes))
        self.assertEqual(status, 201, data)
        return data

    def delete(self, road_id):
        request("DELETE", f"{BASE}/{road_id}")

    # ----- POST /road-segments -----

    def test_create_returns_201_with_full_record(self):
        data = self.create()
        try:
            self.assertEqual(
                set(data),
                {"road_id", "name", "speed_limit_kph", "is_oneway", "direction", "geom", "created_at"},
            )
            self.assertGreater(data["road_id"], 4086)
            self.assertEqual(data["name"], f"{self.token} Segment A")
            self.assertEqual(data["speed_limit_kph"], 60)
            self.assertIs(data["is_oneway"], True)
            self.assertEqual(data["direction"], "forward")
            self.assertEqual(data["geom"], INSIDE_LINE)
            self.assertTrue(data["created_at"].endswith("Z"))
        finally:
            self.delete(data["road_id"])

    def test_create_trims_name_and_allows_optional_fields_to_be_omitted(self):
        status, data = request("POST", payload={"name": f"  {self.token}  ", "geom": INSIDE_LINE})
        try:
            self.assertEqual(status, 201, data)
            self.assertEqual(data["name"], self.token)
            self.assertIsNone(data["speed_limit_kph"])
            self.assertIsNone(data["is_oneway"])
            self.assertIsNone(data["direction"])
        finally:
            if status == 201:
                self.delete(data["road_id"])

    def test_create_generates_unique_ids(self):
        first, second = self.create(), self.create()
        try:
            self.assertNotEqual(first["road_id"], second["road_id"])
        finally:
            self.delete(first["road_id"])
            self.delete(second["road_id"])

    def test_create_invalid_payloads_return_400(self):
        missing_name = self.make_payload()
        del missing_name["name"]
        missing_geom = self.make_payload()
        del missing_geom["geom"]
        cases = {
            "missing name": missing_name,
            "blank name": self.make_payload(name="   "),
            "numeric name": self.make_payload(name=5),
            "missing geom": missing_geom,
            "null geom": self.make_payload(geom=None),
            "point geom": self.make_payload(geom={"type": "Point", "coordinates": [-65.5, 18.4]}),
            "one position": self.make_payload(geom=line((-65.5, 18.4))),
            "repeated position": self.make_payload(geom=line((-65.5, 18.4), (-65.5, 18.4))),
            "three-value position": self.make_payload(
                geom={"type": "LineString", "coordinates": [[-65.5, 18.4, 1], [-65.4, 18.5, 1]]}
            ),
            "string coordinate": self.make_payload(
                geom={"type": "LineString", "coordinates": [["a", 18.4], [-65.4, 18.5]]}
            ),
            "longitude out of range": self.make_payload(geom=line((-181, 18.4), (-65.4, 18.5))),
            "latitude out of range": self.make_payload(geom=line((-65.5, 91), (-65.4, 18.5))),
            "negative speed": self.make_payload(speed_limit_kph=-1),
            "fractional speed": self.make_payload(speed_limit_kph=60.5),
            "invalid direction": self.make_payload(direction="backward"),
            "extra field": self.make_payload(lanes=2),
            "array body": [self.make_payload()],
        }
        for name, payload in cases.items():
            with self.subTest(name):
                status, data = request("POST", payload=payload)
                self.assertEqual(status, 400, data)
                self.assertEqual(data["detail"], CREATE_ERROR)
        status, data = request("POST", raw_body='{"name": "x",')
        self.assertEqual(status, 400, data)
        self.assertEqual(data["detail"], CREATE_ERROR)

    # ----- GET /road-segments/{road_id} -----

    def test_get_by_id_matches_created_record(self):
        created = self.create()
        try:
            status, data = request(url=f"{BASE}/{created['road_id']}")
            self.assertEqual(status, 200, data)
            expected = {
                key: created[key]
                for key in (
                    "road_id",
                    "name",
                    "speed_limit_kph",
                    "geom",
                    "created_at",
                )
            }

            self.assertEqual(set(data), set(expected))
            self.assertEqual(data, expected)
        finally:
            self.delete(created["road_id"])

    def test_get_existing_phase1_road(self):
        status, data = request(url=f"{BASE}/1")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["road_id"], 1)
        self.assertEqual(data["geom"]["type"], "LineString")

    def test_get_missing_returns_404(self):
        status, data = request(url=f"{BASE}/{MISSING_ID}")
        self.assertEqual(status, 404, data)
        self.assertEqual(data["detail"], "road_id does not exist.")

    
    def test_invalid_road_id_returns_exact_400_error(self):
        expected_detail = "road_id must be a positive integer."

        for method, kwargs in (
            ("GET", {}),
            ("PUT", {"payload": {"speed_limit_kph": 50}}),
            ("DELETE", {}),
        ):
            for road_id in ("0", "-1", "abc"):
                with self.subTest(method=method, road_id=road_id):
                    status, data = request(
                        method,
                        f"{BASE}/{road_id}",
                        **kwargs
                    )

                    self.assertEqual(status, 400, data)
                    self.assertEqual(data["detail"], expected_detail)


    # ----- PUT /road-segments/{road_id} -----

    def test_partial_update_changes_only_supplied_field(self):
        created = self.create()
        try:
            status, data = request("PUT", f"{BASE}/{created['road_id']}", payload={"speed_limit_kph": 80})
            self.assertEqual(status, 200, data)
            self.assertEqual(data["speed_limit_kph"], 80)
            for field in ("name", "geom", "created_at"):
                self.assertEqual(data[field], created[field], field)
        finally:
            self.delete(created["road_id"])

    def test_full_update_persists(self):
        created = self.create()
        try:
            changes = {
                "name": f"{self.token} Renamed",
                "speed_limit_kph": 0,
                "is_oneway": False,
                "direction": "both",
                "geom": line((-65.58, 18.35), (-65.42, 18.45)),
            }
            status, data = request("PUT", f"{BASE}/{created['road_id']}", payload=changes)
            self.assertEqual(status, 200, data)
            for field in ("name", "speed_limit_kph", "geom"):
                self.assertEqual(data[field], changes[field], field)
            status, stored = request(url=f"{BASE}/{created['road_id']}")
            self.assertEqual(stored, data)
        finally:
            self.delete(created["road_id"])

    def test_update_invalid_payloads_return_400_without_changes(self):
        created = self.create()
        try:
            cases = {
                "empty": {},
                "null name": {"name": None},
                "blank name": {"name": "  "},
                "null geom": {"geom": None},
                "negative speed": {"speed_limit_kph": -5},
                "invalid direction": {"direction": "north"},
                "polygon geom": {"geom": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
                "extra field": {"lanes": 3},
            }
            for name, payload in cases.items():
                with self.subTest(name):
                    status, data = request("PUT", f"{BASE}/{created['road_id']}", payload=payload)
                    self.assertEqual(status, 400, data)
                    self.assertEqual(data["detail"], UPDATE_ERROR)
            status, data = request("PUT", f"{BASE}/{created['road_id']}", raw_body="{bad json")
            self.assertEqual(status, 400, data)
            self.assertEqual(
                data["detail"],
                "Malformed JSON or empty patch payload."
            )
            status, stored = request(url=f"{BASE}/{created['road_id']}")
            expected = {
                key: created[key]
                for key in (
                    "road_id",
                    "name",
                    "speed_limit_kph",
                    "geom",
                    "created_at",
                )
            }

            self.assertEqual(stored, expected)
        finally:
            self.delete(created["road_id"])

    def test_update_missing_road_returns_404(self):
        status, data = request("PUT", f"{BASE}/{MISSING_ID}", payload={"speed_limit_kph": 50})
        self.assertEqual(status, 404, data)
        self.assertEqual(data["detail"], "road_id does not exist.")

    # ----- DELETE /road-segments/{road_id} -----

    def test_delete_then_404(self):
        created = self.create()
        status, data = request("DELETE", f"{BASE}/{created['road_id']}")
        self.assertEqual(status, 200, data)
        self.assertEqual(
            data, {"message": "Road segment deleted successfully.", "road_id": created["road_id"]}
        )
        
        status, data = request("DELETE", f"{BASE}/{created['road_id']}")
        self.assertEqual(status, 404, data)
        self.assertEqual(
            data["detail"],
            "road_id does not exist."
        )

        status, data = request(url=f"{BASE}/{created['road_id']}")
        self.assertEqual(status, 404, data)
        self.assertEqual(
            data["detail"],
            "road_id does not exist."
        )


    # ----- GET /road-segments -----

    def test_list_shape_pagination_and_zero_limit(self):
        status, data = request(params={"limit": 3, "offset": 5})
        self.assertEqual(status, 200, data)
        self.assertEqual(set(data), {"items", "limit", "offset", "count"})
        self.assertEqual((data["limit"], data["offset"]), (3, 5))
        self.assertEqual([item["road_id"] for item in data["items"]], [6, 7, 8])
        self.assertEqual(
            set(data["items"][0]),
            {"road_id", "name", "speed_limit_kph", "created_at"},
        )
        status, zero = request(params={"limit": 0})
        self.assertEqual(status, 200, zero)
        self.assertEqual(zero["items"], [])
        self.assertEqual(zero["count"], data["count"])

    def test_list_filters_combine_with_and(self):
        inside = self.create(name=f"{self.token} Inside", speed_limit_kph=40)
        crossing = self.create(name=f"{self.token} Crossing", speed_limit_kph=60, geom=CROSSING_LINE)
        outside = self.create(name=f"{self.token} Outside", speed_limit_kph=80, geom=OUTSIDE_LINE)
        ids = lambda payload: [item["road_id"] for item in payload["items"]]
        try:
            status, data = request(params={"name": self.token.lower()})
            self.assertEqual(status, 200, data)
            self.assertEqual(ids(data), [inside["road_id"], crossing["road_id"], outside["road_id"]])

            status, data = request(params={"name": self.token, "min_speed_kph": 50, "max_speed_kph": 80})
            self.assertEqual(ids(data), [crossing["road_id"], outside["road_id"]])

            status, data = request(params={"bbox": TEST_BBOX, "name": self.token})
            self.assertEqual(ids(data), [inside["road_id"], crossing["road_id"]])

            status, data = request(params={
                "bbox": TEST_BBOX, "name": self.token, "min_speed_kph": 50, "max_speed_kph": 70,
            })
            self.assertEqual(ids(data), [crossing["road_id"]])
            self.assertEqual(data["count"], 1)
        finally:
            for road in (inside, crossing, outside):
                self.delete(road["road_id"])

    def test_list_invalid_query_parameters_return_400(self):
        cases = {
            "negative limit": {"limit": -1},
            "text offset": {"offset": "abc"},
            "negative min speed": {"min_speed_kph": -1},
            "text max speed": {"max_speed_kph": "fast"},
            "min above max": {"min_speed_kph": 80, "max_speed_kph": 40},
            "bbox three values": {"bbox": "-65.6,18.3,-65.4"},
            "bbox text": {"bbox": "a,b,c,d"},
            "bbox min above max": {"bbox": "-65.4,18.3,-65.6,18.5"},
            "bbox latitude out of range": {"bbox": "-65.6,18.3,-65.4,91"},
        }
        for name, params in cases.items():
            with self.subTest(name):
                status, data = request(params=params)
                self.assertEqual(status, 400, data)
                self.assertEqual(data["detail"], LIST_ERROR)

    # ----- GET /road-segments/geojson -----

    def test_geojson_feature_collection_contract(self):
        created = self.create()
        try:
            status, headers, data = send(url=GEOJSON, params={"name": self.token})
            self.assertEqual(status, 200, data)
            self.assertTrue(headers["Content-Type"].startswith("application/geo+json"))
            self.assertEqual(set(data), {"type", "count", "limit", "offset", "features"})
            self.assertEqual(data["type"], "FeatureCollection")
            self.assertEqual((data["count"], data["limit"], data["offset"]), (1, 15000, 0))
            feature = data["features"][0]
            self.assertEqual(set(feature), {"type", "geometry", "properties"})
            self.assertEqual(feature["type"], "Feature")
            self.assertEqual(feature["geometry"], INSIDE_LINE)
            self.assertEqual(
                feature["properties"],
                {key: created[key] for key in
                 ("road_id", "name", "speed_limit_kph", "is_oneway", "direction", "created_at")},
            )
        finally:
            self.delete(created["road_id"])

    def test_geojson_filters_and_count_before_pagination(self):
        slow = self.create(speed_limit_kph=30)
        fast = self.create(speed_limit_kph=70)
        try:
            status, data = request(url=GEOJSON, params={
                "name": self.token.lower(), "min_speed_kph": 40, "max_speed_kph": 80,
            })
            self.assertEqual(status, 200, data)
            self.assertEqual([f["properties"]["road_id"] for f in data["features"]], [fast["road_id"]])

            status, data = request(url=GEOJSON, params={"name": self.token, "limit": 1, "offset": 1})
            self.assertEqual(data["count"], 2)
            self.assertEqual(len(data["features"]), 1)
            self.assertEqual(data["features"][0]["properties"]["road_id"], fast["road_id"])
        finally:
            self.delete(slow["road_id"])
            self.delete(fast["road_id"])

    def test_geojson_inconsistent_filters_return_400(self):
        for params in (
            {"bbox": TEST_BBOX},
            {"min_speed_kph": 80, "max_speed_kph": 40},
        ):
            with self.subTest(params):
                status, data = request(url=GEOJSON, params=params)
                self.assertEqual(status, 400, data)
                self.assertEqual(data["detail"], GEOJSON_FILTER_ERROR)

    def test_geojson_type_or_range_errors_return_422(self):
        for params in (
            {"limit": -1},
            {"limit": "many"},
            {"offset": "x"},
            {"min_speed_kph": "slow"},
            {"max_speed_kph": -10},
        ):
            with self.subTest(params):
                status, data = request(url=GEOJSON, params=params)
                self.assertEqual(status, 422, data)
                self.assertEqual(data["detail"], GEOJSON_PARAM_ERROR)

    def test_99_road_count_preserved(self):
        status, data = request(params={"limit": 0})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["count"], self.initial_count)


if __name__ == "__main__":
    unittest.main()
