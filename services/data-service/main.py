from __future__ import annotations

import ast
import hashlib
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from shapely.geometry import LineString, mapping

from scripts.predownload_graphs import load_graph, normalize_city

app = FastAPI(title="Connectivity-Aware Data Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def normalize_highway(highway: Any) -> str:
    if isinstance(highway, str) and highway.startswith("[") and highway.endswith("]"):
        try:
            highway = ast.literal_eval(highway)
        except (SyntaxError, ValueError):
            pass
    if isinstance(highway, list):
        highway = highway[0] if highway else None
    if isinstance(highway, str) and ";" in highway:
        highway = highway.split(";", 1)[0]
    return str(highway) if highway else "unknown"


def normalize_name(name: Any) -> str:
    if isinstance(name, str) and name.startswith("[") and name.endswith("]"):
        try:
            name = ast.literal_eval(name)
        except (SyntaxError, ValueError):
            pass
    if isinstance(name, list):
        return ", ".join(str(part) for part in name if part)
    return str(name) if name else ""


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


@lru_cache(maxsize=3)
def get_city_graph(city: str):
    return load_graph(city)


def edge_geometry(graph, u: int, v: int, data: dict[str, Any]) -> LineString:
    geometry = data.get("geometry")
    if geometry is not None:
        return geometry
    start = graph.nodes[u]
    end = graph.nodes[v]
    return LineString([(start["x"], start["y"]), (end["x"], end["y"])])


@app.get("/segments/{city}")
def get_segments(city: str) -> dict[str, Any]:
    try:
        city_slug = normalize_city(city)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    graph = get_city_graph(city_slug)
    features: list[dict[str, Any]] = []

    for u, v, key, data in graph.edges(keys=True, data=True):
        road_type = normalize_highway(data.get("highway"))
        name = normalize_name(data.get("name"))
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(edge_geometry(graph, u, v, data)),
                "properties": {
                    "segment_id": f"{u}-{v}-{key}",
                    "connectivity_score": connectivity_score(city_slug, u, v, key, data.get("highway")),
                    "road_type": road_type,
                    "name": name,
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
