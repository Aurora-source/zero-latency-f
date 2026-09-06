from __future__ import annotations

import asyncio
import runpy
import sys
import tempfile
import threading
import time
import unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import networkx as nx
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_MAIN = REPO_ROOT / "services" / "data-service" / "main.py"


def load_data_service() -> dict[str, object]:
    module_dir = str(DATA_MAIN.parent)
    inserted = False
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
        inserted = True
    try:
        return runpy.run_path(str(DATA_MAIN))
    finally:
        if inserted:
            sys.path.remove(module_dir)


def synthetic_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph(crs="EPSG:4326", graph_revision="graph-test")
    graph.add_node(1, x=77.59, y=12.97)
    graph.add_node(2, x=77.60, y=12.98)
    graph.add_edge(1, 2, key=0, length=1000.0, highway="residential")
    return graph


class ObservableRLock:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.observe_attempts = False
        self.acquire_attempted = threading.Event()

    def __enter__(self):
        if self.observe_attempts:
            self.acquire_attempted.set()
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._lock.release()


class DataConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_data_service()

    def test_equivalent_corridor_requests_share_ingestion_and_scoring(self) -> None:
        post_corridor_scores = self.data["post_corridor_scores"]
        globals_dict = post_corridor_scores.__globals__
        payload = self.data["CorridorScoresRequest"](
            city="bangalore",
            graph_revision="graph-test",
            score_revision="score-test",
            origin=[12.97, 77.59],
            destination=[12.98, 77.60],
            edge_coords={"1-2-0": [12.975, 77.595]},
            padding_km=3.0,
        )
        fetch_calls = 0
        score_calls = 0
        state = SimpleNamespace(
            graph_revision="graph-test",
            score_revision="score-test",
        )

        async def exercise() -> tuple[dict[str, object], dict[str, object]]:
            nonlocal fetch_calls, score_calls
            fetch_started = asyncio.Event()
            release_fetch = asyncio.Event()

            async def fake_fetch(*args, **kwargs):
                nonlocal fetch_calls
                fetch_calls += 1
                fetch_started.set()
                await release_fetch.wait()
                return (
                    [{"id": "tower-1", "lat": 12.975, "lon": 77.595}],
                    {
                        "min_lat": 12.94,
                        "min_lon": 77.56,
                        "max_lat": 13.01,
                        "max_lon": 77.63,
                    },
                    {
                        "source": "opencellid",
                        "real_data_source": "opencellid",
                        "live_full_bbox": True,
                        "real_data_coverage_percent": 100.0,
                    },
                )

            def fake_score(edge_coords, towers):
                nonlocal score_calls
                score_calls += 1
                return {edge_id: 0.82 for edge_id in edge_coords}

            with patch.dict(
                globals_dict,
                {
                    "fetch_towers_cached": fake_fetch,
                    "compute_scores_from_towers": fake_score,
                    "CORRIDOR_SCORE_TASKS": {},
                    "GRAPH_CACHE": {"bangalore": state},
                },
            ):
                first = asyncio.create_task(post_corridor_scores(payload))
                await fetch_started.wait()
                second = asyncio.create_task(post_corridor_scores(payload))
                await asyncio.sleep(0)
                release_fetch.set()
                first_result, second_result = await asyncio.gather(first, second)
            return first_result, second_result

        first_result, second_result = asyncio.run(exercise())

        self.assertEqual(fetch_calls, 1)
        self.assertEqual(score_calls, 1)
        self.assertEqual(first_result, second_result)
        self.assertEqual(first_result["scores"], {"1-2-0": 0.82})
        self.assertEqual(first_result["edge_sources"], {"1-2-0": "opencellid"})

    def test_equivalent_tower_requests_queue_and_fetch_once(self) -> None:
        fetch_towers_cached = self.data["fetch_towers_cached"]
        globals_dict = fetch_towers_cached.__globals__
        cache_queries = 0
        queue_calls = 0
        live_calls = 0

        async def exercise():
            nonlocal cache_queries, queue_calls, live_calls
            live_started = asyncio.Event()
            release_live = asyncio.Event()

            def fake_cached_towers(*args, **kwargs):
                nonlocal cache_queries
                cache_queries += 1
                return [], ["tile-1"], set(), []

            def fake_queue(tile_ids):
                nonlocal queue_calls
                queue_calls += 1
                return len(tile_ids)

            async def fake_live_fetch(*args, **kwargs):
                nonlocal live_calls
                live_calls += 1
                live_started.set()
                await release_live.wait()
                return [{"id": "tower-1", "lat": 12.975, "lon": 77.595}]

            with patch.dict(
                globals_dict,
                {
                    "CORRIDOR_CACHE": {},
                    "CORRIDOR_FETCH_TASKS": {},
                    "cached_towers_for_bbox": fake_cached_towers,
                    "corridor_coverage_metadata": lambda *args, **kwargs: {
                        "source": kwargs.get("live_source", "unknown"),
                        "live_full_bbox": kwargs.get("live_full_bbox", False),
                    },
                    "queue_missing_tower_tiles": fake_queue,
                    "live_tower_fetch_available": lambda: True,
                    "fetch_towers_for_corridor": fake_live_fetch,
                    "tower_provenance_source": lambda: "opencellid",
                },
            ):
                first = asyncio.create_task(
                    fetch_towers_cached(12.97, 77.59, 12.98, 77.60, 3.0)
                )
                await live_started.wait()
                second = asyncio.create_task(
                    fetch_towers_cached(12.97, 77.59, 12.98, 77.60, 3.0)
                )
                await asyncio.sleep(0)
                release_live.set()
                return await asyncio.gather(first, second)

        first_result, second_result = asyncio.run(exercise())

        self.assertEqual(cache_queries, 1)
        self.assertEqual(queue_calls, 1)
        self.assertEqual(live_calls, 1)
        self.assertEqual(first_result, second_result)

    def test_cancelled_singleflight_waiter_does_not_cancel_or_leak_work(self) -> None:
        run_singleflight = self.data["run_singleflight"]

        async def exercise() -> None:
            tasks = {}
            started = asyncio.Event()
            release = asyncio.Event()

            async def operation() -> str:
                started.set()
                await release.wait()
                return "complete"

            waiter = asyncio.create_task(
                run_singleflight(tasks, "corridor", operation)
            )
            await started.wait()
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            self.assertIn("corridor", tasks)
            release.set()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertEqual(tasks, {})

        asyncio.run(exercise())

    def test_city_state_load_is_deduplicated_and_published_after_hydration(self) -> None:
        load_city_state = self.data["load_city_state"]
        globals_dict = load_city_state.__globals__
        graph = synthetic_graph()
        state = SimpleNamespace(
            expires_at=time.time() + 60.0,
            segments=[object()],
            real_score_sources={},
            published=False,
        )
        hydrate_started = threading.Event()
        release_hydration = threading.Event()
        second_finished = threading.Event()
        load_calls = 0

        def fake_load_graph(city: str):
            nonlocal load_calls
            load_calls += 1
            return graph

        def fake_build(city: str, loaded_graph, expires_at: float):
            self.assertIs(loaded_graph, graph)
            state.expires_at = expires_at
            return state

        def fake_hydrate(city: str, candidate_state) -> int:
            self.assertNotIn(city, globals_dict["GRAPH_CACHE"])
            hydrate_started.set()
            if not release_hydration.wait(1.0):
                raise AssertionError("test did not release graph hydration")
            return 0

        results: list[object] = []

        def invoke(*, mark_finished: bool = False) -> None:
            results.append(load_city_state("bangalore"))
            if mark_finished:
                second_finished.set()

        city_lock = ObservableRLock()
        first = threading.Thread(target=invoke)
        second = threading.Thread(target=invoke, kwargs={"mark_finished": True})
        with patch.dict(
            globals_dict,
            {
                "GRAPH_CACHE": {},
                "CITY_LOCKS": defaultdict(lambda: city_lock),
                "load_or_fetch_graph": fake_load_graph,
                "build_city_state": fake_build,
                "hydrate_cached_coverage": fake_hydrate,
                "refresh_state_predictions": lambda city, candidate: None,
            },
        ):
            try:
                first.start()
                self.assertTrue(hydrate_started.wait(1.0))
                city_lock.observe_attempts = True
                second.start()
                self.assertTrue(city_lock.acquire_attempted.wait(1.0))
                self.assertFalse(second_finished.is_set())
                self.assertEqual(load_calls, 1)
            finally:
                release_hydration.set()
                first.join(1.0)
                if second.ident is not None:
                    second.join(1.0)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(load_calls, 1)
        self.assertEqual(results, [state, state])

    def test_interrupted_graph_publication_preserves_previous_file(self) -> None:
        publish_graph_cache = self.data["publish_graph_cache"]
        globals_dict = publish_graph_cache.__globals__

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "bangalore.graphml"
            target.write_bytes(b"complete-old-graph")

            def interrupted_save(graph, temporary_path) -> None:
                Path(temporary_path).write_bytes(b"partial-new-graph")
                raise OSError("simulated interrupted serialization")

            with patch.object(
                globals_dict["ox"], "save_graphml", side_effect=interrupted_save
            ):
                with self.assertRaisesRegex(OSError, "interrupted serialization"):
                    publish_graph_cache(synthetic_graph(), target)

            self.assertEqual(target.read_bytes(), b"complete-old-graph")
            self.assertEqual(list(target.parent.glob(".bangalore.graphml.*.tmp")), [])

    def test_local_graph_is_not_ready_when_atomic_publication_fails(self) -> None:
        load_or_fetch_graph = self.data["load_or_fetch_graph"]
        globals_dict = load_or_fetch_graph.__globals__

        def fail_publication(graph, path) -> None:
            raise OSError("shared graph publication failed")

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            globals_dict,
            {
                "GRAPH_CACHE_DIR": Path(tmpdir) / "graphs",
                "OSMNX_HTTP_CACHE_DIR": Path(tmpdir) / "http-cache",
                "load_local_graph_fallback": lambda city: synthetic_graph(),
                "publish_graph_cache": fail_publication,
            },
        ):
            with self.assertRaisesRegex(OSError, "publication failed"):
                load_or_fetch_graph("bangalore")

    def test_scores_endpoint_returns_one_locked_score_snapshot(self) -> None:
        get_scores = self.data["get_scores"]
        globals_dict = get_scores.__globals__
        segment_type = self.data["SegmentRecord"]
        segment = segment_type(
            segment_id="1-2-0",
            geometry=None,
            lat=12.975,
            lon=77.595,
            length=1000.0,
            highway="residential",
            surface="paved",
            properties={},
        )
        state = SimpleNamespace(
            city="bangalore",
            graph_revision="graph-test",
            score_revision="score-test",
            score_values=np.asarray([0.25], dtype=np.float32),
            scores_updated_at=10.0,
            score_source="opencellid",
            real_score_sources={"1-2-0": "opencellid"},
            segments=[segment],
        )
        read_started = threading.Event()
        release_read = threading.Event()
        update_finished = threading.Event()
        result: dict[str, object] = {}
        original_to_numpy = globals_dict["to_numpy_array"]

        def blocking_to_numpy(values):
            read_started.set()
            if not release_read.wait(1.0):
                raise AssertionError("test did not release score snapshot read")
            return original_to_numpy(values)

        def read_scores() -> None:
            result.update(get_scores("bangalore"))

        score_lock = ObservableRLock()
        score_locks = defaultdict(lambda: score_lock)

        def update_scores() -> None:
            with score_locks["bangalore"]:
                state.score_values = np.asarray([0.9], dtype=np.float32)
                state.scores_updated_at = 20.0
                state.score_source = "trai"
                state.real_score_sources = {"1-2-0": "trai"}
            update_finished.set()

        reader = threading.Thread(target=read_scores)
        updater = threading.Thread(target=update_scores)
        with patch.dict(
            globals_dict,
            {
                "CITY_LOCKS": score_locks,
                "require_city_state": lambda city: state,
                "to_numpy_array": blocking_to_numpy,
            },
        ):
            try:
                reader.start()
                self.assertTrue(read_started.wait(1.0))
                score_lock.observe_attempts = True
                updater.start()
                self.assertTrue(score_lock.acquire_attempted.wait(1.0))
                self.assertFalse(update_finished.is_set())
            finally:
                release_read.set()
                reader.join(1.0)
                if updater.ident is not None:
                    updater.join(1.0)

        self.assertFalse(reader.is_alive())
        self.assertFalse(updater.is_alive())
        self.assertTrue(update_finished.is_set())
        self.assertEqual(result["updated_at"], 10.0)
        self.assertEqual(result["source"], "opencellid")
        self.assertEqual(result["scores"], {"1-2-0": 0.25})
        self.assertEqual(result["edge_sources"], {"1-2-0": "opencellid"})

    def test_transient_preload_failure_recovers_within_retry_budget(self) -> None:
        schedule_preload = self.data["schedule_preload"]
        globals_dict = schedule_preload.__globals__
        third_attempt_started = threading.Event()
        release_success = threading.Event()
        attempts = 0

        def transient_then_success(city: str) -> None:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise TimeoutError(f"transient failure {attempts}")
            third_attempt_started.set()
            release_success.wait(1.0)

        with patch.dict(
            globals_dict,
            {
                "GRAPH_CACHE": {},
                "GRAPH_STATUS": {},
                "GRAPH_ERRORS": {},
                "PRELOAD_THREADS": {},
                "GRAPH_LOAD_RETRY_BACKOFF_SECONDS": (0.0, 0.0),
                "load_city_state": transient_then_success,
            },
        ):
            globals_dict["SCHEDULER_STOP"].clear()
            self.assertEqual(schedule_preload("bangalore"), "loading")
            self.assertTrue(third_attempt_started.wait(1.0))
            self.assertEqual(globals_dict["GRAPH_STATUS"]["bangalore"], "loading")
            thread = globals_dict["PRELOAD_THREADS"]["bangalore"]
            release_success.set()
            thread.join(1.0)
            self.assertEqual(globals_dict["GRAPH_STATUS"]["bangalore"], "ready")
            self.assertNotIn("bangalore", globals_dict["GRAPH_ERRORS"])

        self.assertEqual(attempts, 3)

    def test_transient_preload_failures_stop_at_retry_budget(self) -> None:
        schedule_preload = self.data["schedule_preload"]
        globals_dict = schedule_preload.__globals__
        attempts = 0
        exhausted = threading.Event()

        def always_transient(city: str) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 3:
                exhausted.set()
            raise OSError("temporary graph source failure")

        with patch.dict(
            globals_dict,
            {
                "GRAPH_CACHE": {},
                "GRAPH_STATUS": {},
                "GRAPH_ERRORS": {},
                "PRELOAD_THREADS": {},
                "GRAPH_LOAD_RETRY_BACKOFF_SECONDS": (0.0, 0.0),
                "load_city_state": always_transient,
            },
        ):
            globals_dict["SCHEDULER_STOP"].clear()
            self.assertEqual(schedule_preload("bangalore"), "loading")
            self.assertTrue(exhausted.wait(1.0))
            deadline = time.time() + 1.0
            while (
                globals_dict["GRAPH_STATUS"].get("bangalore") == "loading"
                and time.time() < deadline
            ):
                time.sleep(0.01)
            self.assertEqual(globals_dict["GRAPH_STATUS"]["bangalore"], "error")
            self.assertIn("temporary graph source failure", globals_dict["GRAPH_ERRORS"]["bangalore"])

        self.assertEqual(attempts, 3)


class TowerIngestionReservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_data_service()

    def make_worker(self, on_tile_ingested=None):
        return self.data["TowerIngestionWorker"](
            db_path=Path("unused-test-cache.db"),
            city="bangalore",
            key_manager=None,
            logger=lambda message: None,
            on_tile_ingested=on_tile_ingested,
            request_delay_seconds=0.0,
        )

    def test_active_tile_remains_reserved_through_fetch_and_callback(self) -> None:
        tile_id = "bangalore_001_001"
        fetch_started = threading.Event()
        release_fetch = threading.Event()
        callback_started = threading.Event()
        release_callback = threading.Event()
        callback_enqueue_results: list[int] = []
        fetch_calls = 0

        def on_tile_ingested(city: str, completed_tile: str, tower_count: int) -> None:
            callback_started.set()
            callback_enqueue_results.append(worker.enqueue_tiles([completed_tile]))
            if not release_callback.wait(1.0):
                raise AssertionError("test did not release adaptive callback")
            worker._stop.set()

        worker = self.make_worker(on_tile_ingested)

        def blocked_fetch(completed_tile: str):
            nonlocal fetch_calls
            fetch_calls += 1
            fetch_started.set()
            if not release_fetch.wait(1.0):
                raise AssertionError("test did not release tile fetch")
            return SimpleNamespace(
                tile_id=completed_tile,
                tower_count=4,
                status="ok",
            )

        self.assertEqual(worker.enqueue_tiles([tile_id]), 1)
        thread = threading.Thread(target=worker._run)
        with patch.object(worker, "_fetch_and_store_tile", side_effect=blocked_fetch):
            try:
                thread.start()
                self.assertTrue(fetch_started.wait(1.0))
                self.assertEqual(worker.enqueue_tiles([tile_id]), 0)
                release_fetch.set()
                self.assertTrue(callback_started.wait(1.0))
                self.assertEqual(worker.enqueue_tiles([tile_id]), 0)
            finally:
                release_fetch.set()
                release_callback.set()
                worker._stop.set()
                if thread.ident is not None:
                    thread.join(1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(fetch_calls, 1)
        self.assertEqual(callback_enqueue_results, [0])
        self.assertEqual(worker.enqueue_tiles([tile_id]), 1)

    def test_stopped_ingestion_releases_tile_for_future_retry(self) -> None:
        tile_id = "bangalore_002_002"
        fetch_started = threading.Event()
        release_fetch = threading.Event()
        worker = self.make_worker()

        def interrupted_fetch(completed_tile: str):
            fetch_started.set()
            if not release_fetch.wait(1.0):
                raise AssertionError("test did not release interrupted fetch")
            return SimpleNamespace(
                tile_id=completed_tile,
                tower_count=0,
                status="interrupted",
            )

        self.assertEqual(worker.enqueue_tiles([tile_id]), 1)
        thread = threading.Thread(target=worker._run)
        with patch.object(worker, "_fetch_and_store_tile", side_effect=interrupted_fetch):
            try:
                thread.start()
                self.assertTrue(fetch_started.wait(1.0))
                worker._stop.set()
                self.assertEqual(worker.enqueue_tiles([tile_id]), 0)
            finally:
                release_fetch.set()
                worker._stop.set()
                if thread.ident is not None:
                    thread.join(1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(worker.enqueue_tiles([tile_id]), 1)

    def test_failed_ingestion_releases_tile_for_future_retry(self) -> None:
        tile_id = "bangalore_004_004"
        worker = self.make_worker()

        def failed_fetch(completed_tile: str):
            worker._stop.set()
            return SimpleNamespace(
                tile_id=completed_tile,
                tower_count=0,
                status="error",
            )

        self.assertEqual(worker.enqueue_tiles([tile_id]), 1)
        thread = threading.Thread(target=worker._run)
        with patch.object(worker, "_fetch_and_store_tile", side_effect=failed_fetch):
            thread.start()
            thread.join(1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(worker.enqueue_tiles([tile_id]), 1)

    def test_background_stale_tile_is_claimed_against_enqueue_races(self) -> None:
        tile_id = "bangalore_003_003"
        worker = self.make_worker()
        globals_dict = worker._next_tile.__globals__

        with patch.dict(
            globals_dict,
            {"stale_tile_ids": lambda db_path, city, limit: [tile_id]},
        ):
            self.assertEqual(worker._next_tile(), tile_id)

        self.assertEqual(worker.enqueue_tiles([tile_id]), 0)
        worker._release_tile(tile_id)
        self.assertEqual(worker.enqueue_tiles([tile_id]), 1)


if __name__ == "__main__":
    unittest.main()
