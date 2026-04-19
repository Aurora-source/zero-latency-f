from __future__ import annotations

import os
import runpy
import asyncio
import sys
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from shapely.geometry import LineString


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTING_MAIN = REPO_ROOT / "services" / "routing-engine" / "main.py"
DATA_MAIN = REPO_ROOT / "services" / "data-service" / "main.py"
API_KEY_MANAGER_MAIN = REPO_ROOT / "services" / "data-service" / "api_key_manager.py"
TILE_LOADER_MAIN = REPO_ROOT / "services" / "data-service" / "tile_loader.py"
MAP_VIEW = REPO_ROOT / "services" / "visualization" / "app" / "components" / "MapView.tsx"
APP_VIEW = REPO_ROOT / "services" / "visualization" / "app" / "App.tsx"


def load_module(path: Path) -> dict[str, object]:
    module_dir = str(path.parent)
    inserted = False
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
        inserted = True
    try:
        return runpy.run_path(str(path))
    finally:
        if inserted:
            sys.path.remove(module_dir)


class RoutingModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.routing = load_module(ROUTING_MAIN)

    def test_fastest_prefers_travel_time_not_shortest_distance(self) -> None:
        compute_scalar_route_cost = self.routing["compute_scalar_route_cost"]

        short_slow = {
            "length": 800.0,
            "road_type": "residential",
            "surface_type": "paved",
            "mid_lat": 12.98,
            "mid_lon": 77.60,
        }
        long_fast = {
            "length": 1500.0,
            "road_type": "motorway",
            "surface_type": "paved",
            "mid_lat": 12.99,
            "mid_lon": 77.62,
        }

        short_cost, _ = compute_scalar_route_cost("bangalore", short_slow, "fastest", "car", 0.8, hour=14)
        long_cost, _ = compute_scalar_route_cost("bangalore", long_fast, "fastest", "car", 0.8, hour=14)

        self.assertLess(
            long_cost,
            short_cost,
            "Fastest mode should prefer lower travel time even when the route is longer.",
        )

    def test_connected_mode_penalizes_low_connectivity_more_than_balanced(self) -> None:
        compute_scalar_route_cost = self.routing["compute_scalar_route_cost"]

        edge = {
            "length": 1200.0,
            "road_type": "primary",
            "surface_type": "paved",
            "mid_lat": 12.97,
            "mid_lon": 77.61,
        }

        fastest_cost, _ = compute_scalar_route_cost("bangalore", edge, "fastest", "car", 0.2, hour=14)
        balanced_cost, _ = compute_scalar_route_cost("bangalore", edge, "balanced", "car", 0.2, hour=14)
        connected_cost, _ = compute_scalar_route_cost("bangalore", edge, "connected", "car", 0.2, hour=14)
        connected_good_cost, _ = compute_scalar_route_cost("bangalore", edge, "connected", "car", 0.85, hour=14)

        self.assertLess(fastest_cost, balanced_cost)
        self.assertLess(balanced_cost, connected_cost)
        self.assertLess(connected_good_cost, connected_cost)

    def test_require_graph_state_rejects_unloaded_graphs(self) -> None:
        require_graph_state = self.routing["require_graph_state"]
        graph_cache = self.routing["GRAPH_CACHE"]
        graph_status = self.routing["GRAPH_STATUS"]

        graph_cache.clear()
        graph_status.clear()
        graph_status["bangalore"] = "idle"

        with self.assertRaises(Exception) as exc_info:
            require_graph_state("bangalore")

        self.assertEqual(getattr(exc_info.exception, "status_code", None), 503)


class CachePersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.routing = load_module(ROUTING_MAIN)
        cls.data = load_module(DATA_MAIN)

    def test_route_cache_persists_and_invalidates(self) -> None:
        route_cache = self.routing["ROUTE_CACHE"]
        route_cache_path_key = "ROUTE_CACHE_PATH"
        store_cached_route = self.routing["store_cached_route"]
        load_route_cache = self.routing["load_route_cache"]
        get_cached_route = self.routing["get_cached_route"]
        route_cache_ttl = int(self.routing["ROUTE_CACHE_TTL_SECONDS"])

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir) / "route_cache.json"
            self.routing[route_cache_path_key] = temp_path
            route_cache.clear()

            response = {"mode": "balanced", "total_time_min": 12.4}
            store_cached_route(
                "bangalore",
                (12.9716, 77.5946),
                (13.0467, 77.7582),
                "balanced",
                "car",
                10.0,
                response,
            )

            route_cache.clear()
            load_route_cache()
            cached = get_cached_route(
                "bangalore",
                (12.9716, 77.5946),
                (13.0467, 77.7582),
                "balanced",
                "car",
                10.0,
            )
            self.assertEqual(cached, response)

            cache_key = self.routing["route_cache_key"](
                "bangalore",
                (12.9716, 77.5946),
                (13.0467, 77.7582),
                "balanced",
                "car",
            )
            route_cache[cache_key]["stored_at"] = time.time() - route_cache_ttl - 1
            self.assertIsNone(
                get_cached_route(
                    "bangalore",
                    (12.9716, 77.5946),
                    (13.0467, 77.7582),
                    "balanced",
                    "car",
                    10.0,
                )
            )

    def test_hotspot_cache_persists_and_reuses_viewport_payload(self) -> None:
        hotspot_cache = self.data["HOTSPOT_CACHE"]
        hotspot_cache_path_key = "HOTSPOT_CACHE_PATH"
        store_cached_hotspots = self.data["store_cached_hotspots"]
        load_hotspot_cache = self.data["load_hotspot_cache"]
        get_cached_hotspots = self.data["get_cached_hotspots"]

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir) / "hotspots.json"
            self.data[hotspot_cache_path_key] = temp_path
            hotspot_cache.clear()
            payload = [{"id": "seg-1", "lat": 12.97, "lon": 77.59, "score": 0.2}]

            store_cached_hotspots("bangalore", 12.9, 77.5, 13.0, 77.7, 12, payload)
            hotspot_cache.clear()
            load_hotspot_cache()

            cached = get_cached_hotspots("bangalore", 12.9, 77.5, 13.0, 77.7, 12)
            self.assertEqual(cached, payload)

    def test_tower_cache_status_initializes_sqlite_grid(self) -> None:
        persistent_cache_status = self.data["persistent_cache_status"]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tower_cache.db"
            payload = persistent_cache_status(db_path, "bangalore")

            self.assertTrue(db_path.exists())
            self.assertGreater(int(payload["total_tiles"]), 0)
            self.assertEqual(int(payload["cached_tiles"]), 0)
            self.assertEqual(int(payload["remaining_tiles"]), int(payload["total_tiles"]))


class LocalTowerSourceTests(unittest.TestCase):
    def test_local_tower_source_filters_bbox_and_serves_bbox_queries(self) -> None:
        tile_loader = load_module(TILE_LOADER_MAIN)
        load_local_tower_source = tile_loader["load_local_tower_source"]
        local_towers_for_bbox = tile_loader["local_towers_for_bbox"]

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "towers_bangalore.csv"
            csv_path.write_text(
                "radio,mcc,net,area,cell,lon,lat,range\n"
                "LTE,404,45,100,1,77.5946,12.9716,500\n"
                "LTE,404,45,101,2,77.7000,13.0500,750\n"
                "LTE,404,45,102,3,78.1000,14.0000,900\n",
                encoding="utf-8",
            )

            source = load_local_tower_source(csv_path, logger=lambda message: None)
            towers = local_towers_for_bbox(12.95, 77.58, 12.99, 77.61)

        self.assertIsNotNone(source)
        self.assertEqual(int(source["count"]), 2)
        self.assertEqual(len(towers or []), 1)
        self.assertAlmostEqual(float(towers[0]["lat"]), 12.9716, places=4)


class APIKeyManagerTests(unittest.TestCase):
    def test_api_key_manager_rotates_and_persists_state(self) -> None:
        module = load_module(API_KEY_MANAGER_MAIN)
        APIKeyManager = module["APIKeyManager"]

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            state_path = Path(tmpdir) / "api_key_state.json"
            env_path.write_text("OPENCELLID_KEYS=key1,key2,key3\n", encoding="utf-8")

            with patch.dict(os.environ, {"OPENCELLID_KEYS": "", "OPENCELLID_TOKEN": ""}, clear=False):
                manager = APIKeyManager(env_path=env_path, state_path=state_path, logger=lambda message: None)
                self.assertEqual(manager.status()["active_key"], 1)
                self.assertEqual(manager.get_current_key(), "key1")

                manager.mark_current_exhausted(reason="quota")
                self.assertEqual(manager.status()["active_key"], 2)
                self.assertEqual(manager.status()["exhausted_keys"], [1])

                reloaded = APIKeyManager(env_path=env_path, state_path=state_path, logger=lambda message: None)
                self.assertEqual(reloaded.status()["active_key"], 2)
                self.assertEqual(reloaded.status()["exhausted_keys"], [1])

    def test_tile_loader_rotates_keys_on_runtime_quota_exception(self) -> None:
        tile_loader = load_module(TILE_LOADER_MAIN)
        fetch_tower_chunk = tile_loader["fetch_tower_chunk"]
        globals_dict = fetch_tower_chunk.__globals__
        module = load_module(API_KEY_MANAGER_MAIN)
        APIKeyManager = module["APIKeyManager"]

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            state_path = Path(tmpdir) / "api_key_state.json"
            env_path.write_text("OPENCELLID_KEYS=key1,key2\n", encoding="utf-8")
            with patch.dict(os.environ, {"OPENCELLID_KEYS": "", "OPENCELLID_TOKEN": ""}, clear=False):
                manager = APIKeyManager(env_path=env_path, state_path=state_path, logger=lambda message: None)

                async def fake_size(*args, **kwargs):
                    token = kwargs["token"]
                    if token == "key1":
                        raise RuntimeError("OpenCellID size error: Daily limit 5000 requests exceeded")
                    return 0

                with patch.dict(
                    globals_dict,
                    {
                        "fetch_area_size": fake_size,
                    },
                ):
                    towers = asyncio.run(
                        fetch_tower_chunk(
                            client=None,
                            chunk_bbox=(12.95, 77.58, 12.99, 77.63),
                            chunk_number=1,
                            key_manager=manager,
                        )
                    )

        self.assertEqual(towers, [])
        self.assertEqual(manager.status()["active_key"], 2)
        self.assertEqual(manager.status()["exhausted_keys"], [1])


class BangaloreDefaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.routing = load_module(ROUTING_MAIN)
        cls.data = load_module(DATA_MAIN)

    def test_default_supported_city_is_bangalore_only(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SUPPORTED_CITIES", None)
            self.assertEqual(self.routing["supported_cities"](), ["bangalore"])
            self.assertEqual(self.data["supported_cities"](), ["bangalore"])

    def test_bangalore_uses_single_place_query_and_shared_graphml_cache(self) -> None:
        self.assertEqual(
            self.routing["place_query"]("bangalore"),
            "Bangalore, Karnataka, India",
        )
        self.assertEqual(
            self.data["place_query"]("bangalore"),
            "Bangalore, Karnataka, India",
        )
        self.assertTrue(str(self.routing["graph_cache_path"]("bangalore")).endswith("bangalore.graphml"))
        self.assertTrue(str(self.data["graph_cache_path"]("bangalore")).endswith("bangalore.graphml"))

    def test_data_service_retries_overpass_fallbacks_with_timeout(self) -> None:
        load_or_fetch_graph = self.data["load_or_fetch_graph"]
        globals_dict = load_or_fetch_graph.__globals__
        original_graph_cache_dir = globals_dict["GRAPH_CACHE_DIR"]
        original_http_cache_dir = globals_dict["OSMNX_HTTP_CACHE_DIR"]
        attempts: list[tuple[str, float]] = []

        def fake_graph_from_polygon(*args, **kwargs):
            attempts.append(
                (
                    str(globals_dict["ox"].settings.overpass_url),
                    float(globals_dict["ox"].settings.requests_timeout),
                )
            )
            if len(attempts) == 1:
                raise TimeoutError("primary endpoint timed out")
            return {"graph": "ok"}

        with tempfile.TemporaryDirectory() as tmpdir:
            globals_dict["GRAPH_CACHE_DIR"] = Path(tmpdir)
            globals_dict["OSMNX_HTTP_CACHE_DIR"] = Path(tmpdir) / "osmnx-http"
            try:
                with patch.dict(
                    globals_dict,
                    {
                        "configured_overpass_urls": lambda: [
                            "https://overpass-api.de/api",
                            "https://overpass.private.coffee/api",
                        ],
                        "load_local_graph_fallback": lambda city: None,
                        "geocode_place_boundary": lambda city: "polygon",
                        "simplify_city_graph": lambda city, graph: graph,
                    },
                ), patch.object(
                    globals_dict["ox"],
                    "graph_from_polygon",
                    side_effect=fake_graph_from_polygon,
                ), patch.object(globals_dict["ox"], "save_graphml"):
                    graph = load_or_fetch_graph("bangalore")
            finally:
                globals_dict["GRAPH_CACHE_DIR"] = original_graph_cache_dir
                globals_dict["OSMNX_HTTP_CACHE_DIR"] = original_http_cache_dir

        self.assertEqual(graph, {"graph": "ok"})
        self.assertEqual(
            attempts,
            [
                ("https://overpass-api.de/api", 60.0),
                ("https://overpass.private.coffee/api", 60.0),
            ],
        )

    def test_geocode_place_boundary_disables_proxy_env(self) -> None:
        geocode_place_boundary = self.data["geocode_place_boundary"]
        globals_dict = geocode_place_boundary.__globals__

        class DummyGeometry:
            def union_all(self):
                return "polygon"

            @property
            def unary_union(self):
                return "polygon"

        class DummyGdf:
            empty = False
            geometry = DummyGeometry()

        observed: dict[str, str | None] = {}

        def fake_geocode_to_gdf(place_name: str):
            observed["place"] = place_name
            observed["HTTP_PROXY"] = os.environ.get("HTTP_PROXY")
            observed["HTTPS_PROXY"] = os.environ.get("HTTPS_PROXY")
            observed["ALL_PROXY"] = os.environ.get("ALL_PROXY")
            return DummyGdf()

        with patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "http://127.0.0.1:9",
                "HTTPS_PROXY": "http://127.0.0.1:9",
                "ALL_PROXY": "http://127.0.0.1:9",
            },
            clear=False,
        ), patch.object(globals_dict["ox"], "geocode_to_gdf", side_effect=fake_geocode_to_gdf):
            polygon = geocode_place_boundary("bangalore")

        self.assertEqual(polygon, "polygon")
        self.assertEqual(observed["place"], "Bangalore, Karnataka, India")
        self.assertIsNone(observed["HTTP_PROXY"])
        self.assertIsNone(observed["HTTPS_PROXY"])
        self.assertIsNone(observed["ALL_PROXY"])

    def test_data_service_preload_sets_error_after_final_failure(self) -> None:
        schedule_preload = self.data["schedule_preload"]
        globals_dict = schedule_preload.__globals__
        graph_cache = self.data["GRAPH_CACHE"]
        graph_status = self.data["GRAPH_STATUS"]
        graph_errors = self.data["GRAPH_ERRORS"]
        preload_threads = self.data["PRELOAD_THREADS"]

        graph_cache.clear()
        graph_status.clear()
        graph_errors.clear()
        preload_threads.clear()

        def fail_load(city: str) -> None:
            raise RuntimeError("all Overpass endpoints failed")

        with patch.dict(globals_dict, {"load_city_state": fail_load}):
            status = schedule_preload("bangalore")
            self.assertEqual(status, "loading")
            deadline = time.time() + 2.0
            while graph_status.get("bangalore") == "loading" and time.time() < deadline:
                time.sleep(0.05)

        self.assertEqual(graph_status.get("bangalore"), "error")
        self.assertIn("all Overpass endpoints failed", graph_errors.get("bangalore", ""))

    def test_data_service_preload_deduplicates_inflight_requests(self) -> None:
        schedule_preload = self.data["schedule_preload"]
        globals_dict = schedule_preload.__globals__
        graph_cache = self.data["GRAPH_CACHE"]
        graph_status = self.data["GRAPH_STATUS"]
        graph_errors = self.data["GRAPH_ERRORS"]
        preload_threads = self.data["PRELOAD_THREADS"]

        graph_cache.clear()
        graph_status.clear()
        graph_errors.clear()
        preload_threads.clear()

        release = threading.Event()

        def blocking_load(city: str) -> None:
            release.wait(0.3)

        with patch.dict(globals_dict, {"load_city_state": blocking_load}):
            first_status = schedule_preload("bangalore")
            second_status = schedule_preload("bangalore")
            self.assertEqual(first_status, "loading")
            self.assertEqual(second_status, "already loading")
            deadline = time.time() + 2.0
            while graph_status.get("bangalore") == "loading" and time.time() < deadline:
                time.sleep(0.05)
        self.assertEqual(graph_status.get("bangalore"), "ready")

    def test_fetch_towers_cached_queues_tiles_and_uses_live_fallback(self) -> None:
        fetch_towers_cached = self.data["fetch_towers_cached"]
        globals_dict = fetch_towers_cached.__globals__

        async def fake_live_fetch(*args, **kwargs):
            return [{"id": "tower-1", "lat": 12.97, "lon": 77.59, "radio": "LTE", "range": 500.0}]

        with patch.dict(
            globals_dict,
            {
                "cached_towers_for_bbox": lambda *args, **kwargs: ([], ["bangalore_000_000"], set(), []),
                "queue_missing_tower_tiles": lambda tile_ids: len(tile_ids),
                "fetch_towers_for_corridor": fake_live_fetch,
            },
        ):
            towers, _bbox, metadata = asyncio.run(
                fetch_towers_cached(12.9716, 77.5946, 12.9948, 77.6699, 3.0)
            )

        self.assertEqual(len(towers or []), 1)
        self.assertEqual(metadata["source"], "OpenCellID")

    def test_cached_coverage_metadata_is_used_when_real_tiles_exist(self) -> None:
        cached_coverage_metadata = self.data["cached_coverage_metadata"]
        globals_dict = cached_coverage_metadata.__globals__

        temp_root = Path(tempfile.mkdtemp())
        db_path = temp_root / "tower_cache.db"
        try:
            self.data["persistent_cache_status"](db_path, "bangalore")
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute("UPDATE tiles SET is_cached = 1, last_updated = '2026-04-19T00:00:00Z' WHERE city = 'bangalore'")
                tile_ids = [row[0] for row in conn.execute("SELECT tile_id FROM tiles WHERE city = 'bangalore' LIMIT 2").fetchall()]
                for tile_id in tile_ids:
                    conn.execute(
                        "INSERT OR REPLACE INTO coverage_tiles(tile_id, city, has_real_data) VALUES (?, 'bangalore', 1)",
                        (tile_id,),
                    )
                conn.execute(
                    "INSERT INTO towers(lat, lon, mcc, mnc, lac, cellid, radio, range, tile_id) VALUES (12.97, 77.59, 404, 45, 100, 1, 'LTE', 500.0, ?)",
                    (tile_ids[0],),
                )
                tower_id = conn.execute("SELECT id FROM towers").fetchone()[0]
                conn.execute(
                    "INSERT OR IGNORE INTO tower_tile_map(tower_id, tile_id) VALUES (?, ?)",
                    (tower_id, tile_ids[0]),
                )
                conn.commit()

            original_db_path = globals_dict["TOWER_CACHE_DB_PATH"]
            globals_dict["TOWER_CACHE_DB_PATH"] = db_path
            try:
                metadata = cached_coverage_metadata("bangalore")
            finally:
                globals_dict["TOWER_CACHE_DB_PATH"] = original_db_path
        finally:
            pass

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["source"], "OpenCellID")
        self.assertGreater(float(metadata["coverage_percent"]), 0.0)

    def test_corridor_scores_are_hybrid_when_partial_real_coverage_exists(self) -> None:
        post_corridor_scores = self.data["post_corridor_scores"]
        globals_dict = post_corridor_scores.__globals__
        payload_model = self.data["CorridorScoresRequest"]

        class Tile:
            def __init__(self, tile_id: str, min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> None:
                self.tile_id = tile_id
                self.min_lat = min_lat
                self.min_lon = min_lon
                self.max_lat = max_lat
                self.max_lon = max_lon

        async def fake_fetch(*args, **kwargs):
            return (
                [{"id": "tower-1", "lat": 12.97, "lon": 77.59, "radio": "LTE", "range": 500.0}],
                {"min_lat": 12.95, "min_lon": 77.58, "max_lat": 12.99, "max_lon": 77.63},
                {
                    "source": "OpenCelliD",
                    "covered_tile_ids": {"tile-1"},
                    "query_tiles": [
                        Tile("tile-1", 12.95, 77.58, 12.99, 77.63),
                        Tile("tile-2", 12.99, 77.63, 13.02, 77.68),
                    ],
                    "coverage_percent": 50.0,
                },
            )

        with patch.dict(
            globals_dict,
            {
                "fetch_towers_cached": fake_fetch,
                "compute_scores_from_towers": lambda edge_coords, towers: {edge_id: 0.8 for edge_id in edge_coords},
            },
        ):
            payload = payload_model(
                origin=[12.9716, 77.5946],
                destination=[12.9948, 77.6699],
                edge_coords={
                    "edge-real": [12.9717, 77.5947],
                    "edge-ml": [13.0010, 77.6650],
                },
                padding_km=3.0,
            )
            response = asyncio.run(post_corridor_scores(payload))

        self.assertEqual(response["source"], "OpenCelliD")
        self.assertEqual(response["coverage_percent"], 50.0)
        self.assertEqual(response["scores"], {"edge-real": 0.8})

class HotspotViewportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_module(DATA_MAIN)

    def test_hotspots_only_include_visible_weak_segments(self) -> None:
        segment_record = self.data["SegmentRecord"]
        city_state = self.data["CityState"]
        hotspots_for_viewport = self.data["hotspots_for_viewport"]

        segments = [
            segment_record(
                segment_id="seg-in-weak",
                geometry=LineString([(77.58, 12.96), (77.59, 12.97)]),
                lat=12.965,
                lon=77.585,
                length=100.0,
                highway="primary",
                surface="paved",
                properties={"name": "MG Road"},
            ),
            segment_record(
                segment_id="seg-outside",
                geometry=LineString([(77.75, 13.15), (77.76, 13.16)]),
                lat=13.155,
                lon=77.755,
                length=100.0,
                highway="secondary",
                surface="paved",
                properties={"name": "Outer Ring"},
            ),
            segment_record(
                segment_id="seg-in-strong",
                geometry=LineString([(77.60, 12.98), (77.61, 12.99)]),
                lat=12.985,
                lon=77.605,
                length=100.0,
                highway="primary",
                surface="paved",
                properties={"name": "Brigade Road"},
            ),
        ]

        state = city_state(
            city="bangalore",
            graph=None,
            expires_at=time.time() + 60,
            segments=segments,
            segment_lookup={segment.segment_id: index for index, segment in enumerate(segments)},
            tile_index={},
            edge_tile_map={},
            context={},
            score_values=np.asarray([0.2, 0.1, 0.85], dtype=np.float32),
        )

        hotspots = hotspots_for_viewport(state, 12.94, 77.56, 13.00, 77.62, 12)
        hotspot_ids = [hotspot["id"] for hotspot in hotspots]

        self.assertEqual(hotspot_ids, ["seg-in-weak"])


class FrontendRegressionTests(unittest.TestCase):
    def test_map_view_keeps_base_route_and_signal_overlay(self) -> None:
        source = MAP_VIEW.read_text(encoding="utf-8")

        self.assertIn("routes.map((route) => (", source)
        self.assertIn("<RoutePolyline", source)
        self.assertIn("<RouteSignalOverlay", source)
        self.assertIn("noClip: true", source)
        self.assertIn("smoothFactor: 0", source)
        self.assertIn("CircleMarker", source)
        self.assertIn("onViewportChange", source)

    def test_app_fetches_hotspots_from_current_viewport(self) -> None:
        source = APP_VIEW.read_text(encoding="utf-8")

        self.assertIn("fetchHotspotsForViewport(selectedCity, viewportBounds)", source)
        self.assertIn("if (!showHeatmap || !selectedCity || !viewportBounds)", source)
        self.assertIn("setViewportBounds(nextViewport)", source)


if __name__ == "__main__":
    unittest.main()
