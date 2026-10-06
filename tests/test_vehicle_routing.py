"""Vehicle legality/seconds on synthetic topology; no external data or services."""
from __future__ import annotations

import math
import asyncio
import runpy
from collections import OrderedDict
from pathlib import Path

import networkx as nx
import httpx
import numpy as np
import pytest
from shapely.geometry import LineString


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def routing_module():
    module = runpy.run_path(str(ROOT / "services/routing-engine/main.py"))
    return module["compute_route"].__globals__


@pytest.fixture
def routing(routing_module, monkeypatch):
    replacements = {
        "USE_CUPY": False,
        "GRAPH_CACHE": {}, "GRAPH_STATUS": {"bangalore": "ready"},
        "ROUTE_CACHE": OrderedDict(), "ROUTE_FLIGHTS": {},
        "city_local_hour": lambda city: 12,
        "fetch_corridor_scores": lambda *args: ({}, "ml_synthetic", 0, 0, 0, {}, "corridor-test"),
        "push_corridor_scores_to_tiles": lambda *args: None,
        "persist_route_cache": lambda: None,
        "find_nearest_node": lambda graph, lat, lon, index: next(
            node for node, data in graph.nodes(data=True)
            if data["x"] == lon and data["y"] == lat
        ),
    }
    for key, value in replacements.items():
        monkeypatch.setitem(routing_module, key, value)
    return routing_module


def graph_with_nodes(count=4):
    graph = nx.MultiDiGraph(crs="EPSG:4326", graph_revision="graph-vehicle-test")
    for node in range(count):
        graph.add_node(node, x=77.50 + node * 0.001, y=12.90)
    return graph


def add_edge(graph, u, v, key=0, **attrs):
    graph.add_edge(u, v, key=key, **{
        "length": 1000.0, "speed_kph": 60.0, "highway": "residential",
        "connectivity_score": 0.8, "provenance_source": "trai", **attrs,
    })


def prepare(routing, graph):
    annotated = routing["annotate_base_graph"](graph.copy())
    for u, v, key, data in annotated.edges(keys=True, data=True):
        raw = graph.edges[u, v, key]
        data["connectivity_score"] = raw["connectivity_score"]
        data["provenance_source"] = raw["provenance_source"]
    prepared = {
        vehicle: routing["precompute_vehicle_graph"]("bangalore", annotated, vehicle, 1, hour=12)
        for vehicle in routing["VEHICLE_PROFILES"]
    }
    state = routing["GraphState"](
        city="bangalore", base_graph=annotated, expires_at=math.inf,
        scores_updated_at=1, vehicle_graphs=prepared,
        graph_revision=annotated.graph["graph_revision"], score_revision="scores-test",
    )
    routing["GRAPH_CACHE"]["bangalore"] = state
    return state


def route(routing, state, origin=0, destination=3, mode="fastest", vehicle="car"):
    nodes = state.base_graph.nodes
    return routing["compute_route"](
        "bangalore", (nodes[origin]["y"], nodes[origin]["x"]),
        (nodes[destination]["y"], nodes[destination]["x"]), mode, vehicle,
    )


def assert_no_route(routing, operation):
    with pytest.raises(routing["HTTPException"]) as error:
        operation()
    assert error.value.status_code == 422
    assert error.value.detail == routing["NO_ROUTE_DETAIL"]


@pytest.mark.parametrize("corridor_override", [False, True])
def test_unknown_tower_estimates_are_never_counted_as_real_coverage(routing, monkeypatch, corridor_override):
    graph = graph_with_nodes()
    add_edge(graph, 0, 3, provenance_source="unknown", connectivity_score=0.8)
    state = prepare(routing, graph)
    if corridor_override:
        monkeypatch.setitem(routing, "fetch_corridor_scores", lambda *args: (
            {"0-3-0": 0.9}, "unknown", 1, 0, 100, {"0-3-0": "unknown"}, "corridor-unknown",
        ))
    result = route(routing, state)
    assert result["provenance_source"] == "unknown"
    assert result["real_data_coverage_percent"] == 0.0
    assert result["total_time_min"] == 1.0
    assert result["signal_segments"][0]["provenance_source"] == "unknown"


def test_unknown_neighbor_does_not_turn_route_provenance_into_hybrid(routing):
    graph = graph_with_nodes()
    add_edge(graph, 0, 1, provenance_source="unknown")
    add_edge(graph, 1, 3, provenance_source="trai")
    result = route(routing, prepare(routing, graph))
    assert result["provenance_source"] == "unknown"
    assert result["real_data_coverage_percent"] == 50.0
    assert result["total_time_min"] == 2.0


def test_fastest_uses_vehicle_seconds_even_when_longer(routing):
    graph = graph_with_nodes()
    for u, v in ((0, 1), (1, 3)):
        add_edge(graph, u, v, length=400, speed_kph=10)
    for u, v in ((0, 2), (2, 3)):
        add_edge(graph, u, v, length=1000, speed_kph=60)
    state = prepare(routing, graph)
    car = route(routing, state)
    bike = route(routing, state, vehicle="bike")
    # Car: 2 * 1000m / (60/3.6 m/s) = 120s < 288s on the 800m path.
    assert car["nodes"] == [0, 2, 3]
    assert car["total_time_min"] == 2.0
    assert all(len(segment["coordinates"]) == 2 for segment in car["signal_segments"])
    assert car["signal_segments"][0]["coordinates"][-1] == car["signal_segments"][1]["coordinates"][0]
    # Bicycle: 2000m at 18km/h = 400s; the short path at 10km/h takes 288s.
    assert bike["nodes"] == [0, 1, 3]
    assert bike["total_time_min"] == 4.8


@pytest.mark.parametrize("vehicle,seconds", [("bike", 200), ("scooter", 80), ("car", 60), ("truck", 60)])
def test_fastest_excludes_city_and_corridor_connectivity_penalties(routing, monkeypatch, vehicle, seconds):
    graph = graph_with_nodes()
    add_edge(graph, 0, 3, connectivity_score=0.01)
    add_edge(graph, 0, 1, length=700)
    add_edge(graph, 1, 3, length=700)
    state = prepare(routing, graph)
    original = state.vehicle_graphs[vehicle].fastest_cost.copy()
    monkeypatch.setitem(routing, "fetch_corridor_scores", lambda *args: (
        {"0-3-0": 0.001, "0-1-0": 0.99, "1-3-0": 0.99}, "trai", 1, 100, 67,
        {edge: "trai" for edge in ("0-3-0", "0-1-0", "1-3-0")},
        "corridor-test",
    ))
    result = route(routing, state, vehicle=vehicle)
    assert result["nodes"] == [0, 3]
    assert result["total_time_min"] == round(seconds / 60, 1)
    assert result["avg_connectivity"] == 0.001
    np.testing.assert_array_equal(original, state.vehicle_graphs[vehicle].fastest_cost)
    assert route(routing, state, mode="connected", vehicle=vehicle)["nodes"] == [0, 1, 3]


@pytest.mark.parametrize("tags,vehicle", [
    ({"access": "no"}, "car"), ({"access": "private"}, "bike"),
    ({"vehicle": "destination"}, "scooter"), ({"motor_vehicle": "no"}, "scooter"),
    ({"motorcar": "no"}, "car"), ({"motorcycle": "no"}, "scooter"),
    ({"bicycle": "dismount"}, "bike"), ({"hgv": "no"}, "truck"),
    ({"access": ["yes", "no"]}, "truck"),
    ({"motor_vehicle:conditional": "no @ (20:00-06:00)"}, "car"),
    ({"maxweight": "3.5"}, "truck"),
    ({"maxweight:conditional": "3.5 @ (wet)"}, "truck"),
])
def test_access_restrictions_survive_all_modes_and_corridor_overrides(routing, monkeypatch, tags, vehicle):
    graph = graph_with_nodes()
    add_edge(graph, 0, 3, length=100, **tags)
    add_edge(graph, 0, 1, length=300)
    add_edge(graph, 1, 3, length=300)
    state = prepare(routing, graph)
    monkeypatch.setitem(routing, "fetch_corridor_scores", lambda *args: (
        {"0-3-0": 1.0}, "trai", 1, 100, 100, {"0-3-0": "trai"},
        "corridor-test",
    ))
    for mode in ("fastest", "balanced", "connected"):
        assert route(routing, state, mode=mode, vehicle=vehicle)["nodes"] == [0, 1, 3]


def test_specific_access_overrides_general_access(routing):
    graph = graph_with_nodes(2)
    add_edge(graph, 0, 1, access="no", bicycle="yes")
    state = prepare(routing, graph)
    assert route(routing, state, destination=1, vehicle="bike")["nodes"] == [0, 1]
    assert_no_route(routing, lambda: route(routing, state, destination=1, vehicle="car"))
    graph.edges[0, 1, 0].update(access="yes", motor_vehicle="no", motorcycle="yes")
    state = prepare(routing, graph)
    assert route(routing, state, destination=1, vehicle="scooter")["nodes"] == [0, 1]
    assert_no_route(routing, lambda: route(routing, state, destination=1, vehicle="truck"))


def test_one_way_branches_are_retained_and_never_reversed(routing):
    graph = graph_with_nodes(3)
    add_edge(graph, 0, 1, oneway=True, reversed=False)
    add_edge(graph, 1, 2, oneway=True, reversed=False)
    assert set(routing["ensure_connected_graph"](graph).nodes) == {0, 1, 2}
    state = prepare(routing, graph)
    assert route(routing, state, destination=2)["nodes"] == [0, 1, 2]
    for mode in ("fastest", "balanced", "connected"):
        assert_no_route(routing, lambda: route(routing, state, origin=2, destination=0, mode=mode))


def test_directional_access_and_vehicle_oneway_on_existing_edges(routing):
    graph = graph_with_nodes(2)
    add_edge(graph, 0, 1, oneway=False, reversed=False, **{"motor_vehicle:forward": "no", "oneway:bicycle": "yes"})
    add_edge(graph, 1, 0, oneway=False, reversed=True, **{"motor_vehicle:forward": "no", "oneway:bicycle": "yes"})
    state = prepare(routing, graph)
    assert route(routing, state, destination=1, vehicle="bike")["nodes"] == [0, 1]
    assert_no_route(routing, lambda: route(routing, state, origin=1, destination=0, vehicle="bike"))
    assert route(routing, state, origin=1, destination=0)["nodes"] == [1, 0]
    assert_no_route(routing, lambda: route(routing, state, destination=1))


def test_oneway_exemption_does_not_create_an_absent_reverse_edge(routing):
    graph = graph_with_nodes(2)
    add_edge(graph, 0, 1, oneway=True, reversed=False, **{"oneway:bicycle": "no"})
    state = prepare(routing, graph)
    assert_no_route(routing, lambda: route(routing, state, origin=1, destination=0, vehicle="bike"))


@pytest.mark.parametrize("vehicle,key,seconds,score,source", [
    ("car", "fast", 60, 0.4, "ml_synthetic"),
    ("bike", "slow", 200, 0.8, "trai"),
    ("scooter", "slow", 120, 0.8, "trai"),  # Equal cost: same first edge everywhere.
    ("truck", "slow", 120, 0.8, "trai"),
])
def test_parallel_edge_cost_eta_geometry_and_connectivity_agree(routing, vehicle, key, seconds, score, source):
    graph = graph_with_nodes(2)
    a = (graph.nodes[0]["x"], graph.nodes[0]["y"])
    b = (graph.nodes[1]["x"], graph.nodes[1]["y"])
    add_edge(graph, 0, 1, "prohibited", length=10, access="no")
    slow_geometry = LineString([a, (77.5004, 12.9005), b])
    fast_geometry = LineString([a, (77.5006, 12.8995), b])
    add_edge(graph, 0, 1, "slow", speed_kph=30, geometry=slow_geometry)
    add_edge(graph, 0, 1, "fast", length=1500, speed_kph=90, hgv="no", geometry=fast_geometry,
             connectivity_score=0.4, provenance_source="ml_synthetic")
    state = prepare(routing, graph)
    result = route(routing, state, destination=1, vehicle=vehicle)
    assert result["total_time_min"] == round(seconds / 60, 1)
    assert result["avg_connectivity"] == score
    assert result["real_data_coverage_percent"] == (100 if source == "trai" else 0)
    assert result["edge_sources"] == {f"0-1-{key}": source}
    assert result["path_geojson"]["coordinates"] == list((slow_geometry if key == "slow" else fast_geometry).coords)


@pytest.mark.parametrize("raw,expected_kph", [
    (None, 20), (0, 20), (-10, 20), (math.nan, 20), (math.inf, 20), (True, 20),
    ("invalid", 20), ("NaN", 20), ("0", 20), ("-5", 20), ("walk", 20),
    ("30 mph", 48.28032), ("30 km/h", 30), ("30 kph", 30),
    ("10 knots", 18.52), ("1 km/h", 1), ("80;20", 20), (["80", "20"], 20),
])
def test_speed_units_and_fallbacks_have_independent_expected_seconds(routing, raw, expected_kph):
    data = {"length": 1000, "highway": "residential", "speed_kph": raw, "travel_time": 1}
    assert routing["edge_travel_time_seconds"](data, "car") == pytest.approx(3600 / expected_kph)
    graph = graph_with_nodes(2)
    add_edge(graph, 0, 1, speed_kph=raw, travel_time=1)
    state = prepare(routing, graph)
    assert route(routing, state, destination=1)["total_time_min"] == round(60 / expected_kph, 1)


@pytest.mark.parametrize("point", [[91, 77], [-91, 77], [12, 181], [12, -181], [math.nan, 77], [12, math.inf], [], [12], [12, 77, 0]])
def test_invalid_coordinates_rejected_before_snapping(routing, point):
    with pytest.raises(routing["HTTPException"]) as caught:
        routing["validate_point"]("origin", point)
    assert caught.value.status_code == 422


def test_coordinate_boundaries_are_valid(routing):
    assert routing["validate_point"]("origin", [-90, -180]) == (-90, -180)
    assert routing["validate_point"]("destination", [90, 180]) == (90, 180)


def test_speed_limits_and_directional_limits_bound_vehicle_speeds(routing):
    data = {"length": 1000, "speed_kph": 90, "maxspeed": "60", "maxspeed:hgv": "30"}
    assert routing["edge_travel_time_seconds"](data, "car") == 60
    assert routing["edge_travel_time_seconds"](data, "truck") == 120
    data.update({"oneway": False, "reversed": True, "maxspeed:backward": "20"})
    assert routing["edge_travel_time_seconds"](data, "car") == 180
    # Missing speed uses the posted limit before the road-class fallback.
    assert routing["edge_travel_time_seconds"]({"length": 1000, "maxspeed": "30"}) == 120


@pytest.mark.parametrize("reason", ["disconnected", "restricted", "invalid_length", "node_access", "ambiguous_direction"])
def test_unreachable_or_prohibited_destinations_never_use_unweighted_fallback(routing, reason):
    graph = graph_with_nodes(2)
    if reason != "disconnected":
        add_edge(graph, 0, 1)
    if reason == "restricted":
        graph.edges[0, 1, 0]["access"] = "no"
    elif reason == "invalid_length":
        graph.edges[0, 1, 0]["length"] = math.nan
    elif reason == "node_access":
        graph.nodes[1]["motor_vehicle"] = "no"
    elif reason == "ambiguous_direction":
        graph.edges[0, 1, 0].update({"oneway": True, "reversed": False, "maxspeed:forward": "30"})
    state = prepare(routing, graph)
    for mode in ("fastest", "balanced", "connected"):
        assert_no_route(routing, lambda: route(routing, state, destination=1, mode=mode))


def test_invalid_edge_indexes_cannot_bypass_vehicle_weights(routing):
    graph = graph_with_nodes(2)
    for key, index in enumerate((-1, 99, None, True)):
        add_edge(graph, 0, 1, key, edge_index=index)
    weights = np.asarray([math.inf, 5.0])
    assert_no_route(routing, lambda: routing["compute_path_with_fallbacks"](graph, 0, 1, weights))
    assert_no_route(routing, lambda: routing["resolve_edge"](graph, 0, 1, weights))


def test_synthetic_graphml_with_invalid_speed_loads_for_documented_fallback(routing, tmp_path, monkeypatch):
    graph = graph_with_nodes(2)
    add_edge(graph, 0, 1, speed_kph="invalid", travel_time="invalid", oneway=True, reversed=False)
    path = tmp_path / "synthetic.graphml"
    routing["ox"].save_graphml(graph, path)
    monkeypatch.setitem(routing, "graph_cache_path", lambda city: path)
    loaded = routing["load_or_fetch_graph"]("bangalore")
    assert loaded.number_of_edges() == 1
    assert routing["edge_travel_time_seconds"](loaded.edges[0, 1, 0]) == 180


def test_no_route_http_response_is_terminal_422(routing):
    state = prepare(routing, graph_with_nodes(2))

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=routing["app"]), base_url="http://synthetic",
            trust_env=False,
        ) as client:
            return await client.post("/route", json={
                "city": "bangalore", "origin": [12.90, state.base_graph.nodes[0]["x"]],
                "destination": [12.90, state.base_graph.nodes[1]["x"]],
                "mode": "fastest", "vehicle": "car",
            })

    response = asyncio.run(exercise())
    assert response.status_code == 422
    assert response.json() == {"detail": routing["NO_ROUTE_DETAIL"]}
    assert "retry-after" not in response.headers


def test_connected_low_signal_is_a_penalty_not_an_access_restriction(routing):
    graph = graph_with_nodes(2)
    add_edge(graph, 0, 1, connectivity_score=0.0)
    state = prepare(routing, graph)
    result = route(routing, state, destination=1, mode="connected")
    assert result["nodes"] == [0, 1]
    assert result["total_time_min"] == 1.0
    assert result["avg_connectivity"] == 0.0


def test_aggregated_road_classes_do_not_hide_restrictions_or_slow_fallback(routing):
    graph = graph_with_nodes(2)
    add_edge(graph, 0, 1, highway=["motorway", "residential"], speed_kph=None)
    state = prepare(routing, graph)
    assert route(routing, state, destination=1)["total_time_min"] == 3.0  # 1000m at 20km/h.
    assert_no_route(routing, lambda: route(routing, state, destination=1, vehicle="bike"))


def test_future_osm_import_keeps_vehicle_tags_and_restriction_boundaries(routing, tmp_path, monkeypatch):
    ox = routing["ox"]
    monkeypatch.setattr(ox.settings, "useful_tags_way", ["highway", "oneway"])
    monkeypatch.setattr(ox.settings, "useful_tags_node", ["highway"])
    monkeypatch.syspath_prepend(str(ROOT / "services/data-service"))
    data = runpy.run_path(str(ROOT / "services/data-service/main.py"))
    source = tmp_path / "synthetic.osm"
    source.write_text('''<osm version="0.6">
      <node id="1" lat="12.9" lon="77.50" />
      <node id="2" lat="12.9" lon="77.51" />
      <node id="3" lat="12.9" lon="77.52" />
      <way id="10"><nd ref="1"/><nd ref="2"/>
        <tag k="highway" v="residential"/><tag k="motorcycle" v="no"/>
        <tag k="bicycle" v="yes"/><tag k="maxspeed:hgv" v="20"/>
      </way>
      <way id="11"><nd ref="2"/><nd ref="3"/>
        <tag k="highway" v="residential"/><tag k="motorcycle" v="yes"/>
        <tag k="bicycle" v="no"/><tag k="maxspeed:hgv" v="30"/>
      </way>
    </osm>''', encoding="utf-8")
    imported = ox.graph_from_xml(source, simplify=False, retain_all=True)
    assert imported.edges[1, 2, 0]["motorcycle"] == "no"
    assert imported.edges[2, 3, 0]["bicycle"] == "no"
    assert imported.edges[1, 2, 0]["maxspeed:hgv"] == "20"
    # Exercise the service's simplification but isolate the later geometric
    # intersection consolidation, whose real-map quality is outside this test.
    monkeypatch.setattr(ox, "project_graph", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("synthetic: skip consolidation")))
    simplified = data["simplify_city_graph"]("bangalore", imported)
    assert 2 in simplified.nodes
    assert simplified.edges[1, 2, 0]["motorcycle"] == "no"
