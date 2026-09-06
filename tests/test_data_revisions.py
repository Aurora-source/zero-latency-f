from __future__ import annotations

import asyncio
import json
import pickle
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
import httpx
from fastapi import HTTPException


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


def graph(revision: str | None = "graph-a") -> nx.MultiDiGraph:
    value = nx.MultiDiGraph(crs="EPSG:4326")
    if revision is not None:
        value.graph["graph_revision"] = revision
    value.add_node(1, x=77.59, y=12.97)
    value.add_node(2, x=77.60, y=12.98)
    value.add_edge(1, 2, key=0, length=100.0, highway="residential")
    return value


class DataRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = load_data_service()

    def state(self, graph_revision: str = "graph-a", score_revision: str = "score-a"):
        segment = self.data["SegmentRecord"](
            segment_id="1-2-0",
            geometry=None,
            lat=12.975,
            lon=77.595,
            length=100.0,
            highway="residential",
            surface="unknown",
            properties={},
        )
        return self.data["CityState"](
            city="bangalore",
            graph=graph(graph_revision),
            expires_at=time.time() + 60,
            segments=[segment],
            segment_lookup={segment.segment_id: 0},
            graph_revision=graph_revision,
            score_revision=score_revision,
            score_values=np.asarray([0.5], dtype=np.float32),
            score_metadata={
                "city": "bangalore",
                "source": "ml_synthetic",
                "graph_revision": graph_revision,
                "score_revision": score_revision,
            },
            published=True,
        )

    def test_graph_revision_survives_atomic_graphml_reload(self) -> None:
        publish = self.data["publish_graph_cache"]
        candidate = graph("previous-publication")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bangalore.graphml"
            publish(candidate, path)
            published_revision = candidate.graph["graph_revision"]
            loaded = self.data["ox"].load_graphml(path)
            self.assertEqual(self.data["graph_revision"](loaded), published_revision)
            loaded.edges[1, 2, 0]["length"] = 200.0
            publish(loaded, path)
            replaced = self.data["ox"].load_graphml(path)
        self.assertNotEqual(published_revision, "previous-publication")
        self.assertNotEqual(self.data["graph_revision"](replaced), published_revision)

    def test_legacy_graph_cache_is_assigned_and_republished(self) -> None:
        load_graph = self.data["load_or_fetch_graph"]
        globals_dict = load_graph.__globals__
        legacy = graph(None)
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cache_path = cache_dir / "bangalore.graphml"
            self.data["ox"].save_graphml(legacy, cache_path)
            with patch.dict(globals_dict, {
                "GRAPH_CACHE_DIR": cache_dir, "OSMNX_HTTP_CACHE_DIR": cache_dir / "http-cache",
            }):
                loaded = load_graph("bangalore")
                reloaded = load_graph("bangalore")

        self.assertTrue(self.data["graph_revision"](loaded))
        self.assertEqual(self.data["graph_revision"](loaded), self.data["graph_revision"](reloaded))
        self.assertEqual(set(loaded.edges(keys=True)), set(legacy.edges(keys=True)))

    def test_city_build_cannot_assign_an_unpublished_graph_identity(self) -> None:
        with self.assertRaisesRegex(self.data["GraphLoadTransientError"], "published with a revision"):
            self.data["build_city_state"]("bangalore", graph(None), time.time() + 60)

    def test_real_score_cache_requires_matching_single_file_envelope(self) -> None:
        load_scores = self.data["load_real_scores"]
        globals_dict = load_scores.__globals__
        state = self.state()
        with tempfile.TemporaryDirectory() as tmpdir:
            score_dir = Path(tmpdir)
            path = score_dir / "bangalore_real_scores.pkl"
            with patch.dict(globals_dict, {"REAL_SCORE_DIR": score_dir}):
                for payload in (
                    {"1-2-0": 0.8},
                    {
                        "graph_revision": "graph-old",
                        "score_revision": "stored-score",
                        "scores": {"1-2-0": 0.8},
                        "metadata": {"source": "trai"},
                    },
                ):
                    with path.open("wb") as handle:
                        pickle.dump(payload, handle)
                    self.assertIsNone(load_scores("bangalore", state))

                with path.open("wb") as handle:
                    pickle.dump(
                        {
                            "graph_revision": "graph-a",
                            "score_revision": "stored-score",
                            "scores": {"1-2-0": 0.8},
                            "metadata": {"source": "trai"},
                        },
                        handle,
                    )
                loaded = load_scores("bangalore", state)

        self.assertIsNotNone(loaded)
        values, metadata = loaded
        self.assertAlmostEqual(float(values[0]), 0.8)
        self.assertEqual(metadata["score_revision"], "stored-score")

    def test_score_change_rotates_only_score_revision(self) -> None:
        apply_scores = self.data["apply_city_scores"]
        state = self.state()
        globals_dict = apply_scores.__globals__
        with patch.dict(globals_dict, {"GRAPH_CACHE": {"bangalore": state}}):
            changed = apply_scores(
                "bangalore",
                state,
                {"1-2-0": 0.8},
                {"source": "ml_synthetic"},
                expected_graph_revision="graph-a",
                expected_score_revision="score-a",
            )
        self.assertTrue(changed)
        self.assertEqual(state.graph_revision, "graph-a")
        self.assertNotEqual(state.score_revision, "score-a")
        current_revision = state.score_revision
        with patch.dict(globals_dict, {"GRAPH_CACHE": {"bangalore": state}}):
            accepted = apply_scores(
                "bangalore",
                state,
                {"1-2-0": 0.8},
                {"source": "ml_synthetic"},
                expected_graph_revision="graph-a",
                expected_score_revision=current_revision,
            )
        self.assertTrue(accepted)
        self.assertEqual(state.score_revision, current_revision)

    def test_provenance_only_update_rotates_score_revision(self) -> None:
        apply_scores = self.data["apply_city_scores"]
        state = self.state()
        state.real_score_sources = {"1-2-0": "trai"}
        globals_dict = apply_scores.__globals__
        with patch.dict(globals_dict, {"GRAPH_CACHE": {"bangalore": state}}):
            apply_scores("bangalore", state, {"1-2-0": 0.5}, edge_sources={"1-2-0": "opencellid"})
        self.assertEqual(state.graph_revision, "graph-a")
        self.assertNotEqual(state.score_revision, "score-a")
        self.assertEqual(state.real_score_sources, {"1-2-0": "opencellid"})
        self.assertEqual(float(state.score_values[0]), 0.5)

    def test_private_replacement_can_be_hydrated_before_publication(self) -> None:
        apply_scores = self.data["apply_city_scores"]
        old = self.state()
        new = self.state("graph-b", "score-b")
        new.published = False
        with patch.dict(apply_scores.__globals__, {"GRAPH_CACHE": {"bangalore": old}}):
            self.assertTrue(apply_scores("bangalore", new, {"1-2-0": 0.8}))
        self.assertAlmostEqual(float(new.score_values[0]), 0.8)
        self.assertAlmostEqual(float(old.score_values[0]), 0.5)

    def test_prediction_revision_is_echoed_and_checked_before_application(self) -> None:
        post = self.data["post_prediction_scores"]
        state = self.state()
        replies = [None, "graph-old", "graph-a"]
        requests = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"graph_revision": replies.pop(0), "scores": {"1-2-0": 0.9}}).encode()

        def respond(req, **kwargs):
            requests.append(json.loads(req.data))
            return Response()

        with patch.object(post.__globals__["request"], "urlopen", side_effect=respond):
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "absent or incompatible"):
                    post("bangalore", state)
            scores, metadata = post("bangalore", state)
        self.assertEqual(scores, {"1-2-0": 0.9})
        self.assertEqual(metadata["graph_revision"], "graph-a")
        self.assertTrue(all(request["graph_revision"] == "graph-a" for request in requests))

    def test_feedback_checks_graph_and_base_score_before_writing(self) -> None:
        feedback = self.data["post_corridor_feedback"]
        globals_dict = feedback.__globals__
        state = self.state()
        cache = {"bangalore": state}
        request_type = self.data["CorridorTileUpdateRequest"]
        payload = request_type(
            graph_revision="graph-a", base_score_revision="score-a", score_revision="corridor-a",
            scores={"1-2-0": 0.9}, edge_sources={"1-2-0": "trai"},
        )
        with patch.dict(globals_dict, {
            "GRAPH_CACHE": cache, "cached_coverage_metadata": lambda city: None,
        }):
            for bad in (
                payload.model_copy(update={"graph_revision": "graph-old"}),
                payload.model_copy(update={"base_score_revision": "score-old"}),
                payload.model_copy(update={"score_revision": ""}),
            ):
                with self.assertRaises(HTTPException) as raised:
                    feedback("bangalore", bad)
                self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(float(state.score_values[0]), 0.5)
            result = feedback("bangalore", payload)
            self.assertEqual(result["updated_edges"], 1)
            self.assertNotEqual(state.score_revision, "score-a")
            with self.assertRaises(HTTPException) as raised:
                feedback("bangalore", payload)
            self.assertEqual(raised.exception.status_code, 409)
            cache["bangalore"] = self.state("graph-b", "score-b")
            with self.assertRaises(HTTPException) as raised:
                feedback("bangalore", payload)
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(float(cache["bangalore"].score_values[0]), 0.5)

    def test_corridor_http_rejects_legacy_mismatch_and_unknown_city(self) -> None:
        post = self.data["post_corridor_scores"]
        payload = {
            "origin": [12.97, 77.59], "destination": [12.98, 77.60],
            "edge_coords": {"1-2-0": [12.975, 77.595]},
        }

        async def check():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.data["app"]),
                base_url="http://test", trust_env=False,
            ) as client:
                legacy = await client.post("/corridor-scores", json=payload)
                self.assertEqual(legacy.status_code, 422)
                payload.update(city="bangalore", graph_revision="graph-old", score_revision="score-a")
                mismatch = await client.post("/corridor-scores", json=payload)
                self.assertEqual(mismatch.status_code, 409)
                payload.update(city="unsupported-city")
                unknown_city = await client.post("/corridor-scores", json=payload)
                self.assertEqual(unknown_city.status_code, 404)
                unknown_feedback = await client.post("/corridor-feedback/unsupported-city", json={
                    "graph_revision": "graph-a", "base_score_revision": "score-a",
                    "score_revision": "corridor-a", "scores": {},
                })
                self.assertEqual(unknown_feedback.status_code, 404)

        with patch.dict(post.__globals__, {"GRAPH_CACHE": {"bangalore": self.state()}}):
            asyncio.run(check())

    def test_stale_state_and_stale_score_generation_cannot_publish(self) -> None:
        apply_scores = self.data["apply_city_scores"]
        old_state = self.state()
        current_state = self.state("graph-b", "score-b")
        globals_dict = apply_scores.__globals__
        with patch.dict(globals_dict, {"GRAPH_CACHE": {"bangalore": current_state}}):
            self.assertFalse(apply_scores("bangalore", old_state, {"1-2-0": 0.9}))
        self.assertAlmostEqual(float(old_state.score_values[0]), 0.5)

        with patch.dict(globals_dict, {"GRAPH_CACHE": {"bangalore": current_state}}):
            self.assertFalse(
                apply_scores(
                    "bangalore",
                    current_state,
                    {"1-2-0": 0.9},
                    expected_graph_revision="graph-b",
                    expected_score_revision="score-old",
                )
            )
        self.assertAlmostEqual(float(current_state.score_values[0]), 0.5)

    def test_corridor_revisions_are_admitted_echoed_and_deterministic(self) -> None:
        calculate = self.data["_calculate_corridor_scores"]
        globals_dict = calculate.__globals__
        state = self.state()
        payload = self.data["CorridorScoresRequest"](
            city="bangalore",
            graph_revision="graph-a",
            score_revision="score-a",
            origin=[12.97, 77.59],
            destination=[12.98, 77.60],
            edge_coords={"1-2-0": [12.975, 77.595]},
        )

        async def fetch(*args, **kwargs):
            return [], {}, {"source": "unknown"}

        with patch.dict(
            globals_dict,
            {
                "GRAPH_CACHE": {"bangalore": state},
                "CITY_LOCKS": defaultdict(threading.RLock),
                "fetch_towers_cached": fetch,
            },
        ):
            first = asyncio.run(calculate(payload))
            second = asyncio.run(calculate(payload))

        self.assertEqual(first, second)
        self.assertEqual(first["graph_revision"], "graph-a")
        self.assertEqual(first["base_score_revision"], "score-a")
        self.assertEqual(len(first["score_revision"]), 64)

    def test_corridor_mismatch_is_explicit_and_bounded_to_one_attempt(self) -> None:
        calculate = self.data["_calculate_corridor_scores"]
        globals_dict = calculate.__globals__
        state = self.state()
        payload = self.data["CorridorScoresRequest"](
            city="bangalore",
            graph_revision="graph-old",
            score_revision="score-old",
            origin=[12.97, 77.59],
            destination=[12.98, 77.60],
            edge_coords={"1-2-0": [12.975, 77.595]},
        )
        fetch_calls = 0

        async def fetch(*args, **kwargs):
            nonlocal fetch_calls
            fetch_calls += 1
            return [], {}, {}

        with patch.dict(
            globals_dict,
            {"GRAPH_CACHE": {"bangalore": state}, "fetch_towers_cached": fetch},
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(calculate(payload))
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(fetch_calls, 0)

    def test_admitted_corridor_request_keeps_old_revision_after_replacement(self) -> None:
        calculate = self.data["_calculate_corridor_scores"]
        globals_dict = calculate.__globals__
        old_state = self.state()
        cache = {"bangalore": old_state}
        payload = self.data["CorridorScoresRequest"](
            city="bangalore",
            graph_revision="graph-a",
            score_revision="score-a",
            origin=[12.97, 77.59],
            destination=[12.98, 77.60],
            edge_coords={"1-2-0": [12.975, 77.595]},
        )

        async def fetch(*args, **kwargs):
            cache["bangalore"] = self.state("graph-b", "score-b")
            return [], {}, {"source": "unknown"}

        with patch.dict(
            globals_dict,
            {
                "GRAPH_CACHE": cache,
                "CITY_LOCKS": defaultdict(threading.RLock),
                "fetch_towers_cached": fetch,
            },
        ):
            result = asyncio.run(calculate(payload))

        self.assertEqual(result["graph_revision"], "graph-a")
        self.assertEqual(result["base_score_revision"], "score-a")
        self.assertEqual(cache["bangalore"].graph_revision, "graph-b")


if __name__ == "__main__":
    unittest.main()
