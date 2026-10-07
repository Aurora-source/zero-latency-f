from __future__ import annotations

import os
import runpy
import asyncio
import json
import pickle
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from shapely.geometry import LineString


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTING_MAIN = REPO_ROOT / "services" / "routing-engine" / "main.py"
DATA_MAIN = REPO_ROOT / "services" / "data-service" / "main.py"
PREDICTION_MAIN = REPO_ROOT / "services" / "prediction-service" / "main.py"
API_KEY_MANAGER_MAIN = REPO_ROOT / "services" / "data-service" / "api_key_manager.py"
TILE_LOADER_MAIN = REPO_ROOT / "services" / "data-service" / "tile_loader.py"
MAP_VIEW = REPO_ROOT / "services" / "visualization" / "app" / "components" / "MapView.tsx"
APP_VIEW = REPO_ROOT / "services" / "visualization" / "app" / "App.tsx"
API_CLIENT = REPO_ROOT / "services" / "visualization" / "app" / "lib" / "api.ts"
DATA_DOCKERFILE = REPO_ROOT / "services" / "data-service" / "Dockerfile"
PREDICTION_DOCKERFILE = REPO_ROOT / "services" / "prediction-service" / "Dockerfile"
ROUTING_DOCKERFILE = REPO_ROOT / "services" / "routing-engine" / "Dockerfile"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
GATEWAY_CONFIG = REPO_ROOT / "gateway" / "nginx.conf"


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

    def test_missing_travel_time_is_derived_in_seconds(self) -> None:
        graph = self.routing["nx"].MultiDiGraph()
        graph.add_node(1, x=77.59, y=12.97)
        graph.add_node(2, x=77.60, y=12.98)
        graph.add_edge(
            1,
            2,
            key=0,
            length=1000.0,
            highway="residential",
            speed_kph=36.0,
            travel_time=0.0,
        )
        annotate_base_graph = self.routing["annotate_base_graph"]
        globals_dict = annotate_base_graph.__globals__

        with patch.dict(
            globals_dict,
            {"add_edge_speeds_and_times": lambda candidate: candidate},
        ):
            annotated = annotate_base_graph(graph)

        edge = annotated.edges[1, 2, 0]
        self.assertAlmostEqual(float(edge["travel_time"]), 100.0, places=3)
        self.assertAlmostEqual(
            float(self.routing["edge_time_cost"](edge)),
            100.0,
            places=3,
        )

    def test_bangalore_risk_clock_and_route_cache_use_time_bucket(self) -> None:
        city_local_hour = self.routing["city_local_hour"]
        route_cache_key = self.routing["route_cache_key"]
        self.assertEqual(city_local_hour("bangalore", 0.0), 5)

        key_globals = route_cache_key.__globals__
        with patch.dict(key_globals, {"city_risk_time_bucket": lambda city: "day"}):
            day_key = route_cache_key(
                "bangalore",
                (12.97, 77.59),
                (12.99, 77.67),
                "balanced",
                "car",
            )
        with patch.dict(key_globals, {"city_risk_time_bucket": lambda city: "night"}):
            night_key = route_cache_key(
                "bangalore",
                (12.97, 77.59),
                (12.99, 77.67),
                "balanced",
                "car",
            )

        forced_day_key = route_cache_key(
            "bangalore",
            (12.97, 77.59),
            (12.99, 77.67),
            "balanced",
            "car",
            "day",
        )

        self.assertNotEqual(day_key, night_key)
        self.assertEqual(day_key, forced_day_key)

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

    def test_bicycle_and_scooter_profiles_remain_distinct(self) -> None:
        profiles = self.routing["VEHICLE_PROFILES"]

        self.assertIn("bike", profiles)
        self.assertIn("scooter", profiles)
        self.assertNotEqual(profiles["bike"], profiles["scooter"])

        edge = {
            "length": 900.0,
            "road_type": "motorway",
            "surface_type": "paved",
            "mid_lat": 12.98,
            "mid_lon": 77.60,
        }
        compute_scalar_route_cost = self.routing["compute_scalar_route_cost"]
        bike_cost, _ = compute_scalar_route_cost(
            "bangalore", edge, "balanced", "bike", 0.45, hour=14
        )
        scooter_cost, _ = compute_scalar_route_cost(
            "bangalore", edge, "balanced", "scooter", 0.45, hour=14
        )
        self.assertNotEqual(bike_cost, scooter_cost)

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

    def test_route_loading_response_uses_retry_contract(self) -> None:
        route_endpoint = self.routing["route"]
        request_model = self.routing["RouteRequest"]
        graph_status = self.routing["GRAPH_STATUS"]

        with patch.dict(graph_status, {"bangalore": "loading"}, clear=True):
            response = asyncio.run(
                route_endpoint(
                    request_model(
                        city="bangalore",
                        origin=[12.9716, 77.5946],
                        destination=[12.9948, 77.6699],
                        mode="balanced",
                        vehicle="bike",
                    )
                )
            )

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.headers["retry-after"], "5")
        self.assertEqual(payload["status"], "loading")
        self.assertEqual(payload["retry_after"], 5)

    def test_expired_graph_is_not_ready(self) -> None:
        graph_is_ready = self.routing["graph_is_ready"]
        graph_status = self.routing["GRAPH_STATUS"]
        graph_cache = self.routing["GRAPH_CACHE"]
        stale_state = SimpleNamespace(
            expires_at=time.time() - 1,
            vehicle_graphs={"car": object()},
        )

        with patch.dict(graph_status, {"bangalore": "ready"}, clear=True), patch.dict(
            graph_cache,
            {"bangalore": stale_state},
            clear=True,
        ):
            self.assertFalse(graph_is_ready("bangalore"))

    def test_corridor_contract_does_not_promote_unscored_edges(self) -> None:
        fetch_corridor_scores = self.routing["fetch_corridor_scores"]
        request_module = self.routing["request"]
        response_payload = {
            "scores": {"edge-real": 0.8},
            "graph_revision": "graph-test", "base_score_revision": "scores-test",
            "score_revision": "corridor-test",
            "source": "opencellid",
            "real_data_coverage_percent": 0.0,
            "coverage_percent": 99.0,
            "tower_count": 1,
        }

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def read() -> bytes:
                return json.dumps(response_payload).encode("utf-8")

        with patch.object(request_module, "urlopen", return_value=DummyResponse()):
            scores, _source, _tower_count, real_coverage, _good, edge_sources, _revision = (
                fetch_corridor_scores(
                    (12.97, 77.59),
                    (12.99, 77.67),
                    {
                        "edge-real": [12.971, 77.591],
                        "edge-ml": [12.989, 77.669],
                    },
                    "bangalore", "graph-test", "scores-test",
                )
            )

        self.assertEqual(scores, {"edge-real": 0.8})
        self.assertEqual(edge_sources["edge-real"], "opencellid")
        self.assertEqual(edge_sources["edge-ml"], "ml_synthetic")
        self.assertEqual(real_coverage, 0.0)

    def test_city_score_fetch_keeps_per_edge_provenance(self) -> None:
        fetch_city_scores = self.routing["fetch_city_scores"]
        request_module = self.routing["request"]
        response_payload = {
            "scores": {"edge-real": 0.8, "edge-ml": 0.4},
            "graph_revision": "graph-test", "score_revision": "scores-test",
            "source": "hybrid",
            "updated_at": 12.0,
            "edge_sources": {
                "edge-real": "TRAI India",
                "edge-ml": "ml_synthetic",
            },
        }

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            @staticmethod
            def read() -> bytes:
                return json.dumps(response_payload).encode("utf-8")

        with patch.object(request_module, "urlopen", return_value=DummyResponse()):
            scores, updated_at, edge_sources, _revision = fetch_city_scores("bangalore", "graph-test")

        self.assertEqual(scores, response_payload["scores"])
        self.assertEqual(updated_at, 12.0)
        self.assertEqual(edge_sources["edge-real"], "trai")
        self.assertEqual(edge_sources["edge-ml"], "ml_synthetic")

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
            cache_globals = store_cached_route.__globals__
            path_patch = patch.dict(cache_globals, {route_cache_path_key: temp_path})
            path_patch.start()
            self.addCleanup(path_patch.stop)
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
            cache_globals = store_cached_hotspots.__globals__
            path_patch = patch.dict(cache_globals, {hotspot_cache_path_key: temp_path})
            path_patch.start()
            self.addCleanup(path_patch.stop)
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

    def test_zero_tower_observation_keeps_real_coverage_and_source(self) -> None:
        tile_loader = load_module(TILE_LOADER_MAIN)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tower_cache.db"
            tile_loader["ensure_city_tiles"](db_path, "bangalore")
            with sqlite3.connect(str(db_path)) as conn:
                tile_id = str(
                    conn.execute(
                        "SELECT tile_id FROM tiles WHERE city = 'bangalore' LIMIT 1"
                    ).fetchone()[0]
                )
            tile = tile_loader["tile_bounds"](db_path, tile_id)
            tile_loader["store_tile_towers"](
                db_path,
                tile_id,
                [],
                source="opencellid",
            )
            center_lat = (tile.min_lat + tile.max_lat) / 2.0
            center_lon = (tile.min_lon + tile.max_lon) / 2.0
            towers, missing, covered, _query_tiles = tile_loader[
                "cached_towers_for_bbox"
            ](
                db_path,
                "bangalore",
                center_lat - 0.0001,
                center_lon - 0.0001,
                center_lat + 0.0001,
                center_lon + 0.0001,
            )
            sources = tile_loader["coverage_sources_for_tiles"](db_path, covered)

        self.assertEqual(towers, [])
        self.assertEqual(missing, [])
        self.assertEqual(covered, {tile_id})
        self.assertEqual(sources, {tile_id: "opencellid"})

    def test_expired_tiles_are_not_reported_as_current_coverage(self) -> None:
        tile_loader = load_module(TILE_LOADER_MAIN)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tower_cache.db"
            tile_loader["ensure_city_tiles"](db_path, "bangalore")
            with sqlite3.connect(str(db_path)) as conn:
                tile_id = str(
                    conn.execute(
                        "SELECT tile_id FROM tiles WHERE city = 'bangalore' LIMIT 1"
                    ).fetchone()[0]
                )
            tile_loader["store_tile_towers"](
                db_path,
                tile_id,
                [],
                source="opencellid",
            )
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "UPDATE tiles SET last_updated = '2000-01-01T00:00:00Z' "
                    "WHERE tile_id = ?",
                    (tile_id,),
                )
                conn.commit()

            status = tile_loader["cache_status"](db_path, "bangalore")

        self.assertEqual(status["cached_tiles"], 0)
        self.assertEqual(status["real_coverage_tiles"], 0)
        self.assertEqual(status["real_coverage_percent"], 0.0)

    def test_tower_refresh_updates_range_without_duplicate_null_identity(self) -> None:
        tile_loader = load_module(TILE_LOADER_MAIN)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tower_cache.db"
            tile_loader["ensure_city_tiles"](db_path, "bangalore")
            with sqlite3.connect(str(db_path)) as conn:
                tile_id = str(
                    conn.execute(
                        "SELECT tile_id FROM tiles WHERE city = 'bangalore' LIMIT 1"
                    ).fetchone()[0]
                )
            tile = tile_loader["tile_bounds"](db_path, tile_id)
            tower = {
                "lat": (tile.min_lat + tile.max_lat) / 2.0,
                "lon": (tile.min_lon + tile.max_lon) / 2.0,
                "radio": "LTE",
                "range": 500.0,
            }
            tile_loader["store_tile_towers"](
                db_path,
                tile_id,
                [tower],
                source="opencellid",
            )
            tile_loader["store_tile_towers"](
                db_path,
                tile_id,
                [{**tower, "range": 1500.0}],
                source="opencellid",
            )
            with sqlite3.connect(str(db_path)) as conn:
                rows = conn.execute("SELECT range FROM towers").fetchall()

        self.assertEqual(rows, [(1500.0,)])


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

            source = load_local_tower_source(
                csv_path,
                source="trai",
                logger=lambda message: None,
            )
            towers = local_towers_for_bbox(12.95, 77.58, 12.99, 77.61)

        self.assertIsNotNone(source)
        self.assertEqual(source["source"], "trai")
        self.assertEqual(int(source["count"]), 2)
        self.assertEqual(len(towers or []), 1)
        self.assertAlmostEqual(float(towers[0]["lat"]), 12.9716, places=4)

    def test_malformed_optional_local_source_does_not_abort_startup(self) -> None:
        data = load_module(DATA_MAIN)
        load_local_towers = data["load_local_towers"]

        def fail_local_load(**kwargs):
            raise ValueError("malformed optional CSV")

        with patch.dict(
            load_local_towers.__globals__,
            {
                "LOCAL_TOWER_INDEX": {"count": 1},
                "load_local_tower_source": fail_local_load,
            },
        ):
            result = load_local_towers()

        self.assertIsNone(result)
        self.assertIsNone(load_local_towers.__globals__["LOCAL_TOWER_INDEX"])


class DataScoreMergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_module(DATA_MAIN)

    def test_ml_refresh_fills_only_edges_without_real_observations(self) -> None:
        city_state = self.data["CityState"]
        state = city_state(
            city="bangalore",
            graph=None,
            expires_at=time.time() + 60,
            segments=[
                SimpleNamespace(segment_id="edge-real"),
                SimpleNamespace(segment_id="edge-ml"),
            ],
            segment_lookup={"edge-real": 0, "edge-ml": 1},
            score_values=np.asarray([0.8, 0.05], dtype=np.float32),
            real_score_sources={"edge-real": "trai"},
            score_metadata={"tower_count": 7},
        )
        refresh_city_predictions = self.data["refresh_city_predictions"]

        def fake_predictions(city, candidate_state):
            self.assertIs(candidate_state, state)
            return (
                {"edge-real": 0.2, "edge-ml": 0.7},
                {
                    "source": "ml_synthetic",
                    "data_source": "test-model",
                    "tower_count": 0,
                },
            )

        with patch.dict(
            self.data["GRAPH_CACHE"],
            {"bangalore": state},
            clear=True,
        ), patch.dict(
            refresh_city_predictions.__globals__,
            {"post_prediction_scores": fake_predictions},
        ):
            refresh_city_predictions("bangalore")

        values = self.data["to_numpy_array"](state.score_values)
        self.assertAlmostEqual(float(values[0]), 0.8, places=3)
        self.assertAlmostEqual(float(values[1]), 0.7, places=3)
        self.assertEqual(state.score_source, "hybrid")
        self.assertEqual(state.real_score_sources, {"edge-real": "trai"})
        self.assertEqual(state.score_metadata["real_data_coverage_percent"], 50.0)
        self.assertEqual(state.score_metadata["tower_count"], 7)

    def test_corridor_feedback_records_exact_real_edge_source(self) -> None:
        city_state = self.data["CityState"]
        state = city_state(
            city="bangalore",
            graph=None,
            expires_at=time.time() + 60,
            segments=[
                SimpleNamespace(segment_id="edge-real"),
                SimpleNamespace(segment_id="edge-ml"),
            ],
            segment_lookup={"edge-real": 0, "edge-ml": 1},
            score_values=np.asarray([0.4, 0.6], dtype=np.float32),
        )
        update_corridor_tiles = self.data["update_corridor_tiles"]
        with patch.dict(
            self.data["GRAPH_CACHE"],
            {"bangalore": state},
            clear=True,
        ), patch.dict(
            update_corridor_tiles.__globals__,
            {"cached_coverage_metadata": lambda city: None},
        ):
            updated = update_corridor_tiles(
                "bangalore",
                {"edge-real": 0.9},
                {"edge-real": "opencellid"},
            )

        self.assertEqual(updated, 1)
        self.assertEqual(state.real_score_sources, {"edge-real": "opencellid"})
        self.assertEqual(state.score_source, "hybrid")
        self.assertEqual(state.score_metadata["real_data_coverage_percent"], 50.0)

    def test_current_edge_provider_replaces_historical_provider(self) -> None:
        city_state = self.data["CityState"]
        state = city_state(
            city="bangalore",
            graph=None,
            expires_at=time.time() + 60,
            segments=[SimpleNamespace(segment_id="edge-real")],
            segment_lookup={"edge-real": 0},
            score_values=np.asarray([0.4], dtype=np.float32),
            real_score_sources={"edge-real": "opencellid"},
        )
        update_corridor_tiles = self.data["update_corridor_tiles"]
        with patch.dict(
            self.data["GRAPH_CACHE"],
            {"bangalore": state},
            clear=True,
        ), patch.dict(
            update_corridor_tiles.__globals__,
            {"cached_coverage_metadata": lambda city: None},
        ):
            updated = update_corridor_tiles(
                "bangalore",
                {"edge-real": 0.9},
                {"edge-real": "trai"},
            )

        self.assertEqual(updated, 1)
        self.assertEqual(state.real_score_sources, {"edge-real": "trai"})

    def test_unknown_tile_provider_is_not_promoted_by_known_neighbor(self) -> None:
        corridor_metadata = self.data["corridor_coverage_metadata"]
        corridor_real_edges = self.data["corridor_real_edge_coords"]

        tiles = [
            SimpleNamespace(
                tile_id="known",
                min_lat=12.95,
                min_lon=77.58,
                max_lat=13.00,
                max_lon=77.64,
            ),
            SimpleNamespace(
                tile_id="unknown",
                min_lat=12.95,
                min_lon=77.64,
                max_lat=13.00,
                max_lon=77.70,
            ),
        ]
        tile_sources = {"known": "opencellid", "unknown": "unknown"}

        with patch.dict(
            corridor_metadata.__globals__,
            {
                "coverage_sources_for_tiles": lambda *args, **kwargs: tile_sources,
            },
        ):
            metadata = corridor_metadata(
                [],
                [],
                {"known", "unknown"},
                tiles,
            )

        _edge_coords, edge_sources = corridor_real_edges(
            {"boundary": [12.975, 77.64]},
            tiles,
            {"known", "unknown"},
            tile_sources,
        )

        self.assertEqual(metadata["real_data_source"], "unknown")
        self.assertEqual(metadata["source"], "unknown")
        self.assertEqual(metadata["real_data_coverage_percent"], 50.0)
        self.assertEqual(edge_sources["boundary"], "unknown")

    def test_adjacent_empty_tile_does_not_erase_boundary_tower_score(self) -> None:
        tile_loader = load_module(TILE_LOADER_MAIN)
        city_state = self.data["CityState"]
        segment_record = self.data["SegmentRecord"]
        update_coverage_model = self.data["update_coverage_model"]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tower_cache.db"
            tile_loader["ensure_city_tiles"](db_path, "bangalore")
            with sqlite3.connect(str(db_path)) as conn:
                rows = conn.execute(
                    """
                    SELECT tile_id, min_lat, min_lon, max_lat, max_lon
                    FROM tiles WHERE city = 'bangalore'
                    ORDER BY min_lat, min_lon LIMIT 2
                    """
                ).fetchall()
            self.assertEqual(len(rows), 2)
            first, second = rows
            shared_lon = (float(first[4]) + float(second[2])) / 2.0
            center_lat = (
                max(float(first[1]), float(second[1]))
                + min(float(first[3]), float(second[3]))
            ) / 2.0
            first_center_lon = (float(first[2]) + float(first[4])) / 2.0
            second_center_lon = (float(second[2]) + float(second[4])) / 2.0
            geometry = LineString(
                [(first_center_lon, center_lat), (second_center_lon, center_lat)]
            )
            segment = segment_record(
                segment_id="boundary-edge",
                geometry=geometry,
                lat=center_lat,
                lon=shared_lon,
                length=100.0,
                highway="primary",
                surface="paved",
                properties={},
            )
            state = city_state(
                city="bangalore",
                graph=None,
                expires_at=time.time() + 60,
                segments=[segment],
                segment_lookup={"boundary-edge": 0},
                score_values=np.asarray([0.5], dtype=np.float32),
            )
            tile_loader["store_tile_towers"](
                db_path,
                str(first[0]),
                [
                    {
                        "lat": center_lat,
                        "lon": shared_lon,
                        "radio": "LTE",
                        "range": 500.0,
                    }
                ],
                source="opencellid",
            )

            with patch.dict(
                self.data["GRAPH_CACHE"],
                {"bangalore": state},
                clear=True,
            ), patch.dict(
                update_coverage_model.__globals__,
                {"TOWER_CACHE_DB_PATH": db_path},
            ):
                update_coverage_model("bangalore", str(first[0]), 1)
                first_score = float(
                    self.data["to_numpy_array"](state.score_values)[0]
                )
                tile_loader["store_tile_towers"](
                    db_path,
                    str(second[0]),
                    [],
                    source="opencellid",
                )
                update_coverage_model("bangalore", str(second[0]), 0)
                second_score = float(
                    self.data["to_numpy_array"](state.score_values)[0]
                )
                restored_state = city_state(
                    city="bangalore",
                    graph=None,
                    expires_at=time.time() + 60,
                    segments=[segment],
                    segment_lookup={"boundary-edge": 0},
                    score_values=np.asarray([0.5], dtype=np.float32),
                )
                restored_count = self.data["hydrate_cached_coverage"](
                    "bangalore",
                    restored_state,
                )
                restored_score = float(
                    self.data["to_numpy_array"](restored_state.score_values)[0]
                )

        self.assertGreater(first_score, self.data["ROAD_FALLBACK_SCORE"])
        self.assertAlmostEqual(second_score, first_score, places=3)
        self.assertEqual(restored_count, 1)
        self.assertAlmostEqual(restored_score, first_score, places=3)
        self.assertEqual(
            restored_state.real_score_sources,
            {"boundary-edge": "opencellid"},
        )


class APIKeyManagerTests(unittest.TestCase):
    def test_api_key_manager_rotates_and_persists_state(self) -> None:
        module = load_module(API_KEY_MANAGER_MAIN)
        APIKeyManager = module["APIKeyManager"]

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "missing-environment-file"
            state_path = Path(tmpdir) / "api_key_state.json"
            with patch.dict(
                os.environ,
                {"OPENCELLID_KEYS": "key1,key2,key3", "OPENCELLID_TOKEN": ""},
                clear=False,
            ):
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
            env_path = Path(tmpdir) / "missing-environment-file"
            state_path = Path(tmpdir) / "api_key_state.json"
            with patch.dict(
                os.environ,
                {"OPENCELLID_KEYS": "key1,key2", "OPENCELLID_TOKEN": ""},
                clear=False,
            ):
                manager = APIKeyManager(env_path=env_path, state_path=state_path, logger=lambda message: None)

                async def fake_size(*args, **kwargs):
                    if kwargs["token"] == "key1":
                        raise RuntimeError("OpenCellID size error: Daily limit exceeded")
                    return 0

                with patch.dict(globals_dict, {"fetch_area_size": fake_size}):
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

    def test_foreground_fetch_does_not_wait_for_exhausted_keys(self) -> None:
        tile_loader = load_module(TILE_LOADER_MAIN)
        fetch_tower_chunk = tile_loader["fetch_tower_chunk"]

        class ExhaustedManager:
            @staticmethod
            def has_available_key() -> bool:
                return False

            @staticmethod
            def wait_until_available(stop_event=None) -> bool:
                raise AssertionError("foreground fetch must not wait")

        with self.assertRaisesRegex(RuntimeError, "temporarily unavailable"):
            asyncio.run(
                fetch_tower_chunk(
                    client=None,
                    chunk_bbox=(12.95, 77.58, 12.99, 77.63),
                    chunk_number=1,
                    key_manager=ExhaustedManager(),
                )
            )


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

    def test_documented_provenance_aliases_are_accepted(self) -> None:
        expected = {
            "TRAI India": "trai",
            "mixed": "hybrid",
            "mixed_source": "hybrid",
            "opencellid+ml": "hybrid",
        }
        for alias, canonical in expected.items():
            self.assertEqual(self.data["canonical_provenance"](alias), canonical)
            self.assertEqual(self.routing["canonical_provenance"](alias), canonical)

    def test_legacy_good_signal_alias_is_not_real_data_coverage(self) -> None:
        load_real_scores = self.data["load_real_scores"]
        globals_dict = load_real_scores.__globals__

        with tempfile.TemporaryDirectory() as tmpdir:
            score_dir = Path(tmpdir)
            with (score_dir / "bangalore_real_scores.pkl").open("wb") as handle:
                pickle.dump({
                    "graph_revision": "graph-test", "score_revision": "scores-test",
                    "scores": {"edge-real": 0.4, "edge-fallback": 0.05},
                    "metadata": {"source": "OpenCelliD", "coverage_percent": 0.0},
                }, handle)
            state = SimpleNamespace(
                graph_revision="graph-test",
                segments=[object(), object()],
                segment_lookup={"edge-real": 0, "edge-fallback": 1},
            )
            with patch.dict(globals_dict, {"REAL_SCORE_DIR": score_dir}):
                _scores, metadata = load_real_scores("bangalore", state)

        self.assertEqual(metadata["source"], "hybrid")
        self.assertEqual(metadata["real_data_source"], "opencellid")
        self.assertEqual(metadata["real_data_coverage_percent"], 50.0)
        self.assertEqual(metadata["coverage_percent"], 50.0)
        self.assertEqual(metadata["good_signal_percent"], 0.0)

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
        candidate_graph = SimpleNamespace(graph={})

        def fake_graph_from_polygon(*args, **kwargs):
            attempts.append(
                (
                    str(globals_dict["ox"].settings.overpass_url),
                    float(globals_dict["ox"].settings.requests_timeout),
                )
            )
            if len(attempts) == 1:
                raise TimeoutError("primary endpoint timed out")
            return candidate_graph

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

        self.assertIs(graph, candidate_graph)
        self.assertTrue(graph.graph["graph_revision"])
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

    def test_data_service_disables_ingestion_safely_without_keys_or_local_towers(self) -> None:
        start_worker = self.data["start_tower_worker_if_available"]
        globals_dict = start_worker.__globals__

        class EmptyKeyManager:
            @staticmethod
            def status() -> dict[str, int]:
                return {"total_keys": 0}

        with patch.dict(
            globals_dict,
            {
                "API_KEY_MANAGER": EmptyKeyManager(),
                "LOCAL_TOWER_INDEX": None,
                "TOWER_WORKER": None,
            },
        ):
            self.assertFalse(start_worker())
            self.assertIsNone(globals_dict["TOWER_WORKER"])

    def test_fetch_towers_cached_queues_tiles_and_uses_live_fallback(self) -> None:
        fetch_towers_cached = self.data["fetch_towers_cached"]
        globals_dict = fetch_towers_cached.__globals__

        async def fake_live_fetch(*args, **kwargs):
            return [{"id": "tower-1", "lat": 12.97, "lon": 77.59, "radio": "LTE", "range": 500.0}]

        with patch.dict(
            globals_dict,
            {
                "cached_towers_for_bbox": lambda *args, **kwargs: (
                    [],
                    ["bangalore_000_000"],
                    set(),
                    [],
                ),
                "queue_missing_tower_tiles": lambda tile_ids: len(tile_ids),
                "fetch_towers_for_corridor": fake_live_fetch,
                "live_tower_fetch_available": lambda: True,
                "tower_provenance_source": lambda: "opencellid",
            },
        ):
            towers, _bbox, metadata = asyncio.run(
                fetch_towers_cached(12.9716, 77.5946, 12.9948, 77.6699, 3.0)
            )

        self.assertEqual(len(towers or []), 1)
        self.assertEqual(metadata["source"], "opencellid")
        self.assertEqual(metadata["real_data_coverage_percent"], 100.0)

    def test_partial_persisted_towers_are_not_retained_after_expiry(self) -> None:
        fetch_towers_cached = self.data["fetch_towers_cached"]
        globals_dict = fetch_towers_cached.__globals__

        class Tile:
            tile_id = "tile-1"
            min_lat = 12.95
            min_lon = 77.58
            max_lat = 13.02
            max_lon = 77.68

        query_tiles = [
            Tile(),
            SimpleNamespace(
                tile_id="tile-2",
                min_lat=12.95,
                min_lon=77.68,
                max_lat=13.02,
                max_lon=77.78,
            ),
        ]

        cached_results = iter(
            [
                (
                    [
                        {
                            "id": "tower-1",
                            "lat": 12.97,
                            "lon": 77.59,
                            "radio": "LTE",
                            "range": 500.0,
                        }
                    ],
                    [],
                    {"tile-1"},
                    query_tiles,
                ),
                ([], ["tile-1", "tile-2"], set(), query_tiles),
            ]
        )

        with patch.dict(
            globals_dict,
            {
                "cached_towers_for_bbox": lambda *args, **kwargs: next(
                    cached_results
                ),
                "coverage_sources_for_tiles": lambda *args, **kwargs: {
                    "tile-1": "opencellid"
                },
                "queue_missing_tower_tiles": lambda tile_ids: 0,
                "live_tower_fetch_available": lambda: False,
            },
        ):
            globals_dict["CORRIDOR_CACHE"].clear()
            first_towers, _bbox, first_metadata = asyncio.run(
                fetch_towers_cached(12.9716, 77.5946, 12.9948, 77.6699, 3.0)
            )
            second_towers, _bbox, second_metadata = asyncio.run(
                fetch_towers_cached(12.9716, 77.5946, 12.9948, 77.6699, 3.0)
            )
            globals_dict["CORRIDOR_CACHE"].clear()

        self.assertEqual(len(first_towers or []), 1)
        self.assertIsNone(second_towers)
        self.assertEqual(first_metadata["real_data_coverage_percent"], 50.0)
        self.assertEqual(first_metadata["source"], "hybrid")
        self.assertEqual(second_metadata["real_data_coverage_percent"], 0.0)
        self.assertEqual(second_metadata["source"], "unknown")

    def test_cached_coverage_metadata_is_used_when_real_tiles_exist(self) -> None:
        cached_coverage_metadata = self.data["cached_coverage_metadata"]
        globals_dict = cached_coverage_metadata.__globals__

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tower_cache.db"
            self.data["persistent_cache_status"](db_path, "bangalore")
            fresh_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "UPDATE tiles SET is_cached = 1, last_updated = ? "
                    "WHERE city = 'bangalore'",
                    (fresh_timestamp,),
                )
                tile_ids = [
                    row[0]
                    for row in conn.execute(
                        "SELECT tile_id FROM tiles WHERE city = 'bangalore' LIMIT 2"
                    ).fetchall()
                ]
                for tile_id in tile_ids:
                    conn.execute(
                        "INSERT OR REPLACE INTO coverage_tiles(tile_id, city, has_real_data, source) "
                        "VALUES (?, 'bangalore', 1, 'opencellid')",
                        (tile_id,),
                    )
                conn.execute(
                    "INSERT INTO towers(lat, lon, mcc, mnc, lac, cellid, radio, range, tile_id) "
                    "VALUES (12.97, 77.59, 404, 45, 100, 1, 'LTE', 500.0, ?)",
                    (tile_ids[0],),
                )
                tower_id = conn.execute("SELECT id FROM towers").fetchone()[0]
                conn.execute(
                    "INSERT OR IGNORE INTO tower_tile_map(tower_id, tile_id) VALUES (?, ?)",
                    (tower_id, tile_ids[0]),
                )
                conn.commit()

            with patch.dict(
                globals_dict,
                {
                    "TOWER_CACHE_DB_PATH": db_path,
                    "local_tower_source_status": lambda: {
                        "loaded": False,
                        "count": 0,
                        "source": "unknown",
                    },
                },
            ):
                metadata = cached_coverage_metadata("bangalore")

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["source"], "hybrid")
        self.assertEqual(metadata["real_data_source"], "opencellid")
        self.assertGreater(float(metadata["real_data_coverage_percent"]), 0.0)
        self.assertEqual(
            metadata["coverage_percent"],
            metadata["real_data_coverage_percent"],
        )

    def test_corridor_scores_are_hybrid_when_partial_real_coverage_exists(self) -> None:
        post_corridor_scores = self.data["post_corridor_scores"]
        globals_dict = post_corridor_scores.__globals__
        payload_model = self.data["CorridorScoresRequest"]

        class Tile:
            def __init__(
                self,
                tile_id: str,
                min_lat: float,
                min_lon: float,
                max_lat: float,
                max_lon: float,
            ) -> None:
                self.tile_id = tile_id
                self.min_lat = min_lat
                self.min_lon = min_lon
                self.max_lat = max_lat
                self.max_lon = max_lon

        async def fake_fetch(*args, **kwargs):
            return (
                [{"id": "tower-1", "lat": 12.97, "lon": 77.59, "radio": "LTE", "range": 500.0}],
                {"min_lat": 12.95, "min_lon": 77.58, "max_lat": 13.02, "max_lon": 77.68},
                {
                    "source": "opencellid",
                    "covered_tile_ids": {"tile-1"},
                    "query_tiles": [
                        Tile("tile-1", 12.95, 77.58, 12.99, 77.63),
                        Tile("tile-2", 12.99, 77.63, 13.02, 77.68),
                    ],
                    "real_data_coverage_percent": 50.0,
                    "live_full_bbox": False,
                },
            )

        with patch.dict(
            globals_dict,
            {
                "fetch_towers_cached": fake_fetch,
                "GRAPH_CACHE": {"bangalore": SimpleNamespace(
                    graph_revision="graph-test", score_revision="scores-test",
                )},
                "compute_scores_from_towers": lambda edge_coords, towers: {
                    edge_id: 0.8 for edge_id in edge_coords
                },
            },
        ):
            payload = payload_model(
                city="bangalore", graph_revision="graph-test", score_revision="scores-test",
                origin=[12.9716, 77.5946],
                destination=[12.9948, 77.6699],
                edge_coords={
                    "edge-real": [12.9717, 77.5947],
                    "edge-ml": [13.0010, 77.6650],
                },
                padding_km=3.0,
            )
            response = asyncio.run(post_corridor_scores(payload))

        self.assertEqual(response["source"], "hybrid")
        self.assertEqual(response["real_data_coverage_percent"], 50.0)
        self.assertEqual(response["good_signal_percent"], 100.0)
        self.assertEqual(response["scores"], {"edge-real": 0.8})
        self.assertEqual(response["edge_sources"]["edge-real"], "opencellid")
        self.assertEqual(response["edge_sources"]["edge-ml"], "ml_synthetic")


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
        # Leaflet Polyline options are direct React props, not PathOptions entries.
        self.assertEqual(source.count("\n      noClip\n"), 2)
        self.assertEqual(source.count("smoothFactor={0}"), 2)
        self.assertIn("CircleMarker", source)
        self.assertIn("onViewportChange", source)

    def test_app_fetches_hotspots_from_current_viewport(self) -> None:
        source = APP_VIEW.read_text(encoding="utf-8")

        self.assertIn("fetchHotspotsForViewport(selectedCity, viewportBounds)", source)
        self.assertIn("if (!showHeatmap || !selectedCity || !viewportBounds)", source)
        self.assertIn("setViewportBounds(nextViewport)", source)

    def test_frontend_honors_retry_after_and_preserves_requested_edge_sources(self) -> None:
        source = API_CLIENT.read_text(encoding="utf-8")

        self.assertIn('res.headers.get("Retry-After")', source)
        self.assertIn("if (status === 202)", source)
        self.assertIn("Object.keys(payload.edgeCoords)", source)
        self.assertIn('!(segmentId in scores)', source)
        self.assertIn('routeEdgeSources[segmentId] ??\n              "unknown"', source)

    def test_gateway_exposes_every_active_frontend_api_route(self) -> None:
        source = GATEWAY_CONFIG.read_text(encoding="utf-8")

        for route in (
            "/api/cities",
            "/api/city-context/",
            "/api/hotspots/",
            "/api/corridor-towers",
            "/api/corridor-scores",
            "/api/cache-status",
            "/api/tiles/",
            "/api/scores/",
            "/api/route",
            "/api/preload/",
        ):
            self.assertIn(route, source)

    def test_default_images_are_python_311_cpu_builds(self) -> None:
        compose = COMPOSE_FILE.read_text(encoding="utf-8")
        prediction_dockerfile = PREDICTION_DOCKERFILE.read_text(encoding="utf-8")
        routing_dockerfile = ROUTING_DOCKERFILE.read_text(encoding="utf-8")
        data_dockerfile = DATA_DOCKERFILE.read_text(encoding="utf-8")

        self.assertNotIn("driver: nvidia", compose)
        self.assertTrue(prediction_dockerfile.startswith("FROM python:3.11.16-slim-bookworm"))
        self.assertTrue(routing_dockerfile.startswith("FROM python:3.11.16-slim-bookworm"))
        self.assertTrue(
            (REPO_ROOT / "services" / "visualization" / "Dockerfile")
            .read_text(encoding="utf-8")
            .startswith("FROM node:22.23.2-bookworm-slim@sha256:")
        )
        self.assertNotIn(
            "--configLoader native",
            (REPO_ROOT / "services" / "visualization" / "package.json")
            .read_text(encoding="utf-8"),
        )
        for module_name in (
            "main.py",
            "api_key_manager.py",
            "tile_loader.py",
            "tower_ingestion_worker.py",
        ):
            self.assertIn(module_name, data_dockerfile)

    def test_active_build_contexts_exclude_credentials_and_runtime_data(self) -> None:
        for service_name in (
            "data-service",
            "prediction-service",
            "routing-engine",
            "visualization",
        ):
            dockerignore = (
                REPO_ROOT / "services" / service_name / ".dockerignore"
            ).read_text(encoding="utf-8")
            for pattern in (
                "**/.env",
                "**/*.env",
                "**/*credential*.json",
                "**/api_key_state.json",
                "**/*.db",
                "**/cache/",
                "**/models/",
                "**/node_modules/",
            ):
                self.assertIn(pattern, dockerignore, f"{service_name}: {pattern}")

    def test_compose_health_gates_use_readiness_endpoints(self) -> None:
        compose = COMPOSE_FILE.read_text(encoding="utf-8")
        for port in (8001, 8002, 8003):
            self.assertIn(f"http://127.0.0.1:{port}/ready", compose)
        self.assertEqual(compose.count("condition: service_healthy"), 2)
        # The static gateway starts immediately; downstream graph work is gated.
        self.assertIn("http://127.0.0.1:8080/api/ready/routing", compose)

        for service_main in (DATA_MAIN, ROUTING_MAIN, PREDICTION_MAIN):
            source = service_main.read_text(encoding="utf-8")
            self.assertIn('@app.get("/ready")', source)


if __name__ == "__main__":
    unittest.main()
