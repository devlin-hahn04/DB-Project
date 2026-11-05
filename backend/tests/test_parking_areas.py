"""Issue #21 Parking Area HTTP integration tests.

Run from the repository root after starting backend-test:
    python -m unittest discover -s backend/tests -p test_parking_areas.py -v

Only use the local isolated Docker test service at 127.0.0.1:8001,
configured for the `cartracking_test` database. Mutable tests delete
newly created rows in finally blocks. Never point port 8001 at production.
"""

import json
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8001/api/v1/parking-areas"
POLYGON = {
    "type": "Polygon",
    "coordinates": [[
        [-67.1400, 18.2100],
        [-67.1390, 18.2100],
        [-67.1390, 18.2110],
        [-67.1400, 18.2110],
        [-67.1400, 18.2100],
    ]],
}
UPDATED_POLYGON = {
    "type": "Polygon",
    "coordinates": [[
        [-67.1420, 18.2120],
        [-67.1410, 18.2120],
        [-67.1410, 18.2130],
        [-67.1420, 18.2130],
        [-67.1420, 18.2120],
    ]],
}


def request(method="GET", path="", payload=None, params=None, raw_body=None):
    """Return HTTP status and decoded JSON, including for HTTP errors."""
    url = BASE + path
    if params is not None:
        url += "?" + urlencode(params)
    if raw_body is not None:
        body = raw_body.encode("utf-8")
    elif payload is not None:
        body = json.dumps(payload).encode("utf-8")
    else:
        body = None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as res:
            status, response_body = res.status, res.read()
    except HTTPError as exc:
        status, response_body = exc.code, exc.read()
    return status, json.loads(response_body.decode("utf-8")) if response_body else None


class ParkingAreaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            status, data = request(params={"limit": 1, "offset": 0})
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(
                "Start backend-test on port 8001, configured for cartracking_test: "
                "docker compose --profile test up -d --build backend-test"
            ) from exc
        if (status != 200 or not isinstance(data, dict)
                or data.get("count", 0) < 1 or not data.get("items")):
            raise RuntimeError("Expected a populated isolated test database; refusing to proceed.")
        cls.initial_count = data["count"]
        cls.existing_id = data["items"][0]["parking_area_id"]
        status, detail = request(path=f"/{cls.existing_id}")
        if status != 200 or detail.get("geom", {}).get("type") != "Polygon":
            raise RuntimeError("Test DB must contain existing valid parking polygons.")

    def assert_error(self, method, expected, *, path="", payload=None, params=None,
                     raw_body=None, detail=None):
        status, data = request(method, path, payload, params, raw_body)
        self.assertEqual(status, expected, data)
        self.assertIsInstance(data, dict)
        self.assertIn("detail", data)
        if detail is not None:
            self.assertEqual(data["detail"], detail)
        return data

    def create_test_area(self):
        status, data = request("POST", payload={
            "name": "Integration Test Parking Area", "capacity": 50, "geom": POLYGON,
        })
        self.assertEqual(status, 201, data)
        self.assertIsInstance(data.get("parking_area_id"), int)
        return data

    def cleanup(self, parking_area_id):
        if parking_area_id is not None:
            status, response = request("DELETE", path=f"/{parking_area_id}")
            self.assertIn(status, (200, 404), response)

    def test_01_listing_and_pagination(self):
        status, first = request(params={"limit": 5, "offset": 0})
        self.assertEqual(status, 200)
        self.assertEqual(first["count"], self.initial_count)
        self.assertEqual(first["limit"], 5)
        self.assertEqual(first["offset"], 0)
        self.assertEqual(len(first["items"]), min(5, self.initial_count))
        self.assertTrue(all("geom" not in item for item in first["items"]))
        ids = [item["parking_area_id"] for item in first["items"]]
        self.assertEqual(ids, sorted(ids))

        status, second = request(params={"limit": 5, "offset": 5})
        self.assertEqual(status, 200)
        self.assertEqual(second["count"], self.initial_count)
        self.assertTrue(set(ids).isdisjoint({x["parking_area_id"] for x in second["items"]}))

        status, beyond = request(params={"limit": 5, "offset": self.initial_count + 1000})
        self.assertEqual(status, 200)
        self.assertEqual(beyond["count"], self.initial_count)
        self.assertEqual(beyond["items"], [])

    def test_02_get_by_id_returns_closed_geojson_polygon(self):
        status, item = request(path=f"/{self.existing_id}")
        self.assertEqual(status, 200)
        self.assertEqual(item["parking_area_id"], self.existing_id)
        self.assertEqual(item["geom"]["type"], "Polygon")
        self.assertTrue(item["geom"]["coordinates"])
        for ring in item["geom"]["coordinates"]:
            self.assertGreaterEqual(len(ring), 4)
            self.assertEqual(ring[0], ring[-1])
        self.assertIn("created_at", item)

    def test_03_name_filter_case_insensitive(self):
        status, result = request(params={"name": "pArKiNg_1", "limit": 500})
        self.assertEqual(status, 200)
        self.assertGreater(result["count"], 0)
        self.assertEqual(len(result["items"]), result["count"])
        self.assertTrue(all("parking_1" in item["name"].lower() for item in result["items"]))

    def test_04_bbox_and_combined_filters(self):
        bbox = "-67.15,18.20,-67.12,18.23"
        status, spatial = request(params={"bbox": bbox, "limit": 500})
        self.assertEqual(status, 200)
        self.assertGreater(spatial["count"], 0)
        self.assertEqual(len(spatial["items"]), spatial["count"])

        status, named = request(params={"name": "Parking_1", "limit": 500})
        self.assertEqual(status, 200)
        status, combined = request(params={"name": "Parking_1", "bbox": bbox, "limit": 500})
        self.assertEqual(status, 200)
        spatial_ids = {item["parking_area_id"] for item in spatial["items"]}
        named_ids = {item["parking_area_id"] for item in named["items"]}
        combined_ids = {item["parking_area_id"] for item in combined["items"]}
        self.assertEqual(combined_ids, spatial_ids & named_ids)
        self.assertEqual(combined["count"], len(combined_ids))
        self.assertIn(1, combined_ids)

    def test_05_crud_create_update_geometry_delete(self):
        parking_area_id = None
        try:
            created = self.create_test_area()
            parking_area_id = created["parking_area_id"]
            self.assertEqual(created["capacity"], 50)
            self.assertEqual(created["geom"]["type"], "Polygon")
            self.assertEqual(created["geom"]["coordinates"], POLYGON["coordinates"])
            initial_created_at = created["created_at"]

            status, fetched = request(path=f"/{parking_area_id}")
            self.assertEqual(status, 200)
            self.assertEqual(fetched["name"], "Integration Test Parking Area")

            status, updated = request("PUT", f"/{parking_area_id}", {
                "name": "Updated Integration Parking Area", "capacity": 75,
            })
            self.assertEqual(status, 200, updated)
            self.assertEqual(updated["name"], "Updated Integration Parking Area")
            self.assertEqual(updated["capacity"], 75)
            self.assertEqual(updated["geom"]["coordinates"], POLYGON["coordinates"])
            self.assertEqual(updated["created_at"], initial_created_at)

            status, geom_updated = request("PUT", f"/{parking_area_id}", {
                "geom": UPDATED_POLYGON,
            })
            self.assertEqual(status, 200, geom_updated)
            self.assertEqual(geom_updated["geom"]["coordinates"], UPDATED_POLYGON["coordinates"])

            status, deleted = request("DELETE", f"/{parking_area_id}")
            self.assertEqual(status, 200, deleted)
            self.assertEqual(deleted["parking_area_id"], parking_area_id)
            self.assertEqual(deleted["message"], "Parking area deleted successfully.")
            parking_area_id = None  # Already deleted: no cleanup needed.
            self.assert_error("GET", 404, path=f"/{deleted['parking_area_id']}",
                              detail="parking_area_id does not exist.")
        finally:
            self.cleanup(parking_area_id)

        status, after = request(params={"limit": 1})
        self.assertEqual(status, 200)
        self.assertEqual(after["count"], self.initial_count)

    def test_06_invalid_create_requests(self):
        invalid_open = {
            "type": "Polygon", "coordinates": [[
                [-67.14, 18.21], [-67.139, 18.21],
                [-67.139, 18.211], [-67.14, 18.211],
            ]],
        }
        invalid_range = {
            "type": "Polygon", "coordinates": [[
                [200, 18.21], [201, 18.21], [201, 18.211],
                [200, 18.211], [200, 18.21],
            ]],
        }
        for description, payload in (
            ("empty name", {"name": "", "capacity": 10, "geom": POLYGON}),
            ("whitespace name", {"name": "   ", "capacity": 10, "geom": POLYGON}),
            ("negative capacity", {"name": "Bad", "capacity": -5, "geom": POLYGON}),
            ("open polygon", {"name": "Bad", "capacity": 10, "geom": invalid_open}),
            ("out of range coordinates", {"name": "Bad", "capacity": 10, "geom": invalid_range}),
            ("missing geometry", {"name": "Bad", "capacity": 10}),
            ("wrong geometry type", {"name": "Bad", "capacity": 10,
                                     "geom": {"type": "Point", "coordinates": [-67.14, 18.21]}}),
        ):
            with self.subTest(description=description):
                self.assert_error("POST", 400, payload=payload)
        self.assert_error("POST", 400, raw_body="{invalid json")

    def test_07_invalid_queries(self):
        for params in (
            {"limit": -1}, {"offset": -1}, {"limit": "bad"},
            {"bbox": "-67.12,18.23,-67.15,18.20"},
            {"bbox": "-200,18.20,-67.12,18.23"},
            {"bbox": "abc,18.20,-67.12,18.23"},
            {"bbox": "-67.15,18.20,-67.12"},
        ):
            with self.subTest(params=params):
                self.assert_error("GET", 400, params=params,
                                  detail="Invalid query parameter values.")

    def test_08_not_found_and_invalid_ids(self):
        for method in ("GET", "DELETE"):
            with self.subTest(method=method):
                self.assert_error(method, 404, path="/999999",
                                  detail="parking_area_id does not exist.")
        self.assert_error("PUT", 404, path="/999999", payload={"capacity": 10},
                          detail="parking_area_id does not exist.")
        self.assert_error("GET", 400, path="/0")
        self.assert_error("GET", 400, path="/-1")

    def test_09_invalid_updates_and_no_mutation(self):
        parking_area_id = None
        try:
            created = self.create_test_area()
            parking_area_id = created["parking_area_id"]
            self.assert_error("PUT", 400, path=f"/{parking_area_id}", payload={})
            self.assert_error("PUT", 400, path=f"/{parking_area_id}",
                              payload={"capacity": -10})
            self.assert_error("PUT", 400, path=f"/{parking_area_id}",
                              payload={"name": ""})
            self.assert_error("PUT", 400, path=f"/{parking_area_id}",
                              payload={"geom": None})
            self.assert_error("PUT", 400, path=f"/{parking_area_id}",
                              raw_body="{broken")
            status, unchanged = request(path=f"/{parking_area_id}")
            self.assertEqual(status, 200)
            self.assertEqual(unchanged["name"], created["name"])
            self.assertEqual(unchanged["capacity"], created["capacity"])
            self.assertEqual(unchanged["geom"], created["geom"])
        finally:
            self.cleanup(parking_area_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)