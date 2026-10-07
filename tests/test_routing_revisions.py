"""Revision compatibility on synthetic topology and mocked HTTP publications."""
from __future__ import annotations

import asyncio
import json
import math
import runpy
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import networkx as nx
import pytest


ROOT = Path(__file__).resolve().parents[1]
ORIGIN, DESTINATION = (12.9, 77.5), (12.9, 77.502)
LOW = {"0-1-0": 0.2, "1-2-0": 0.2, "0-2-0": 0.9}
HIGH = {"0-1-0": 0.9, "1-2-0": 0.9, "0-2-0": 0.2}


@pytest.fixture(scope="module")
def module():
    return runpy.run_path(str(ROOT / "services/routing-engine/main.py"))["compute_route"].__globals__


@pytest.fixture
def routing(module, monkeypatch):
    for name, value in {
        "USE_CUPY": False, "GRAPH_CACHE": {}, "GRAPH_STATUS": {"bangalore": "ready"},
        "GRAPH_ERRORS": {}, "PRELOAD_TASKS": {}, "ROUTE_CACHE": OrderedDict(),
        "ROUTE_FLIGHTS": {}, "city_local_hour": lambda city: 12,
        "persist_route_cache": lambda: None, "push_corridor_scores_to_tiles": lambda *args: None,
        "find_nearest_node": lambda graph, lat, lon, index: 0 if lon == ORIGIN[1] else 2,
    }.items():
        monkeypatch.setitem(module, name, value)
    return module


def graph(revision="graph-A"):
    result = nx.MultiDiGraph(crs="EPSG:4326", graph_revision=revision)
    for node in range(3):
        result.add_node(node, x=77.5 + node * 0.001, y=12.9)
    for u, v, length in ((0, 1, 500), (1, 2, 500), (0, 2, 1200)):
        result.add_edge(u, v, length=length, speed_kph=36, highway="residential")
    return result


def make_state(routing, revision="graph-A", score_revision="scores-A", scores=None):
    base = routing["annotate_base_graph"](graph(revision))
    scores = LOW if scores is None else scores
    routing["apply_scores_to_base_graph"](base, scores, {key: "trai" for key in scores})
    state = routing["GraphState"](
        city="bangalore", base_graph=base, expires_at=math.inf, scores_updated_at=10,
        graph_revision=revision, score_revision=score_revision,
        snapshot_id=routing["score_snapshot_id"](base, score_revision),
        vehicle_graphs={vehicle: routing["precompute_vehicle_graph"](
            "bangalore", base, vehicle, 10, hour=12,
        ) for vehicle in routing["VEHICLE_PROFILES"]},
    )
    routing["GRAPH_CACHE"]["bangalore"] = state
    return state


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def corridor_payload(**overrides):
    return {
        "graph_revision": "graph-A", "base_score_revision": "scores-A",
        "score_revision": "corridor-A", "scores": {}, "edge_sources": {},
        "source": "ml_synthetic", **overrides,
    }


def calculate(routing, mode="balanced"):
    return routing["compute_route"]("bangalore", ORIGIN, DESTINATION, mode, "car")


@pytest.mark.parametrize("metadata", [
    {"graph_revision": "graph-B", "score_revision": "scores-A"},
    {"score_revision": "scores-A"}, {"graph_revision": "graph-A"},
])
def test_city_scores_reject_unknown_or_mismatched_revisions(routing, monkeypatch, metadata):
    monkeypatch.setattr(routing["request"], "urlopen", lambda *a, **k: Response({
        "scores": LOW, "source": "trai", **metadata,
    }))
    with pytest.raises(routing["RevisionCompatibilityError"]):
        routing["safe_fetch_city_scores"]("bangalore", "graph-A")


def test_matching_city_scores_keep_identity_and_provenance(routing, monkeypatch):
    monkeypatch.setattr(routing["request"], "urlopen", lambda *a, **k: Response({
        "scores": LOW, "updated_at": 10, "source": "trai",
        "graph_revision": "graph-A", "score_revision": "scores-A",
    }))
    scores, timestamp, sources, revision = routing["fetch_city_scores"]("bangalore", "graph-A")
    assert (scores, timestamp, revision) == (LOW, 10, "scores-A")
    assert set(sources.values()) == {"trai"}


def test_late_city_response_cannot_modify_replacement(routing, monkeypatch):
    old = make_state(routing)
    entered, release = threading.Event(), threading.Event()
    submitted = Mock()
    monkeypatch.setitem(routing, "THREAD_POOL", submitted)

    def late_response(*args):
        entered.set()
        assert release.wait(2)
        return HIGH, 20, {key: "opencellid" for key in HIGH}, "scores-late"

    monkeypatch.setitem(routing, "safe_fetch_city_scores", late_response)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(routing["refresh_scores_for_city"], "bangalore")
        assert entered.wait(2)
        new = make_state(routing, "graph-B", "scores-B", HIGH)
        release.set()
        future.result(timeout=2)
    submitted.submit.assert_not_called()
    assert new.score_revision == "scores-B"
    assert old.score_revision == "scores-A"
    assert not old.score_refreshing
    # Also exercise a job queued before replacement but executed afterwards.
    routing["rebuild_vehicle_graphs"](
        old, HIGH, 20, {}, "graph-A", "scores-late", "scores-A",
    )
    assert old.score_revision == "scores-A"
    assert routing["GRAPH_CACHE"]["bangalore"] is new


def test_score_update_invalidates_path_at_same_timestamp_and_topology(routing, monkeypatch):
    state = make_state(routing)
    monkeypatch.setattr(routing["request"], "urlopen", lambda *a, **k: Response(corridor_payload(
        base_score_revision=state.score_revision,
    )))
    old = calculate(routing)
    assert old["nodes"] == [0, 2]
    assert old["total_time_min"] == 2.0  # 1200m / 10m/s = 120s.
    routing["rebuild_vehicle_graphs"](
        state, HIGH, 10, {key: "opencellid" for key in HIGH},
        "graph-A", "scores-B", "scores-A",
    )
    new = calculate(routing)
    assert new["nodes"] == [0, 1, 2]
    assert new["total_time_min"] == 1.7  # 2 * 500m / 10m/s = 100s.
    assert new["graph_revision"] == old["graph_revision"] == "graph-A"
    assert (old["score_revision"], new["score_revision"]) == ("scores-A", "scores-B")
    assert new["provenance_source"] == "opencellid"
    assert len(routing["ROUTE_CACHE"]) == 2
    assert calculate(routing, "fastest")["nodes"] == [0, 1, 2]
    # A response admitted for scores-A cannot overwrite scores-B later.
    routing["rebuild_vehicle_graphs"](state, LOW, 999, {}, "graph-A", "scores-C", "scores-A")
    assert state.score_revision == "scores-B"


def test_inflight_route_keeps_old_graph_scores_and_provenance(routing, monkeypatch):
    make_state(routing)
    entered, release = threading.Event(), threading.Event()

    def delayed_corridor(req, **kwargs):
        payload = json.loads(req.data)
        assert (payload["graph_revision"], payload["score_revision"]) == ("graph-A", "scores-A")
        entered.set()
        assert release.wait(2)
        return Response(corridor_payload(scores={"0-2-0": 0.95}, source="opencellid"))

    monkeypatch.setattr(routing["request"], "urlopen", delayed_corridor)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(calculate, routing)
        assert entered.wait(2)
        replacement = make_state(routing, "graph-B", "scores-B", HIGH)
        release.set()
        result = future.result(timeout=2)
    assert (result["graph_revision"], result["score_revision"]) == ("graph-A", "scores-A")
    assert result["nodes"] == [0, 2]
    assert result["total_time_min"] == 2.0
    assert result["avg_connectivity"] == 0.95
    assert result["provenance_source"] == "opencellid"
    assert replacement.base_graph.edges[0, 2, 0]["connectivity_score"] == 0.2


@pytest.mark.parametrize("metadata", [
    {"graph_revision": "graph-B"}, {"base_score_revision": "scores-B"},
    {"score_revision": None}, {"graph_revision": None},
])
def test_bad_corridor_reply_is_not_real_coverage_or_cached(routing, monkeypatch, metadata):
    make_state(routing, scores={key: 0.5 for key in LOW})
    state = routing["GRAPH_CACHE"]["bangalore"]
    routing["apply_scores_to_base_graph"](state.base_graph, {}, {})
    monkeypatch.setattr(routing["request"], "urlopen", lambda *a, **k: Response(corridor_payload(
        scores={key: 1 for key in LOW}, source="trai", **metadata,
    )))
    result = calculate(routing)
    assert result["corridor_score_revision"] is None
    assert result["real_data_coverage_percent"] == 0
    assert result["provenance_source"] == "ml_synthetic"
    assert not routing["ROUTE_CACHE"]
    # The very next compatible response recovers; there is no cached failure.
    monkeypatch.setattr(routing["request"], "urlopen", lambda *a, **k: Response(corridor_payload(
        scores={key: 0.9 for key in LOW}, source="trai",
    )))
    recovered = calculate(routing)
    assert recovered["real_data_coverage_percent"] == 100
    assert recovered["corridor_score_revision"] == "corridor-A"


def test_corridor_score_updates_invalidate_cached_route_without_city_update(routing, monkeypatch):
    make_state(routing)
    response = corridor_payload(scores=LOW, source="trai")
    monkeypatch.setattr(routing["request"], "urlopen", lambda *a, **k: Response(response))
    assert calculate(routing)["nodes"] == [0, 2]
    response.update(score_revision="corridor-B", scores=HIGH)
    result = calculate(routing)
    assert result["nodes"] == [0, 1, 2]
    assert result["score_revision"] == "scores-A"
    assert result["corridor_score_revision"] == "corridor-B"
    assert len(routing["ROUTE_CACHE"]) == 2


def test_graph_revision_survives_graphml_reload_and_legacy_is_read_only(routing, monkeypatch, tmp_path):
    target = tmp_path / "bangalore.graphml"
    routing["ox"].save_graphml(graph(), target)
    monkeypatch.setitem(routing, "graph_cache_path", lambda city: target)
    first = routing["load_or_fetch_graph"]("bangalore")
    # A different file/inode with the same durable publication identity.
    replacement = tmp_path / "replacement.graphml"
    routing["ox"].save_graphml(graph(), replacement)
    replacement.replace(target)
    second = routing["load_or_fetch_graph"]("bangalore")
    assert first.graph["_routing_graph_revision"] != second.graph["_routing_graph_revision"]
    assert routing["score_snapshot_id"](first, "scores-A") == routing["score_snapshot_id"](second, "scores-A")
    legacy = graph()
    del legacy.graph["graph_revision"]
    routing["ox"].save_graphml(legacy, target)
    before = target.read_bytes()
    with pytest.raises(routing["RevisionCompatibilityError"], match="graph_revision"):
        routing["load_or_fetch_graph"]("bangalore")
    assert target.read_bytes() == before


def test_legacy_route_cache_is_discarded_on_load(routing, monkeypatch, tmp_path):
    target = tmp_path / "routes.json"
    target.write_text(json.dumps({"old": {"schema_version": 6, "response": {"source": "trai"}}}))
    monkeypatch.setitem(routing, "ROUTE_CACHE_PATH", target)
    routing["load_route_cache"]()
    assert not routing["ROUTE_CACHE"]


def test_unavailable_scores_clear_embedded_coverage_in_graphml(routing, monkeypatch):
    candidate = graph()
    for *_, edge in candidate.edges(data=True):
        edge.update(connectivity_score=0.99, provenance_source="trai")
    monkeypatch.setitem(routing, "load_or_fetch_graph", lambda city: candidate)

    def unavailable(*args, **kwargs):
        raise OSError("mock service unavailable")

    monkeypatch.setattr(routing["request"], "urlopen", unavailable)
    state = routing["build_graph_state"]("bangalore")
    assert state.score_revision == "unavailable"
    assert all(edge["connectivity_score"] == 0.5 for *_, edge in state.base_graph.edges(data=True))
    result = calculate(routing)
    assert result["provenance_source"] == "ml_synthetic"
    assert result["real_data_coverage_percent"] == 0
    assert result["corridor_score_revision"] is None


@pytest.mark.parametrize("recover", [True, False])
def test_initial_mismatch_retries_are_bounded_and_can_recover(routing, monkeypatch, recover):
    monkeypatch.setitem(routing, "load_or_fetch_graph", lambda city: graph())
    monkeypatch.setitem(routing, "request_data_service_preload", lambda city: None)
    attempts, waits = [], []

    def scores_response(*args, **kwargs):
        attempts.append(1)
        return Response({
            "graph_revision": "graph-A" if recover and len(attempts) == 2 else "graph-B",
            "score_revision": "scores-A", "scores": HIGH, "source": "trai",
        })

    async def record_sleep(seconds):
        assert routing["GRAPH_STATUS"]["bangalore"] == "loading"
        assert not routing["GRAPH_CACHE"]
        waits.append(seconds)

    monkeypatch.setattr(routing["request"], "urlopen", scores_response)
    monkeypatch.setattr(routing["asyncio"], "sleep", record_sleep)
    asyncio.run(routing["preload_city_graph"]("bangalore"))
    assert len(attempts) == (2 if recover else 3)
    assert waits == ([5] if recover else [5, 10])
    assert routing["GRAPH_STATUS"]["bangalore"] == ("ready" if recover else "error")
    if recover:
        assert routing["GRAPH_CACHE"]["bangalore"].score_revision == "scores-A"
    else:
        assert not routing["GRAPH_CACHE"]
        assert "different graph revision" in routing["GRAPH_ERRORS"]["bangalore"]
