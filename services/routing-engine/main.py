from __future__ import annotations

import ast
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import networkx as nx
import osmnx as ox
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from shapely.geometry import LineString,point,polygon

CITY_QUERIES = {
    "chennai": "Chennai, Tamil Nadu, India",
    "mumbai": "Mumbai, Maharashtra, India",
    "delhi": "National Capital Territory of Delhi, India",
}
RISK_ZONES = {
    "chennai": [
        {
            "type": "flood_prone",
            "penalty_multiplier": 5.0, # Makes this route look 5x slower
            # A rough bounding box in Chennai
            "polygon": Polygon([(80.20, 13.04), (80.25, 13.04), (80.25, 13.06), (80.20, 13.06)])
        }
    ]
}
BASE_DIR = Path(__file__).resolve().parent
GRAPH_DIR = Path("/app/data/graphs") if Path("/app/data/graphs").exists() else BASE_DIR.parent / "data-service" / "data" / "graphs"
GRAPH_DIR.mkdir(parents=True, exist_ok=True)

ox.settings.use_cache = True
ox.settings.log_console = False

app = FastAPI(title="Connectivity-Aware Routing Engine", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RouteRequest(BaseModel):
    city: str
    origin: list[float]
    destination: list[float]
    mode: Literal["fastest", "connected", "balanced", "safe"]


def normalize_city(city: str) -> str:
    city_slug = city.strip().lower()
    if city_slug not in CITY_QUERIES:
        supported = ", ".join(sorted(CITY_QUERIES))
        raise ValueError(f"Unsupported city '{city}'. Supported cities: {supported}.")
    return city_slug


def normalize_listish(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("[") and value.endswith("]"):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
    return value


def normalize_highway(highway: Any) -> str:
    highway = normalize_listish(highway)
    if isinstance(highway, list):
        highway = highway[0] if highway else None
    if isinstance(highway, str) and ";" in highway:
        highway = highway.split(";", 1)[0]
    return str(highway) if highway else "unknown"


def deterministic_fraction(seed: str) -> float:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def connectivity_score(city: str, u: int, v: int, key: int, highway: Any) -> float:
    road_type = normalize_highway(highway)
    fraction = deterministic_fraction(f"{normalize_city(city)}:{u}:{v}:{key}:{road_type}")
    if road_type in {"motorway", "trunk"}:
        low, high = 0.3, 0.6
    elif road_type in {"residential", "living_street"}:
        low, high = 0.2, 0.5
    else:
        low, high = 0.5, 0.9
    return round(low + (high - low) * fraction, 3)


def graph_path(city: str) -> Path:
    return GRAPH_DIR / f"{normalize_city(city)}.graphml"


def load_graph(city: str):
    city_slug = normalize_city(city)
    path = graph_path(city_slug)
    if path.exists():
        return ox.load_graphml(path)

    graph = ox.graph_from_place(
        CITY_QUERIES[city_slug],
        network_type="drive",
        simplify=True,
        retain_all=False,
        truncate_by_edge=True,
    )
    ox.save_graphml(graph, path)
    return graph


def add_edge_speeds_and_times(graph):
    if hasattr(ox, "add_edge_speeds") and hasattr(ox, "add_edge_travel_times"):
        graph = ox.add_edge_speeds(graph)
        return ox.add_edge_travel_times(graph)

    graph = ox.routing.add_edge_speeds(graph)
    return ox.routing.add_edge_travel_times(graph)


def nearest_node(graph, latitude: float, longitude: float):
    if hasattr(ox, "distance") and hasattr(ox.distance, "nearest_nodes"):
        return ox.distance.nearest_nodes(graph, X=longitude, Y=latitude)
    return ox.nearest_nodes(graph, X=longitude, Y=latitude)


@lru_cache(maxsize=3)
def get_prepared_graph(city: str):
    city_slug = normalize_city(city)
    graph = add_edge_speeds_and_times(load_graph(city_slug))
    travel_times = []

    for u, v, key, data in graph.edges(keys=True, data=True):
        travel_time = float(data.get("travel_time") or data.get("length") or 1.0)
        score = connectivity_score(city_slug, u, v, key, data.get("highway"))
        data["connectivity_score"] = score
        data["travel_time"] = travel_time
        travel_times.append(travel_time)

    min_time = min(travel_times) if travel_times else 0.0
    max_time = max(travel_times) if travel_times else 1.0
    spread = max(max_time - min_time, 1e-9)

    for u, _, _, data in graph.edges(keys=True, data=True):
        normalized_time = (float(data["travel_time"]) - min_time) / spread
        score = float(data["connectivity_score"])
        
        # 1. Base Weights
        data["weight_fastest"] = float(data["travel_time"])
        data["weight_connected"] = 1.0 - score
        data["weight_balanced"] = 0.5 * normalized_time + 0.5 * (1.0 - score)
        
        # 2. NEW: Risk-Aware Weight
        risk_multiplier = 1.0
        if city_slug in RISK_ZONES:
            # Check if the road's starting coordinate is inside a risk zone
            node_point = Point(graph.nodes[u]["x"], graph.nodes[u]["y"])
            for zone in RISK_ZONES[city_slug]:
                if zone["polygon"].contains(node_point):
                    risk_multiplier = zone["penalty_multiplier"]
                    break # Apply the penalty and stop checking
        
        # Multiply the fastest time by the risk multiplier
        data["weight_safe"] = float(data["travel_time"]) * risk_multiplier
    return graph


def validate_point(name: str, point: list[float]) -> tuple[float, float]:
    if len(point) != 2:
        raise HTTPException(status_code=422, detail=f"{name} must contain [lat, lon].")
    return float(point[0]), float(point[1])


def resolve_edge(graph, u: int, v: int, weight_attr: str):
    edges = graph.get_edge_data(u, v)
    if not edges:
        raise HTTPException(status_code=500, detail=f"Edge data missing between nodes {u} and {v}.")
    return min(
        edges.items(),
        key=lambda item: float(item[1].get(weight_attr, item[1].get("travel_time", 1.0))),
    )


def edge_geometry(graph, u: int, v: int, data: dict[str, Any]) -> LineString:
    geometry = data.get("geometry")
    if geometry is not None:
        return geometry
    start = graph.nodes[u]
    end = graph.nodes[v]
    return LineString([(start["x"], start["y"]), (end["x"], end["y"])])


def orient_coordinates(coords: list[tuple[float, float]], start_xy: tuple[float, float]) -> list[tuple[float, float]]:
    if not coords:
        return coords

    start_distance = abs(coords[0][0] - start_xy[0]) + abs(coords[0][1] - start_xy[1])
    end_distance = abs(coords[-1][0] - start_xy[0]) + abs(coords[-1][1] - start_xy[1])
    return coords if start_distance <= end_distance else list(reversed(coords))


def serialize_node(node: Any) -> Any:
    try:
        return int(node)
    except (TypeError, ValueError):
        return node


@app.post("/route")
def route(request: RouteRequest) -> dict[str, Any]:
    try:
        city_slug = normalize_city(request.city)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    origin_lat, origin_lon = validate_point("origin", request.origin)
    destination_lat, destination_lon = validate_point("destination", request.destination)

    graph = get_prepared_graph(city_slug)
    origin_node = nearest_node(graph, origin_lat, origin_lon)
    destination_node = nearest_node(graph, destination_lat, destination_lon)

    weight_attr = {
        "fastest": "weight_fastest",
        "connected": "weight_connected",
        "balanced": "weight_balanced",
        "safe": "weight_safe",
    }[request.mode]

    try:
        path_nodes = nx.shortest_path(graph, origin_node, destination_node, weight=weight_attr)
    except nx.NetworkXNoPath as exc:
        raise HTTPException(status_code=404, detail="No route found for the selected points.") from exc

    coordinates: list[tuple[float, float]] = []
    edge_scores: list[float] = []
    edge_times: list[float] = []

    for u, v in zip(path_nodes, path_nodes[1:]):
        _, data = resolve_edge(graph, u, v, weight_attr)
        geometry = edge_geometry(graph, u, v, data)
        coords = orient_coordinates(
            list(geometry.coords),
            (float(graph.nodes[u]["x"]), float(graph.nodes[u]["y"])),
        )

        if coordinates:
            coordinates.extend(coords[1:] if coordinates[-1] == coords[0] else coords)
        else:
            coordinates.extend(coords)

        edge_scores.append(float(data["connectivity_score"]))
        edge_times.append(float(data["travel_time"]))

    total_time_minutes = round(sum(edge_times) / 60.0, 1) if edge_times else 0.0
    avg_connectivity = round(sum(edge_scores) / len(edge_scores), 3) if edge_scores else 0.0

    return {
        "mode": request.mode,
        "nodes": [serialize_node(node) for node in path_nodes],
        "path_geojson": {
            "type": "LineString",
            "coordinates": coordinates,
        },
        "total_time_min": total_time_minutes,
        "avg_connectivity": avg_connectivity,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
