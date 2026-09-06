from __future__ import annotations

import asyncio
import json
import runpy
import sys
import tempfile
import threading
import time
import unittest
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import networkx as nx
import numpy as np
from shapely.geometry import LineString


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTING_MAIN = REPO_ROOT / "services" / "routing-engine" / "main.py"
ORIGIN = (12.9700, 77.5900)
DESTINATION = (12.9800, 77.6000)


def load_routing_service() -> dict[str, object]:
    module_dir = str(ROUTING_MAIN.parent)
    inserted = False
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
        inserted = True
    try:
        return runpy.run_path(str(ROUTING_MAIN))
    finally:
        if inserted:
            sys.path.remove(module_dir)


def synthetic_graph(
    *, score: float = 0.2, provenance: str = "ml_synthetic"
) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph(crs="EPSG:4326", graph_revision="graph-test")
    graph.add_node(1, x=ORIGIN[1], y=ORIGIN[0])
    graph.add_node(2, x=DESTINATION[1], y=DESTINATION[0])
    graph.add_edge(
        1,
        2,
        key=0,
        edge_index=0,
        segment_id="1-2-0",
        geometry=LineString([(ORIGIN[1], ORIGIN[0]), (DESTINATION[1], DESTINATION[0])]),
        length=1000.0,
        travel_time=100.0,
        travel_time_norm=0.0,
        speed_kph=36.0,
        connectivity_score=score,
        provenance_source=provenance,
        road_type="residential",
        surface_type="paved",
        road_name="Test Road",
        mid_lat=(ORIGIN[0] + DESTINATION[0]) / 2,
        mid_lon=(ORIGIN[1] + DESTINATION[1]) / 2,
    )
    return graph


def synthetic_diamond() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph(crs="EPSG:4326", graph_revision="graph-diamond")
    node_coords = {
        1: (77.590, 12.970),
        2: (77.595, 12.975),
        3: (77.595, 12.965),
        4: (77.600, 12.970),
    }
    for node, (lon, lat) in node_coords.items():
        graph.add_node(node, x=lon, y=lat)

    edges = [
        (1, 2, 0, 1000.0, 40.0, 0.2, "ml_synthetic", "fast-a"),
        (1, 3, 1, 600.0, 50.0, 0.9, "trai", "good-a"),
        (2, 4, 2, 1000.0, 40.0, 0.2, "ml_synthetic", "fast-b"),
        (3, 4, 3, 600.0, 50.0, 0.9, "trai", "good-b"),
    ]
    for u, v, edge_index, length, travel_time, score, source, segment_id in edges:
        start = node_coords[u]
        end = node_coords[v]
        graph.add_edge(
            u,
            v,
            key=0,
            edge_index=edge_index,
            segment_id=segment_id,
            geometry=LineString([start, end]),
            length=length,
            travel_time=travel_time,
            travel_time_norm=travel_time / 100.0,
            speed_kph=length / travel_time * 3.6,
            connectivity_score=score,
            provenance_source=source,
            road_type="residential",
            surface_type="paved",
            road_name="Fast Road" if score < 0.5 else "Covered Road",
            mid_lat=(start[1] + end[1]) / 2,
            mid_lon=(start[0] + end[0]) / 2,
        )
    return graph


def prepared_graph(
    routing: dict[str, object],
    graph: nx.MultiDiGraph,
    *,
    vehicle: str = "car",
    hour: int = 12,
    score_version: float = 1.0,
):
    edge = next(iter(graph.edges(data=True)))[2]
    score = float(edge["connectivity_score"])
    risk_points = 0.7 if score < 0.3 else 0.0
    values = np.asarray([100.0], dtype=np.float32)
    false_mask = np.asarray([False], dtype=bool)
    return routing["PreparedVehicleGraph"](
        vehicle=vehicle,
        scores=np.asarray([score], dtype=np.float32),
        risk_points=np.asarray([risk_points], dtype=np.float32),
        risk_multiplier=np.asarray([1.0], dtype=np.float32),
        fastest_cost=values.copy(),
        balanced_cost=values.copy(),
        connected_cost=values.copy(),
        dead_zone_mask=np.asarray([score < 0.3], dtype=bool),
        residential_night_mask=np.asarray([hour >= 20 or hour <= 6], dtype=bool),
        chennai_outer_mask=false_mask.copy(),
        flood_mask=false_mask.copy(),
        highway_mask=false_mask.copy(),
        below_tolerance_mask=false_mask.copy(),
        stable_mask=false_mask.copy(),
        risk_time_bucket="night" if hour >= 20 or hour <= 6 else "day",
        risk_hour=hour,
        source_scores_updated_at=score_version,
    )


def graph_state(
    routing: dict[str, object],
    graph: nx.MultiDiGraph,
    *,
    hour: int = 12,
    score_version: float = 1.0,
    snapshot_id: str = "snapshot-old",
):
    prepared = prepared_graph(
        routing, graph, hour=hour, score_version=score_version
    )
    return routing["GraphState"](
        city="bangalore",
        base_graph=graph,
        expires_at=time.time() + 60.0,
        scores_updated_at=score_version,
        edge_count=1,
        node_index=None,
        vehicle_graphs={"car": prepared},
        snapshot_id=snapshot_id,
        graph_revision=graph.graph["graph_revision"],
        score_revision=f"scores-{score_version}",
    )


def route_runtime_patches(globals_dict: dict[str, object]) -> dict[str, object]:
    return {
        "city_local_hour": lambda city: 12,
        "find_nearest_node": (
            lambda graph, latitude, longitude, node_index: 1
            if longitude == ORIGIN[1]
            else 2
        ),
        "compute_path_with_fallbacks": lambda graph, origin, destination, weights: [1, 2],
        "fetch_corridor_scores": lambda *args: ({}, "ml_synthetic", 0, 0.0, 0.0, {}, "corridor-test"),
        "push_corridor_scores_to_tiles": lambda *args: None,
        "persist_route_cache": lambda: None,
    }


class ObservableLock:
    """A lock that exposes when a known number of callers attempted entry."""

    def __init__(self, expected_entries: int = 2) -> None:
        self._lock = threading.Lock()
        self._counter_lock = threading.Lock()
        self._expected_entries = expected_entries
        self.entries = 0
        self.expected_entry_reached = threading.Event()

    def __enter__(self):
        with self._counter_lock:
            self.entries += 1
            if self.entries == self._expected_entries:
                self.expected_entry_reached.set()
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._lock.release()


async def call_inline(function, *args, **kwargs):
    """Deterministic stand-in for asyncio.to_thread when the fake work is instant."""

    return function(*args, **kwargs)


class RoutingConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.routing = load_routing_service()

    def test_equivalent_routes_share_one_in_flight_computation(self) -> None:
        compute_route = self.routing["compute_route"]
        globals_dict = compute_route.__globals__
        state = graph_state(self.routing, synthetic_graph())
        snapshot = self.routing["RouteSnapshot"](
            state.base_graph,
            state.node_index,
            state.vehicle_graphs,
            state.scores_updated_at,
            state.snapshot_id,
        )
        callers = 6
        rendezvous = threading.Barrier(callers)
        computation_started = threading.Event()
        release_computation = threading.Event()
        calls_lock = threading.Lock()
        computation_calls = 0

        class CountingLock:
            def __init__(self) -> None:
                self.lock = threading.Lock()
                self.entries = 0
                self.all_callers_registered = threading.Event()

            def __enter__(self):
                self.lock.acquire()
                self.entries += 1
                if self.entries == callers:
                    self.all_callers_registered.set()
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                self.lock.release()

        flights_lock = CountingLock()

        def synchronized_snapshot(candidate_state):
            self.assertIs(candidate_state, state)
            rendezvous.wait(timeout=1.0)
            return snapshot

        def fake_compute(*args):
            nonlocal computation_calls
            with calls_lock:
                computation_calls += 1
            computation_started.set()
            self.assertTrue(release_computation.wait(1.0))
            return {"nodes": [1, 2], "generation": snapshot.snapshot_id}

        with patch.dict(
            globals_dict,
            {
                "require_graph_state": lambda city: state,
                "ensure_current_risk_weights": synchronized_snapshot,
                "compute_route_from_snapshot": fake_compute,
                "ROUTE_FLIGHTS": {},
                "ROUTE_FLIGHTS_LOCK": flights_lock,
            },
        ):
            with ThreadPoolExecutor(max_workers=callers) as pool:
                futures = [
                    pool.submit(
                        compute_route,
                        "bangalore",
                        ORIGIN,
                        DESTINATION,
                        "balanced",
                        "car",
                    )
                    for _ in range(callers)
                ]
                self.assertTrue(computation_started.wait(1.0))
                self.assertTrue(flights_lock.all_callers_registered.wait(1.0))
                release_computation.set()
                results = [future.result(timeout=1.0) for future in futures]

            self.assertEqual(globals_dict["ROUTE_FLIGHTS"], {})

        self.assertEqual(computation_calls, 1)
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len({id(result) for result in results}), callers)

    def test_singleflight_failure_reaches_waiters_and_next_call_retries(self) -> None:
        compute_route = self.routing["compute_route"]
        globals_dict = compute_route.__globals__
        state = graph_state(self.routing, synthetic_graph())
        snapshot = self.routing["RouteSnapshot"](
            state.base_graph,
            state.node_index,
            state.vehicle_graphs,
            state.scores_updated_at,
            state.snapshot_id,
        )
        callers = 4
        rendezvous = threading.Barrier(callers)
        owner_started = threading.Event()
        release_owner = threading.Event()
        flights_lock = ObservableLock(expected_entries=callers)
        calls_lock = threading.Lock()
        compute_calls = 0

        def synchronized_snapshot(candidate_state):
            rendezvous.wait(timeout=1.0)
            return snapshot

        def fail_then_succeed(*args):
            nonlocal compute_calls
            with calls_lock:
                compute_calls += 1
                call_number = compute_calls
            if call_number == 1:
                owner_started.set()
                self.assertTrue(release_owner.wait(1.0))
                raise RuntimeError("interrupted route computation")
            return {"nodes": [1, 2]}

        with patch.dict(
            globals_dict,
            {
                "require_graph_state": lambda city: state,
                "ensure_current_risk_weights": synchronized_snapshot,
                "compute_route_from_snapshot": fail_then_succeed,
                "ROUTE_FLIGHTS": {},
                "ROUTE_FLIGHTS_LOCK": flights_lock,
            },
        ):
            with ThreadPoolExecutor(max_workers=callers) as pool:
                futures = [
                    pool.submit(
                        compute_route,
                        "bangalore",
                        ORIGIN,
                        DESTINATION,
                        "balanced",
                        "car",
                    )
                    for _ in range(callers)
                ]
                self.assertTrue(owner_started.wait(1.0))
                self.assertTrue(flights_lock.expected_entry_reached.wait(1.0))
                release_owner.set()
                failures = []
                for future in futures:
                    with self.assertRaisesRegex(
                        RuntimeError, "interrupted route computation"
                    ) as exc_info:
                        future.result(timeout=1.0)
                    failures.append(exc_info.exception)

            self.assertEqual(globals_dict["ROUTE_FLIGHTS"], {})
            # The barrier is only needed to make the failed group concurrent.
            globals_dict["ensure_current_risk_weights"] = lambda candidate: snapshot
            retry = compute_route(
                "bangalore", ORIGIN, DESTINATION, "balanced", "car"
            )
            self.assertEqual(globals_dict["ROUTE_FLIGHTS"], {})

        self.assertEqual(compute_calls, 2)
        self.assertEqual(len(failures), callers)
        self.assertEqual(retry, {"nodes": [1, 2]})

    def test_score_refresh_does_not_mix_an_old_route_with_new_generation(self) -> None:
        compute_route = self.routing["compute_route"]
        rebuild_vehicle_graphs = self.routing["rebuild_vehicle_graphs"]
        globals_dict = compute_route.__globals__
        old_graph = synthetic_graph(score=0.2, provenance="ml_synthetic")
        state = graph_state(self.routing, old_graph)
        old_snapshot_id = state.snapshot_id
        cache = OrderedDict()
        route_started = threading.Event()
        release_old_route = threading.Event()
        fetch_calls = 0
        fetch_lock = threading.Lock()

        def blocking_corridor_fetch(*args):
            nonlocal fetch_calls
            with fetch_lock:
                fetch_calls += 1
                call_number = fetch_calls
            if call_number == 1:
                route_started.set()
                self.assertTrue(release_old_route.wait(1.0))
            return {}, "ml_synthetic", 0, 0.0, 0.0, {}, "corridor-test"

        def fake_precompute(city, graph, vehicle, score_version, *, hour=None):
            return prepared_graph(
                self.routing,
                graph,
                vehicle=vehicle,
                hour=12 if hour is None else hour,
                score_version=score_version,
            )

        patches = route_runtime_patches(globals_dict)
        patches.update(
            {
                "GRAPH_CACHE": {"bangalore": state},
                "GRAPH_STATUS": {"bangalore": "ready"},
                "ROUTE_CACHE": cache,
                "ROUTE_CACHE_LOCK": threading.Lock(),
                "ROUTE_FLIGHTS": {},
                "ROUTE_FLIGHTS_LOCK": threading.Lock(),
                "fetch_corridor_scores": blocking_corridor_fetch,
                "precompute_vehicle_graph": fake_precompute,
            }
        )

        with patch.dict(globals_dict, patches):
            with ThreadPoolExecutor(max_workers=2) as pool:
                old_future = pool.submit(
                    compute_route,
                    "bangalore",
                    ORIGIN,
                    DESTINATION,
                    "balanced",
                    "car",
                )
                self.assertTrue(route_started.wait(1.0))

                rebuild_vehicle_graphs(
                    state,
                    {"1-2-0": 0.9},
                    2.0,
                    {"1-2-0": "trai"},
                    state.graph_revision, "scores-2.0", state.score_revision,
                )
                new_snapshot_id = state.snapshot_id
                self.assertNotEqual(new_snapshot_id, old_snapshot_id)
                self.assertIsNot(state.base_graph, old_graph)

                release_old_route.set()
                old_response = old_future.result(timeout=1.0)

            new_response = compute_route(
                "bangalore", ORIGIN, DESTINATION, "balanced", "car"
            )

            entries_by_snapshot = {
                json.loads(cache_key)["snapshot_id"]: entry
                for cache_key, entry in cache.items()
            }

        self.assertEqual(old_response["avg_connectivity"], 0.2)
        self.assertEqual(old_response["provenance_source"], "ml_synthetic")
        self.assertEqual(new_response["avg_connectivity"], 0.9)
        self.assertEqual(new_response["provenance_source"], "trai")
        self.assertEqual(entries_by_snapshot[old_snapshot_id]["score_version"], 1.0)
        self.assertEqual(entries_by_snapshot[new_snapshot_id]["score_version"], 2.0)

    def test_day_to_night_transition_keeps_route_corridor_cost_at_snapshot_hour(self) -> None:
        compute_route = self.routing["compute_route"]
        ensure_current_risk_weights = self.routing["ensure_current_risk_weights"]
        original_scalar_cost = self.routing["compute_scalar_route_cost"]
        globals_dict = compute_route.__globals__
        state = graph_state(self.routing, synthetic_graph(score=0.8), hour=12)
        route_started = threading.Event()
        release_route = threading.Event()
        current_hour = 12
        scalar_hours: list[int | None] = []

        def fake_fetch(*args):
            route_started.set()
            self.assertTrue(release_route.wait(1.0))
            return {"1-2-0": 0.8}, "trai", 1, 100.0, 100.0, {"1-2-0": "trai"}, "corridor-test"

        def fake_precompute(city, graph, vehicle, score_version, *, hour=None):
            return prepared_graph(
                self.routing,
                graph,
                vehicle=vehicle,
                hour=current_hour if hour is None else hour,
                score_version=score_version,
            )

        def recording_scalar_cost(*args, **kwargs):
            scalar_hours.append(kwargs.get("hour"))
            return original_scalar_cost(*args, **kwargs)

        patches = route_runtime_patches(globals_dict)
        patches.update(
            {
                "GRAPH_CACHE": {"bangalore": state},
                "GRAPH_STATUS": {"bangalore": "ready"},
                "ROUTE_CACHE": OrderedDict(),
                "ROUTE_CACHE_LOCK": threading.Lock(),
                "ROUTE_FLIGHTS": {},
                "ROUTE_FLIGHTS_LOCK": threading.Lock(),
                "city_local_hour": lambda city: current_hour,
                "fetch_corridor_scores": fake_fetch,
                "precompute_vehicle_graph": fake_precompute,
                "compute_scalar_route_cost": recording_scalar_cost,
            }
        )

        with patch.dict(globals_dict, patches):
            with ThreadPoolExecutor(max_workers=1) as pool:
                route_future = pool.submit(
                    compute_route,
                    "bangalore",
                    ORIGIN,
                    DESTINATION,
                    "balanced",
                    "car",
                )
                self.assertTrue(route_started.wait(1.0))
                current_hour = 23
                night_snapshot = ensure_current_risk_weights(state)
                self.assertEqual(night_snapshot.vehicle_graphs["car"].risk_hour, 23)
                release_route.set()
                response = route_future.result(timeout=1.0)

        self.assertEqual(scalar_hours, [12])
        self.assertEqual(response["signal_segments"][0]["score"], 0.8)

    def test_failed_refresh_leaves_published_snapshot_unchanged(self) -> None:
        rebuild_vehicle_graphs = self.routing["rebuild_vehicle_graphs"]
        globals_dict = rebuild_vehicle_graphs.__globals__
        old_graph = synthetic_graph(score=0.2)
        state = graph_state(self.routing, old_graph)
        old_vehicle_graphs = state.vehicle_graphs
        old_snapshot_id = state.snapshot_id
        state.score_refreshing = True

        with patch.dict(
            globals_dict,
            {
                "GRAPH_CACHE": {"bangalore": state},
                "city_local_hour": lambda city: 12,
                "precompute_vehicle_graph": (
                    lambda *args, **kwargs: (_ for _ in ()).throw(
                        RuntimeError("simulated weight build failure")
                    )
                ),
            },
        ):
            rebuild_vehicle_graphs(
                state,
                {"1-2-0": 0.95},
                2.0,
                {"1-2-0": "trai"},
                state.graph_revision, "scores-2.0", state.score_revision,
            )

        self.assertIs(state.base_graph, old_graph)
        self.assertIs(state.vehicle_graphs, old_vehicle_graphs)
        self.assertEqual(state.snapshot_id, old_snapshot_id)
        self.assertEqual(state.scores_updated_at, 1.0)
        self.assertEqual(old_graph.edges[1, 2, 0]["connectivity_score"], 0.2)
        self.assertFalse(state.score_refreshing)

    def test_concurrent_score_refreshes_reserve_before_fetching(self) -> None:
        refresh_scores_for_city = self.routing["refresh_scores_for_city"]
        globals_dict = refresh_scores_for_city.__globals__
        state = graph_state(self.routing, synthetic_graph())
        fetch_started = threading.Event()
        release_fetch = threading.Event()
        second_finished = threading.Event()
        calls_lock = threading.Lock()
        fetch_calls = 0
        submitted_jobs = 0

        def slow_fetch(city, graph_revision):
            nonlocal fetch_calls
            with calls_lock:
                fetch_calls += 1
            fetch_started.set()
            self.assertTrue(release_fetch.wait(1.0))
            return {"1-2-0": 0.8}, 2.0, {"1-2-0": "trai"}, "scores-2.0"

        def fake_rebuild(candidate_state, scores, updated_at, edge_sources, *revisions):
            self.assertIs(candidate_state, state)
            with candidate_state.lock:
                candidate_state.score_refreshing = False

        class ImmediatePool:
            def submit(self, function, *args):
                nonlocal submitted_jobs
                submitted_jobs += 1
                function(*args)

        failures: list[BaseException] = []

        def invoke(*, mark_second=False):
            try:
                refresh_scores_for_city("bangalore")
            except BaseException as exc:
                failures.append(exc)
            finally:
                if mark_second:
                    second_finished.set()

        with patch.dict(
            globals_dict,
            {
                "GRAPH_CACHE": {"bangalore": state},
                "GRAPH_STATUS": {"bangalore": "ready"},
                "safe_fetch_city_scores": slow_fetch,
                "rebuild_vehicle_graphs": fake_rebuild,
                "THREAD_POOL": ImmediatePool(),
            },
        ):
            first = threading.Thread(target=invoke)
            second = threading.Thread(target=invoke, kwargs={"mark_second": True})
            first.start()
            self.assertTrue(fetch_started.wait(1.0))
            second.start()
            self.assertTrue(second_finished.wait(1.0))
            self.assertEqual(fetch_calls, 1)
            release_fetch.set()
            first.join(1.0)
            second.join(1.0)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(fetch_calls, 1)
        self.assertEqual(submitted_jobs, 1)
        self.assertFalse(state.score_refreshing)

    def test_concurrent_graph_loaders_build_and_publish_once(self) -> None:
        build_graph_state = self.routing["build_graph_state"]
        globals_dict = build_graph_state.__globals__
        graph = synthetic_graph(score=0.7)
        load_started = threading.Event()
        release_load = threading.Event()
        second_finished = threading.Event()
        load_calls = 0
        results: list[object] = []
        failures: list[BaseException] = []

        def fake_load(city):
            nonlocal load_calls
            load_calls += 1
            load_started.set()
            self.assertTrue(release_load.wait(1.0))
            return graph

        def invoke(*, mark_second=False):
            try:
                results.append(build_graph_state("bangalore"))
            except BaseException as exc:  # Preserve worker failures for the main assertion.
                failures.append(exc)
            finally:
                if mark_second:
                    second_finished.set()

        car_profile = globals_dict["VEHICLE_PROFILES"]["car"]
        city_lock = ObservableLock()
        with patch.dict(
            globals_dict,
            {
                "GRAPH_CACHE": {},
                "CITY_LOCKS": defaultdict(
                    threading.Lock, {"bangalore": city_lock}
                ),
                "VEHICLE_PROFILES": {"car": car_profile},
                "load_or_fetch_graph": fake_load,
                "annotate_base_graph": lambda candidate: candidate,
                "safe_fetch_city_scores": lambda *args: ({}, 1.0, {}, "scores-1.0"),
                "build_node_index": lambda candidate: None,
                "city_local_hour": lambda city: 12,
                "precompute_vehicle_graph": (
                    lambda city, candidate, vehicle, version, hour=None: prepared_graph(
                        self.routing,
                        candidate,
                        vehicle=vehicle,
                        hour=12 if hour is None else hour,
                        score_version=version,
                    )
                ),
            },
        ):
            first = threading.Thread(target=invoke)
            second = threading.Thread(target=invoke, kwargs={"mark_second": True})
            first.start()
            self.assertTrue(load_started.wait(1.0))
            second.start()
            self.assertTrue(city_lock.expected_entry_reached.wait(1.0))
            self.assertFalse(second_finished.is_set())
            self.assertEqual(load_calls, 1)
            release_load.set()
            first.join(1.0)
            second.join(1.0)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(load_calls, 1)
        self.assertEqual(len(results), 2)
        self.assertIs(results[0], results[1])

    def test_graph_loader_is_read_only_and_rejects_replaced_publication(self) -> None:
        load_or_fetch_graph = self.routing["load_or_fetch_graph"]
        globals_dict = load_or_fetch_graph.__globals__

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "bangalore.graphml"
            target.write_bytes(b"published-graph")
            graph = synthetic_graph()

            with patch.dict(
                globals_dict,
                {
                    "graph_cache_path": lambda city: target,
                    "ensure_connected_graph": lambda candidate: candidate,
                },
            ), patch.object(globals_dict["ox"], "load_graphml", return_value=graph):
                loaded = load_or_fetch_graph("bangalore")

            stat = target.stat()
            self.assertIs(loaded, graph)
            self.assertEqual(target.read_bytes(), b"published-graph")
            self.assertEqual(
                graph.graph["_routing_graph_revision"],
                (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns),
            )

            replacement = target.parent / "replacement.graphml"
            replacement.write_bytes(b"a-different-complete-publication")

            def replace_during_read(path, **kwargs):
                globals_dict["os"].replace(replacement, target)
                return synthetic_graph()

            with patch.dict(
                globals_dict,
                {
                    "graph_cache_path": lambda city: target,
                    "ensure_connected_graph": lambda candidate: candidate,
                },
            ), patch.object(
                globals_dict["ox"], "load_graphml", side_effect=replace_during_read
            ):
                with self.assertRaisesRegex(OSError, "changed while loading"):
                    load_or_fetch_graph("bangalore")

    def test_changed_graph_publication_invalidates_readiness_and_rebuilds(self) -> None:
        graph_is_ready = self.routing["graph_is_ready"]
        build_graph_state = self.routing["build_graph_state"]
        globals_dict = graph_is_ready.__globals__
        old_graph = synthetic_graph(score=0.2)
        state = graph_state(self.routing, old_graph)
        load_calls = 0

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "bangalore.graphml"
            target.write_bytes(b"first-publication")
            original = target.stat()
            old_graph.graph["_routing_graph_revision"] = (
                original.st_dev,
                original.st_ino,
                original.st_size,
                original.st_mtime_ns,
            )

            cache = {"bangalore": state}
            status = {"bangalore": "ready"}
            with patch.dict(
                globals_dict,
                {
                    "GRAPH_CACHE": cache,
                    "GRAPH_STATUS": status,
                    "graph_cache_path": lambda city: target,
                },
            ):
                self.assertTrue(graph_is_ready("bangalore"))
                replacement = target.parent / "new.graphml"
                replacement.write_bytes(b"second-publication-with-new-size")
                globals_dict["os"].replace(replacement, target)
                self.assertFalse(graph_is_ready("bangalore"))

                new_graph = synthetic_graph(score=0.8, provenance="trai")
                current = target.stat()
                new_graph.graph["_routing_graph_revision"] = (
                    current.st_dev,
                    current.st_ino,
                    current.st_size,
                    current.st_mtime_ns,
                )

                def load_new(city):
                    nonlocal load_calls
                    load_calls += 1
                    return new_graph

                car_profile = globals_dict["VEHICLE_PROFILES"]["car"]
                with patch.dict(
                    globals_dict,
                    {
                        "CITY_LOCKS": defaultdict(threading.Lock),
                        "VEHICLE_PROFILES": {"car": car_profile},
                        "load_or_fetch_graph": load_new,
                        "annotate_base_graph": lambda candidate: candidate,
                        "safe_fetch_city_scores": lambda *args: ({}, 2.0, {}, "scores-2.0"),
                        "build_node_index": lambda candidate: None,
                        "city_local_hour": lambda city: 12,
                        "precompute_vehicle_graph": (
                            lambda city, candidate, vehicle, version, hour=None: prepared_graph(
                                self.routing,
                                candidate,
                                vehicle=vehicle,
                                hour=12 if hour is None else hour,
                                score_version=version,
                            )
                        ),
                    },
                ):
                    rebuilt = build_graph_state("bangalore")

                self.assertIsNot(rebuilt, state)
                self.assertIs(rebuilt.base_graph, new_graph)
                self.assertTrue(graph_is_ready("bangalore"))

        self.assertEqual(load_calls, 1)

    def test_real_precompute_and_pathfinding_preserve_modes_and_vehicles(self) -> None:
        compute_route = self.routing["compute_route"]
        precompute_vehicle_graph = self.routing["precompute_vehicle_graph"]
        fallback_edge_weight = self.routing["fallback_edge_weight"]
        globals_dict = compute_route.__globals__
        graph = synthetic_diamond()
        vehicle_graphs = {
            vehicle: precompute_vehicle_graph(
                "bangalore", graph, vehicle, 1.0, hour=12
            )
            for vehicle in globals_dict["VEHICLE_PROFILES"]
        }
        state = self.routing["GraphState"](
            city="bangalore",
            base_graph=graph,
            expires_at=time.time() + 60,
            scores_updated_at=1.0,
            edge_count=4,
            node_index=None,
            vehicle_graphs=vehicle_graphs,
            snapshot_id="diamond-generation",
        )

        patches = route_runtime_patches(globals_dict)
        patches.pop("compute_path_with_fallbacks")
        patches.update(
            {
                "GRAPH_CACHE": {"bangalore": state},
                "GRAPH_STATUS": {"bangalore": "ready"},
                "ROUTE_CACHE": OrderedDict(),
                "ROUTE_CACHE_LOCK": threading.Lock(),
                "ROUTE_FLIGHTS": {},
                "ROUTE_FLIGHTS_LOCK": threading.Lock(),
                "find_nearest_node": (
                    lambda candidate, latitude, longitude, index: 1
                    if longitude == ORIGIN[1]
                    else 4
                ),
            }
        )

        with patch.dict(globals_dict, patches):
            results = {
                (mode, vehicle): compute_route(
                    "bangalore", ORIGIN, DESTINATION, mode, vehicle
                )
                for vehicle in globals_dict["VEHICLE_PROFILES"]
                for mode in ("fastest", "balanced", "connected")
            }

        for vehicle in globals_dict["VEHICLE_PROFILES"]:
            with self.subTest(vehicle=vehicle, mode="fastest"):
                fastest = results[("fastest", vehicle)]
                # Phase 2B1 caps each vehicle's planning speed. Bike/scooter now
                # prefer the 1200m branch; car/truck use the 2000m faster branch.
                short_branch = vehicle in {"bike", "scooter"}
                self.assertEqual(fastest["nodes"], [1, 3, 4] if short_branch else [1, 2, 4])
                self.assertEqual(fastest["total_time_min"], {
                    "bike": 4.0, "scooter": 1.7, "car": 1.3, "truck": 1.5,
                }[vehicle])
                self.assertEqual(fastest["provenance_source"], "trai" if short_branch else "ml_synthetic")
                self.assertEqual(len(fastest["path_geojson"]["coordinates"]), 3)
            for mode in ("balanced", "connected"):
                with self.subTest(vehicle=vehicle, mode=mode):
                    covered = results[(mode, vehicle)]
                    self.assertEqual(covered["nodes"], [1, 3, 4])
                    self.assertEqual(covered["total_time_min"], 4.0 if vehicle == "bike" else 1.7)
                    self.assertEqual(covered["provenance_source"], "trai")
                    self.assertEqual(
                        covered["path_geojson"]["coordinates"],
                        [
                            (77.590, 12.970),
                            (77.595, 12.965),
                            (77.600, 12.970),
                        ],
                    )

        # A missing edge index falls back to travel seconds derived from length
        # and speed; the former length/30 heuristic would return 30 here.
        self.assertAlmostEqual(
            fallback_edge_weight(
                {"length": 900.0, "speed_kph": 36.0, "travel_time": 0.0}
            ),
            90.0,
        )

    def test_interrupted_cache_publication_preserves_previous_file(self) -> None:
        persist_route_cache = self.routing["persist_route_cache"]
        globals_dict = persist_route_cache.__globals__

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "route_cache.json"
            target.write_text('{"complete":"old"}', encoding="utf-8")
            with patch.dict(
                globals_dict,
                {
                    "ROUTE_CACHE_PATH": target,
                    "ROUTE_CACHE": OrderedDict({"new": {"generation": 2}}),
                    "ROUTE_CACHE_LOCK": threading.Lock(),
                    "ROUTE_CACHE_WRITE_LOCK": threading.Lock(),
                },
            ):
                with patch.object(
                    globals_dict["os"],
                    "replace",
                    side_effect=OSError("simulated interrupted publication"),
                ):
                    persist_route_cache()

            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"complete": "old"})
            self.assertEqual(list(target.parent.glob(".route_cache.json.*.tmp")), [])

    def test_competing_cache_persistence_publishes_latest_snapshot(self) -> None:
        persist_route_cache = self.routing["persist_route_cache"]
        globals_dict = persist_route_cache.__globals__
        real_json_dump = json.dump
        first_dump_started = threading.Event()
        second_dump_started = threading.Event()
        release_first_dump = threading.Event()
        dump_lock = threading.Lock()
        dump_calls = 0

        def controlled_dump(payload, stream):
            nonlocal dump_calls
            with dump_lock:
                dump_calls += 1
                call_number = dump_calls
            if call_number == 1:
                first_dump_started.set()
                self.assertTrue(release_first_dump.wait(1.0))
            else:
                second_dump_started.set()
            return real_json_dump(payload, stream)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "route_cache.json"
            cache = OrderedDict({"old": {"generation": 1}})
            cache_lock = threading.Lock()
            write_lock = ObservableLock()
            with patch.dict(
                globals_dict,
                {
                    "ROUTE_CACHE_PATH": target,
                    "ROUTE_CACHE": cache,
                    "ROUTE_CACHE_LOCK": cache_lock,
                    "ROUTE_CACHE_WRITE_LOCK": write_lock,
                },
            ), patch.object(globals_dict["json"], "dump", side_effect=controlled_dump):
                first = threading.Thread(target=persist_route_cache)
                second = threading.Thread(target=persist_route_cache)
                first.start()
                self.assertTrue(first_dump_started.wait(1.0))
                with cache_lock:
                    cache.clear()
                    cache["new"] = {"generation": 2}
                second.start()
                self.assertTrue(write_lock.expected_entry_reached.wait(1.0))
                self.assertFalse(second_dump_started.is_set())
                release_first_dump.set()
                first.join(1.0)
                second.join(1.0)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertTrue(second_dump_started.is_set())
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                {"new": {"generation": 2}},
            )
            self.assertEqual(list(target.parent.glob(".route_cache.json.*.tmp")), [])

    def test_score_snapshot_generation_is_stable_and_invalidates_on_inputs(self) -> None:
        score_snapshot_id = self.routing["score_snapshot_id"]
        store_cached_route = self.routing["store_cached_route"]
        get_cached_route = self.routing["get_cached_route"]
        globals_dict = store_cached_route.__globals__

        first = synthetic_graph(score=0.7, provenance="trai")
        second = synthetic_graph(score=0.7, provenance="trai")
        revision = (42, 7, 4096, 1_700_000_000_000_000_000)
        first.graph["_routing_graph_revision"] = revision
        second.graph["_routing_graph_revision"] = revision

        baseline = score_snapshot_id(first, "scores-1")
        restart_generation = score_snapshot_id(second, "scores-1")
        self.assertEqual(restart_generation, baseline)

        changed_score = synthetic_graph(score=0.8, provenance="trai")
        changed_score.graph["_routing_graph_revision"] = revision
        changed_provider = synthetic_graph(score=0.7, provenance="opencellid")
        changed_provider.graph["_routing_graph_revision"] = revision
        changed_revision = synthetic_graph(score=0.7, provenance="trai")
        changed_revision.graph["_routing_graph_revision"] = (*revision[:-1], revision[-1] + 1)
        changed_revision.graph["graph_revision"] = "graph-new"

        # The publisher rotates score identity for value/provenance changes;
        # wall clocks and filesystem stat tuples no longer establish identity.
        changed_version_generation = score_snapshot_id(second, "scores-2")
        changed_score_generation = score_snapshot_id(changed_score, "scores-changed")
        changed_provider_generation = score_snapshot_id(changed_provider, "provenance-changed")
        changed_revision_generation = score_snapshot_id(changed_revision, "scores-1")
        self.assertNotEqual(changed_version_generation, baseline)
        self.assertNotEqual(changed_score_generation, baseline)
        self.assertNotEqual(changed_provider_generation, baseline)
        self.assertNotEqual(changed_revision_generation, baseline)

        cache = OrderedDict()
        with patch.dict(
            globals_dict,
            {
                "ROUTE_CACHE": cache,
                "ROUTE_CACHE_LOCK": threading.Lock(),
                "persist_route_cache": lambda: None,
            },
        ):
            source_response = {"nodes": [1, 2], "details": {"quality": "stable"}}
            store_cached_route(
                "bangalore",
                ORIGIN,
                DESTINATION,
                "balanced",
                "car",
                10.0,
                source_response,
                "day",
                baseline,
            )
            source_response["details"]["quality"] = "mutated by caller"
            cached_response = get_cached_route(
                "bangalore",
                ORIGIN,
                DESTINATION,
                "balanced",
                "car",
                10.0,
                "day",
                restart_generation,
            )
            self.assertEqual(cached_response["details"]["quality"], "stable")
            cached_response["details"]["quality"] = "mutated cache hit"
            second_hit = get_cached_route(
                "bangalore",
                ORIGIN,
                DESTINATION,
                "balanced",
                "car",
                10.0,
                "day",
                restart_generation,
            )
            self.assertEqual(second_hit["details"]["quality"], "stable")
            for changed_generation in (
                changed_version_generation,
                changed_score_generation,
                changed_provider_generation,
                changed_revision_generation,
            ):
                self.assertIsNone(
                    get_cached_route(
                        "bangalore",
                        ORIGIN,
                        DESTINATION,
                        "balanced",
                        "car",
                        10.0,
                        "day",
                        changed_generation,
                    )
                )

        unversioned = synthetic_graph()
        del unversioned.graph["graph_revision"]
        with self.assertRaises(self.routing["RevisionCompatibilityError"]):
            score_snapshot_id(unversioned, "scores-1")

    def test_missing_graph_waits_for_data_service_publication_then_recovers(self) -> None:
        preload_city_graph = self.routing["preload_city_graph"]
        globals_dict = preload_city_graph.__globals__
        graph_not_published = self.routing["GraphNotPublishedError"]
        real_asyncio_sleep = asyncio.sleep
        clock = 100.0
        attempts = 0
        sleeps: list[float] = []
        statuses: list[str] = []

        def monotonic():
            return clock

        def publish_later(city):
            nonlocal attempts
            attempts += 1
            if attempts < 4:
                raise graph_not_published("shared graph is not published yet")
            return object()

        async def fake_sleep(seconds):
            nonlocal clock
            sleeps.append(seconds)
            statuses.append(globals_dict["GRAPH_STATUS"]["bangalore"])
            clock += seconds
            await real_asyncio_sleep(0)

        async def exercise():
            with patch.dict(
                globals_dict,
                {
                    "GRAPH_STATUS": {},
                    "GRAPH_ERRORS": {},
                    "GRAPH_PUBLICATION_WAIT_SECONDS": 600,
                    "request_data_service_preload": lambda city: None,
                    "build_graph_state": publish_later,
                    "time": SimpleNamespace(monotonic=monotonic),
                    "asyncio": SimpleNamespace(
                        to_thread=call_inline,
                        sleep=fake_sleep,
                        create_task=asyncio.create_task,
                    ),
                },
            ):
                await preload_city_graph("bangalore")
                return (
                    globals_dict["GRAPH_STATUS"].copy(),
                    globals_dict["GRAPH_ERRORS"].copy(),
                )

        final_status, final_errors = asyncio.run(exercise())

        self.assertEqual(attempts, 4)
        self.assertEqual(sleeps, [5, 5, 5])
        self.assertEqual(statuses, ["loading", "loading", "loading"])
        self.assertEqual(final_status["bangalore"], "ready")
        self.assertNotIn("bangalore", final_errors)

    def test_missing_graph_publication_deadline_becomes_terminal(self) -> None:
        preload_city_graph = self.routing["preload_city_graph"]
        globals_dict = preload_city_graph.__globals__
        graph_not_published = self.routing["GraphNotPublishedError"]
        real_asyncio_sleep = asyncio.sleep
        clock = 50.0
        attempts = 0
        sleeps: list[float] = []

        def monotonic():
            return clock

        def never_published(city):
            nonlocal attempts
            attempts += 1
            raise graph_not_published("publication deadline expired")

        async def fake_sleep(seconds):
            nonlocal clock
            sleeps.append(seconds)
            clock += seconds
            await real_asyncio_sleep(0)

        async def exercise():
            with patch.dict(
                globals_dict,
                {
                    "GRAPH_STATUS": {},
                    "GRAPH_ERRORS": {},
                    "GRAPH_PUBLICATION_WAIT_SECONDS": 10,
                    "request_data_service_preload": lambda city: None,
                    "build_graph_state": never_published,
                    "time": SimpleNamespace(monotonic=monotonic),
                    "asyncio": SimpleNamespace(
                        to_thread=call_inline, sleep=fake_sleep
                    ),
                },
            ):
                await preload_city_graph("bangalore")
                return (
                    globals_dict["GRAPH_STATUS"].copy(),
                    globals_dict["GRAPH_ERRORS"].copy(),
                )

        final_status, final_errors = asyncio.run(exercise())

        self.assertEqual(attempts, 3)
        self.assertEqual(sleeps, [5, 5])
        self.assertEqual(final_status["bangalore"], "error")
        self.assertIn("publication deadline expired", final_errors["bangalore"])

    def test_preload_retries_transient_failures_and_recovers(self) -> None:
        preload_city_graph = self.routing["preload_city_graph"]
        globals_dict = preload_city_graph.__globals__
        real_asyncio_sleep = asyncio.sleep
        attempts = 0
        backoffs: list[int] = []
        statuses_during_backoff: list[str] = []

        def transient_then_success(city):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise OSError(f"temporary graph read failure {attempts}")
            return object()

        async def fake_sleep(seconds):
            backoffs.append(seconds)
            statuses_during_backoff.append(globals_dict["GRAPH_STATUS"]["bangalore"])
            await real_asyncio_sleep(0)

        async def exercise():
            with patch.dict(
                globals_dict,
                {
                    "GRAPH_STATUS": {},
                    "GRAPH_ERRORS": {},
                    "request_data_service_preload": lambda city: None,
                    "build_graph_state": transient_then_success,
                    "asyncio": SimpleNamespace(
                        to_thread=call_inline, sleep=fake_sleep
                    ),
                },
            ):
                await preload_city_graph("bangalore")
                return (
                    globals_dict["GRAPH_STATUS"].copy(),
                    globals_dict["GRAPH_ERRORS"].copy(),
                )

        statuses, errors = asyncio.run(exercise())

        self.assertEqual(attempts, 3)
        self.assertEqual(backoffs, [5, 10])
        self.assertEqual(statuses_during_backoff, ["loading", "loading"])
        self.assertEqual(statuses["bangalore"], "ready")
        self.assertNotIn("bangalore", errors)

    def test_preload_exhaustion_returns_503_until_explicit_restart(self) -> None:
        preload_city_graph = self.routing["preload_city_graph"]
        schedule_preload = self.routing["schedule_preload"]
        preload_endpoint = self.routing["preload"]
        route_endpoint = self.routing["route"]
        globals_dict = preload_city_graph.__globals__
        request_model = self.routing["RouteRequest"]
        real_asyncio_sleep = asyncio.sleep
        attempts = 0
        should_succeed = False

        def build(city):
            nonlocal attempts
            attempts += 1
            if not should_succeed:
                raise OSError("graph source stayed unavailable")
            return object()

        async def fake_sleep(seconds):
            await real_asyncio_sleep(0)

        async def exercise():
            nonlocal should_succeed
            with patch.dict(
                globals_dict,
                {
                    "GRAPH_CACHE": {},
                    "GRAPH_STATUS": {},
                    "GRAPH_ERRORS": {},
                    "PRELOAD_TASKS": {},
                    "request_data_service_preload": lambda city: None,
                    "build_graph_state": build,
                    "asyncio": SimpleNamespace(
                        to_thread=call_inline,
                        sleep=fake_sleep,
                        create_task=asyncio.create_task,
                    ),
                },
            ):
                await preload_city_graph("bangalore")
                exhausted_status = globals_dict["GRAPH_STATUS"]["bangalore"]
                automatic_status = schedule_preload("bangalore")
                response = await route_endpoint(
                    request_model(
                        city="bangalore",
                        origin=list(ORIGIN),
                        destination=list(DESTINATION),
                        mode="balanced",
                        vehicle="car",
                    )
                )
                should_succeed = True
                restart = await preload_endpoint("bangalore")
                await globals_dict["PRELOAD_TASKS"]["bangalore"]
                return exhausted_status, automatic_status, response, restart, globals_dict[
                    "GRAPH_STATUS"
                ]["bangalore"]

        exhausted, automatic, response, restart, final_status = asyncio.run(exercise())

        self.assertEqual(attempts, 4)
        self.assertEqual(exhausted, "error")
        self.assertEqual(automatic, "error")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.body)["code"], "graph_unavailable")
        self.assertEqual(restart["status"], "loading")
        self.assertEqual(final_status, "ready")

    def test_readiness_change_after_route_admission_returns_loading_contract(self) -> None:
        route_endpoint = self.routing["route"]
        globals_dict = route_endpoint.__globals__
        request_model = self.routing["RouteRequest"]
        http_exception = self.routing["HTTPException"]
        status = {"bangalore": "ready"}
        readiness = iter((True, False))

        def schedule(city):
            status[city] = "loading"
            return "loading"

        def expired_in_worker(*args):
            raise http_exception(status_code=503, detail="Graph not loaded")

        async def exercise(executor):
            with patch.dict(
                globals_dict,
                {
                    "GRAPH_STATUS": status,
                    "GRAPH_ERRORS": {},
                    "graph_is_ready": lambda city: next(readiness),
                    "schedule_preload": schedule,
                    "compute_route": expired_in_worker,
                    "THREAD_POOL": executor,
                    "free_gpu_memory": lambda: None,
                },
            ):
                return await route_endpoint(
                    request_model(
                        city="bangalore",
                        origin=list(ORIGIN),
                        destination=list(DESTINATION),
                        mode="balanced",
                        vehicle="car",
                    )
                )

        with ThreadPoolExecutor(max_workers=1) as executor:
            response = asyncio.run(exercise(executor))

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.headers["retry-after"], "5")
        self.assertEqual(payload["status"], "loading")
        self.assertEqual(payload["retry_after"], 5)

    def test_terminal_worker_503_is_structured_graph_unavailable(self) -> None:
        route_endpoint = self.routing["route"]
        globals_dict = route_endpoint.__globals__
        request_model = self.routing["RouteRequest"]
        http_exception = self.routing["HTTPException"]

        def missing_vehicle(*args):
            raise http_exception(status_code=503, detail="Vehicle graph unavailable")

        async def exercise(executor):
            with patch.dict(
                globals_dict,
                {
                    "GRAPH_STATUS": {"bangalore": "ready"},
                    "GRAPH_ERRORS": {},
                    "graph_is_ready": lambda city: True,
                    "compute_route": missing_vehicle,
                    "THREAD_POOL": executor,
                    "free_gpu_memory": lambda: None,
                },
            ):
                return await route_endpoint(
                    request_model(
                        city="bangalore",
                        origin=list(ORIGIN),
                        destination=list(DESTINATION),
                        mode="balanced",
                        vehicle="car",
                    )
                )

        with ThreadPoolExecutor(max_workers=1) as executor:
            response = asyncio.run(exercise(executor))

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("retry-after", response.headers)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["code"], "graph_unavailable")
        self.assertEqual(payload["message"], "Vehicle graph unavailable")

    def test_route_endpoint_keeps_event_loop_responsive(self) -> None:
        route_endpoint = self.routing["route"]
        globals_dict = route_endpoint.__globals__
        request_model = self.routing["RouteRequest"]
        release_worker = threading.Event()

        async def exercise(executor):
            loop = asyncio.get_running_loop()
            worker_started = asyncio.Event()

            def blocking_route(*args):
                loop.call_soon_threadsafe(worker_started.set)
                self.assertTrue(release_worker.wait(1.0))
                return {"nodes": [1, 2]}

            with patch.dict(
                globals_dict,
                {
                    "GRAPH_STATUS": {"bangalore": "ready"},
                    "graph_is_ready": lambda city: True,
                    "compute_route": blocking_route,
                    "THREAD_POOL": executor,
                    "free_gpu_memory": lambda: None,
                },
            ):
                task = asyncio.create_task(
                    route_endpoint(
                        request_model(
                            city="bangalore",
                            origin=list(ORIGIN),
                            destination=list(DESTINATION),
                            mode="balanced",
                            vehicle="car",
                        )
                    )
                )
                await asyncio.wait_for(worker_started.wait(), timeout=1.0)

                heartbeat_ran = False

                async def heartbeat():
                    nonlocal heartbeat_ran
                    await asyncio.sleep(0)
                    heartbeat_ran = True

                await asyncio.wait_for(heartbeat(), timeout=0.2)
                self.assertTrue(heartbeat_ran)
                self.assertFalse(task.done())
                release_worker.set()
                return await asyncio.wait_for(task, timeout=1.0)

        with ThreadPoolExecutor(max_workers=1) as executor:
            response = asyncio.run(exercise(executor))

        self.assertEqual(response, {"nodes": [1, 2]})


if __name__ == "__main__":
    unittest.main()
