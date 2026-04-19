from __future__ import annotations

import csv
import json
import math
import os
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import osmnx as ox
from shapely import wkt
from shapely.geometry import LineString, MultiLineString, Point, shape
from shapely.geometry.base import BaseGeometry

try:
    import cupy as cp

    USE_CUPY = True
except ImportError:
    cp = None
    USE_CUPY = False

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
TRAI_DIR = DATA_DIR / "trai"
TOWERS_DIR = DATA_DIR / "towers"
SCORES_DIR = DATA_DIR / "scores"
GRAPHS_DIR = DATA_DIR / "graphs"
OPENCELLID_TOKEN = os.environ.get(
    "OPENCELLID_TOKEN",
    "pk.37dddd741049308fd26c175be7a5aea0",
)

ROAD_FALLBACK_SCORE = 0.05
TRAI_TECHNOLOGY_WEIGHTS = {
    "5g": 1.0,
    "nr": 1.0,
    "4g": 0.85,
    "lte": 0.85,
    "3g": 0.5,
    "umts": 0.5,
    "2g": 0.2,
    "gsm": 0.2,
}
OPERATOR_RELIABILITY = {
    "jio": 1.0,
    "airtel": 0.95,
    "vi": 0.75,
    "vodafone idea": 0.75,
    "bsnl": 0.5,
}
RADIO_WEIGHTS = {
    "nr": 1.2,
    "5g": 1.2,
    "lte": 1.0,
    "4g": 1.0,
    "umts": 0.6,
    "3g": 0.6,
    "gsm": 0.3,
    "2g": 0.3,
}


@dataclass(frozen=True)
class SegmentPoint:
    segment_id: str
    lat: float
    lon: float


@dataclass(frozen=True)
class TowerData:
    coords: np.ndarray
    ranges: np.ndarray
    weights: np.ndarray
    count: int
    last_updated: str


def ensure_dirs() -> None:
    SCORES_DIR.mkdir(parents=True, exist_ok=True)


def normalize_geometry(geometry: Any) -> BaseGeometry | None:
    if geometry is None:
        return None
    if isinstance(geometry, str):
        return wkt.loads(geometry)
    return geometry


def extract_linear_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type in {"LineString", "MultiLineString"}:
        return geometry
    if geometry.geom_type != "GeometryCollection":
        return None

    lines: list[BaseGeometry] = []
    for part in geometry.geoms:
        if part.is_empty:
            continue
        if part.geom_type in {"LineString", "MultiLineString"}:
            lines.append(part)

    if not lines:
        return None
    if len(lines) == 1:
        return lines[0]
    return MultiLineString(lines)


def edge_geometry(graph, u: int, v: int, data: dict[str, Any]) -> BaseGeometry | None:
    geometry = normalize_geometry(data.get("geometry"))
    if geometry is not None:
        return geometry
    start = graph.nodes[u]
    end = graph.nodes[v]
    return LineString([(start["x"], start["y"]), (end["x"], end["y"])])


def load_graph(city: str):
    pickled = GRAPHS_DIR / f"{city}_simplified.pkl"
    if pickled.exists():
        with pickled.open("rb") as handle:
            return pickle.load(handle)

    graphml = GRAPHS_DIR / f"{city}.graphml"
    if graphml.exists():
        return ox.load_graphml(graphml)

    raise FileNotFoundError(f"No graph found for {city}")


def build_segment_points(graph) -> list[SegmentPoint]:
    segments: list[SegmentPoint] = []
    for u, v, key, data in graph.edges(keys=True, data=True):
        geometry = extract_linear_geometry(edge_geometry(graph, u, v, data))
        if geometry is None or geometry.is_empty:
            continue
        midpoint = geometry.centroid
        segments.append(
            SegmentPoint(
                segment_id=f"{u}-{v}-{key}",
                lat=float(midpoint.y),
                lon=float(midpoint.x),
            )
        )
    return segments


def normalize_operator(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "vodafone" in text or text == "vi":
        return "vi"
    if "airtel" in text:
        return "airtel"
    if "jio" in text or "rjil" in text:
        return "jio"
    if "bsnl" in text:
        return "bsnl"
    return text


def normalize_technology(value: Any) -> str:
    return str(value or "").strip().lower()


def iter_feature_dicts(value: Any) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    if isinstance(value, dict):
        maybe_features = value.get("features")
        if isinstance(maybe_features, list):
            for feature in maybe_features:
                if isinstance(feature, dict):
                    features.append(feature)
        if "geometry" in value and isinstance(value.get("geometry"), dict):
            features.append(value)
        for child in value.values():
            features.extend(iter_feature_dicts(child))
    elif isinstance(value, list):
        for child in value[:100]:
            features.extend(iter_feature_dicts(child))
    return features


def score_segments_from_trai(city: str, segments: list[SegmentPoint]) -> tuple[dict[str, float], dict[str, Any]] | None:
    raw_path = TRAI_DIR / f"{city}_coverage_raw.json"
    if not raw_path.exists():
        return None

    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    responses = payload.get("responses", [])
    if not responses:
        return None

    polygons: list[tuple[BaseGeometry, float]] = []
    for response in responses:
        tech = normalize_technology(response.get("technology"))
        operator = normalize_operator(response.get("operator"))
        base_score = TRAI_TECHNOLOGY_WEIGHTS.get(tech)
        reliability = OPERATOR_RELIABILITY.get(operator)
        if base_score is None or reliability is None:
            continue

        for feature in iter_feature_dicts(response.get("payload")):
            geometry_payload = feature.get("geometry")
            if not isinstance(geometry_payload, dict):
                continue
            try:
                geometry = shape(geometry_payload)
            except Exception:
                continue
            if geometry.is_empty:
                continue
            polygons.append((geometry, float(base_score * reliability)))

    if not polygons:
        return None

    scores: dict[str, float] = {}
    covered = 0
    for segment in segments:
        point = Point(segment.lon, segment.lat)
        best_score = ROAD_FALLBACK_SCORE
        for polygon, polygon_score in polygons:
            try:
                if polygon.contains(point):
                    best_score = max(best_score, polygon_score)
            except Exception:
                continue
        if best_score > ROAD_FALLBACK_SCORE:
            covered += 1
        scores[segment.segment_id] = round(float(min(best_score, 1.0)), 3)

    metadata = {
        "city": city,
        "source": "TRAI",
        "tower_count": 0,
        "coverage_percent": round((covered / max(len(segments), 1)) * 100.0, 1),
        "dead_zone_percent": round(
            (sum(1 for value in scores.values() if value < 0.3) / max(len(scores), 1)) * 100.0,
            1,
        ),
        "last_updated": payload.get("fetched_at"),
        "polygon_count": len(polygons),
    }
    return scores, metadata


def normalize_radio(value: str) -> float:
    return RADIO_WEIGHTS.get(str(value or "").strip().lower(), 0.5)


def load_tower_data(city: str) -> TowerData | None:
    csv_path = TOWERS_DIR / f"{city}_towers.csv"
    if not csv_path.exists():
        return None

    coords: list[tuple[float, float]] = []
    ranges: list[float] = []
    weights: list[float] = []

    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (KeyError, TypeError, ValueError):
                continue

            raw_range = row.get("range") or "0"
            try:
                tower_range = float(raw_range)
            except (TypeError, ValueError):
                tower_range = 0.0
            tower_range = min(max(tower_range, 250.0), 2000.0)
            if tower_range <= 0:
                tower_range = 2000.0

            coords.append((lat, lon))
            ranges.append(tower_range)
            weights.append(normalize_radio(row.get("radio", "")))

    if not coords:
        return None

    meta_path = TOWERS_DIR / f"{city}_towers_meta.json"
    last_updated = ""
    if meta_path.exists():
        try:
            last_updated = json.loads(meta_path.read_text(encoding="utf-8")).get("last_updated", "")
        except Exception:
            last_updated = ""

    return TowerData(
        coords=np.asarray(coords, dtype=np.float32),
        ranges=np.asarray(ranges, dtype=np.float32),
        weights=np.asarray(weights, dtype=np.float32),
        count=len(coords),
        last_updated=last_updated,
    )


def compute_signal_scores_numpy(
    segment_coords: np.ndarray,
    tower_coords: np.ndarray,
    tower_ranges: np.ndarray,
    tower_weights: np.ndarray,
    chunk_size: int = 4096,
) -> np.ndarray:
    scores = np.full(segment_coords.shape[0], ROAD_FALLBACK_SCORE, dtype=np.float32)
    if segment_coords.size == 0 or tower_coords.size == 0:
        return scores

    for start in range(0, segment_coords.shape[0], chunk_size):
        stop = min(start + chunk_size, segment_coords.shape[0])
        chunk = segment_coords[start:stop]
        dlat = tower_coords[:, 0][None, :] - chunk[:, 0][:, None]
        dlon = tower_coords[:, 1][None, :] - chunk[:, 1][:, None]
        dist = np.sqrt(dlat * dlat + dlon * dlon, dtype=np.float32) * np.float32(111000.0)
        in_range = dist <= tower_ranges[None, :]
        coverage_ratio = 1.0 - (dist / tower_ranges[None, :])
        weighted = np.clip(coverage_ratio * 0.9 + 0.1, ROAD_FALLBACK_SCORE, 1.0) * tower_weights[None, :]
        weighted = np.where(in_range, weighted, ROAD_FALLBACK_SCORE)
        scores[start:stop] = np.clip(weighted.max(axis=1), ROAD_FALLBACK_SCORE, 1.0).astype(np.float32)
    return scores


def compute_signal_scores_gpu(
    segment_coords: np.ndarray,
    tower_coords: np.ndarray,
    tower_ranges: np.ndarray,
    tower_weights: np.ndarray,
    chunk_size: int = 4096,
) -> np.ndarray:
    if not USE_CUPY or cp is None:
        return compute_signal_scores_numpy(segment_coords, tower_coords, tower_ranges, tower_weights, chunk_size)

    scores = np.full(segment_coords.shape[0], ROAD_FALLBACK_SCORE, dtype=np.float32)
    if segment_coords.size == 0 or tower_coords.size == 0:
        return scores

    towers_gpu = cp.asarray(tower_coords, dtype=cp.float32)
    ranges_gpu = cp.asarray(tower_ranges, dtype=cp.float32)
    weights_gpu = cp.asarray(tower_weights, dtype=cp.float32)

    try:
        for start in range(0, segment_coords.shape[0], chunk_size):
            stop = min(start + chunk_size, segment_coords.shape[0])
            chunk_gpu = cp.asarray(segment_coords[start:stop], dtype=cp.float32)
            dlat = towers_gpu[:, 0][None, :] - chunk_gpu[:, 0][:, None]
            dlon = towers_gpu[:, 1][None, :] - chunk_gpu[:, 1][:, None]
            dist = cp.sqrt(dlat * dlat + dlon * dlon) * cp.float32(111000.0)
            in_range = dist <= ranges_gpu[None, :]
            coverage_ratio = 1.0 - (dist / ranges_gpu[None, :])
            weighted = cp.clip(coverage_ratio * 0.9 + 0.1, ROAD_FALLBACK_SCORE, 1.0) * weights_gpu[None, :]
            weighted = cp.where(in_range, weighted, ROAD_FALLBACK_SCORE)
            chunk_scores = cp.clip(cp.max(weighted, axis=1), ROAD_FALLBACK_SCORE, 1.0)
            scores[start:stop] = cp.asnumpy(chunk_scores).astype(np.float32, copy=False)
    finally:
        cp.get_default_memory_pool().free_all_blocks()

    return scores


def score_segments_from_towers(city: str, segments: list[SegmentPoint]) -> tuple[dict[str, float], dict[str, Any]] | None:
    tower_data = load_tower_data(city)
    if tower_data is None:
        return None

    segment_coords = np.asarray([(segment.lat, segment.lon) for segment in segments], dtype=np.float32)
    scores_array = compute_signal_scores_gpu(
        segment_coords,
        tower_data.coords,
        tower_data.ranges,
        tower_data.weights,
    )
    scores = {
        segment.segment_id: round(float(score), 3)
        for segment, score in zip(segments, scores_array, strict=False)
    }
    metadata = {
        "city": city,
        "source": "OpenCelliD",
        "tower_count": tower_data.count,
        "coverage_percent": round(float(np.mean(scores_array >= 0.6) * 100.0), 1),
        "dead_zone_percent": round(float(np.mean(scores_array < 0.3) * 100.0), 1),
        "last_updated": tower_data.last_updated,
    }
    return scores, metadata


def save_scores(city: str, scores: dict[str, float], metadata: dict[str, Any]) -> None:
    score_path = SCORES_DIR / f"{city}_real_scores.pkl"
    meta_path = SCORES_DIR / f"{city}_real_scores_meta.json"

    with score_path.open("wb") as handle:
        pickle.dump(scores, handle, protocol=5)
    with meta_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)


def main() -> int:
    ensure_dirs()

    for city in ("bangalore", "chennai"):
        graph = load_graph(city)
        segments = build_segment_points(graph)

        scored = score_segments_from_trai(city, segments)
        if scored is None:
            scored = score_segments_from_towers(city, segments)
        if scored is None:
            raise RuntimeError(f"No TRAI polygons or OpenCelliD towers available for {city}")

        scores, metadata = scored
        save_scores(city, scores, metadata)
        print(
            f"[coverage] {city}: source={metadata['source']} "
            f"scores={len(scores)} dead={metadata['dead_zone_percent']}% "
            f"good={metadata['coverage_percent']}%"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
