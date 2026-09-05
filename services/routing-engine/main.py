from __future__ import annotations

import ast
import asyncio
import gc
import json
import math
import os
import subprocess
import time
from collections import Counter, OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Literal
from urllib import error, request

import networkx as nx
import numpy as np
import osmnx as ox
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from shapely import wkt
from shapely.geometry import LineString

try:
    import cupy as cp

    USE_CUPY = True
    print("[routing] CuPy GPU available - accelerating weight computation")
except ImportError:
    cp = None
    USE_CUPY = False
    print("[routing] CuPy not available, using CPU numpy")

CACHE_TTL_SECONDS = 24 * 60 * 60
SCORE_REFRESH_SECONDS = 60
ROUTE_CACHE_TTL_SECONDS = 10 * 60
ROUTE_CACHE_MAX_ENTRIES = 200
ROUTE_CACHE_SCHEMA_VERSION = 4
DEFAULT_SUPPORTED_CITIES = "bangalore"
DEFAULT_DEFAULT_CITY = "bangalore"
DEFAULT_DATA_SERVICE_URL = "http://data-service:8001"
DEFAULT_BANGALORE_QUERY = "Bangalore, Karnataka, India"
SERVICE_DIR = Path(__file__).resolve().parent
APP_CACHE_DIR = Path(os.getenv("APP_CACHE_DIR", str(SERVICE_DIR / "cache")))
GRAPH_CACHE_DIR = Path(os.getenv("GRAPH_CACHE_DIR", str(APP_CACHE_DIR / "graphs")))
ROUTE_CACHE_PATH = Path(os.getenv("ROUTE_CACHE_PATH", str(APP_CACHE_DIR / "route_cache.json")))
CITY_PLACE_QUERIES: dict[str, str] = {
    "bangalore": os.getenv("BANGALORE_PLACE_QUERY", DEFAULT_BANGALORE_QUERY),
}
CPU_CORES = max(1, os.cpu_count() or 1)
THREAD_POOL = ThreadPoolExecutor(
    max_workers=CPU_CORES,
    thread_name_prefix="routing_worker",
)
CITY_LOCKS = defaultdict(Lock)
GRAPH_CACHE: dict[str, "GraphState"] = {}
GRAPH_STATUS: dict[str, str] = {}
GRAPH_ERRORS: dict[str, str] = {}
PRELOAD_TASKS: dict[str, asyncio.Task[Any]] = {}
SCORE_REFRESH_STOP = Event()
SCORE_REFRESH_THREAD: Thread | None = None
GPU_NAME = "CPU"
ACTIVE_CITY: str | None = None
MAX_RAM_MB = int(os.getenv("MAX_RAM_MB", "2048"))
ROUTE_CACHE_LOCK = Lock()
ROUTE_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()

ox.settings.use_cache = True
ox.settings.log_console = False

app = FastAPI(title="Connectivity-Aware Routing Engine", version="0.4.0")

PROVENANCE_OPENCELLID = "opencellid"
PROVENANCE_TRAI = "trai"
PROVENANCE_ML_SYNTHETIC = "ml_synthetic"
PROVENANCE_HYBRID = "hybrid"
PROVENANCE_UNKNOWN = "unknown"


def canonical_provenance(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "opencellid": PROVENANCE_OPENCELLID,
        "open_cell_id": PROVENANCE_OPENCELLID,
        "trai": PROVENANCE_TRAI,
        "trai_india": PROVENANCE_TRAI,
        "ml": PROVENANCE_ML_SYNTHETIC,
        "ml_estimate": PROVENANCE_ML_SYNTHETIC,
        "ml_synthetic": PROVENANCE_ML_SYNTHETIC,
        "synthetic": PROVENANCE_ML_SYNTHETIC,
        "hybrid": PROVENANCE_HYBRID,
        "mixed": PROVENANCE_HYBRID,
        "mixed_source": PROVENANCE_HYBRID,
        "opencellid+ml": PROVENANCE_HYBRID,
        "unknown": PROVENANCE_UNKNOWN,
    }
    return aliases.get(normalized, PROVENANCE_UNKNOWN)


def first_payload_percentage(payload: dict[str, Any], *names: str) -> float:
    for name in names:
        if name not in payload or payload[name] is None:
            continue
        try:
            return max(0.0, min(100.0, float(payload[name])))
        except (TypeError, ValueError):
            continue
    return 0.0

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
    mode: Literal["fastest", "connected", "balanced"]
    vehicle: Literal["scooter", "bike", "car", "truck"] = "car"


@dataclass
class PreparedVehicleGraph:
    vehicle: str
    scores: Any
    risk_points: Any
    risk_multiplier: Any
    fastest_cost: Any
    balanced_cost: Any
    connected_cost: Any
    dead_zone_mask: Any
    residential_night_mask: Any
    chennai_outer_mask: Any
    flood_mask: Any
    highway_mask: Any
    below_tolerance_mask: Any
    stable_mask: Any
    flood_labels: dict[int, str] = field(default_factory=dict)
    risk_time_bucket: str = "day"
    risk_hour: int = 12
    computed_at: float = 0.0
    source_scores_updated_at: float = 0.0


@dataclass
class GraphState:
    city: str
    base_graph: Any
    expires_at: float
    scores_updated_at: float = 0.0
    edge_count: int = 0
    travel_time_norms: Any | None = None
    node_index: dict[str, Any] | None = None
    vehicle_graphs: dict[str, PreparedVehicleGraph] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)
    score_refreshing: bool = False


STRATEGY_FACTORS: dict[str, dict[str, float]] = {
    "fastest": {"speed": 1.0, "connectivity": 0.0, "risk": 0.0, "risk_scale": 0.0},
    "balanced": {"speed": 0.7, "connectivity": 0.9, "risk": 0.6, "risk_scale": 0.5},
    "connected": {"speed": 0.45, "connectivity": 1.25, "risk": 1.0, "risk_scale": 1.0},
}
VEHICLE_PROFILES: dict[str, dict[str, Any]] = {
    "scooter": {
        "speed": 0.3,
        "connectivity": 0.3,
        "risk": 0.4,
        "avoid_highways": True,
        "dead_zone_tolerance": 0.2,
        "summary": "avoids highways and prioritizes connectivity over speed",
    },
    "bike": {
        "speed": 0.4,
        "connectivity": 0.3,
        "risk": 0.3,
        "avoid_highways": True,
        "dead_zone_tolerance": 0.25,
        "summary": "avoids highways and balances speed with safer coverage",
    },
    "car": {
        "speed": 0.4,
        "connectivity": 0.4,
        "risk": 0.2,
        "avoid_highways": False,
        "dead_zone_tolerance": 0.3,
        "summary": "balances travel time, connectivity, and comfort",
    },
    "truck": {
        "speed": 0.2,
        "connectivity": 0.5,
        "risk": 0.3,
        "avoid_highways": False,
        "dead_zone_tolerance": 0.15,
        "require_stable_v2x": True,
        "summary": "prioritizes stable connectivity for larger vehicle operations",
    },
}
FLOOD_ZONES: dict[str, list[dict[str, float | str]]] = {
    "bangalore": [
        {"label": "Bellandur Lake", "lat": 12.93, "lon": 77.67},
        {"label": "Varthur Lake", "lat": 12.93, "lon": 77.74},
        {"label": "Hebbal Lake", "lat": 13.05, "lon": 77.59},
    ],
    "chennai": [
        {"label": "Adyar River Basin", "lat": 13.00, "lon": 80.24},
        {"label": "Buckingham Canal", "lat": 13.08, "lon": 80.27},
    ],
}
RISK_RADIUS_METERS = 500.0
CITY_UTC_OFFSETS_MINUTES = {
    "bangalore": 5 * 60 + 30,
    "chennai": 5 * 60 + 30,
}
STRATEGY_ORDER: list[str] = ["fastest", "balanced", "connected"]
WEIGHT_ATTR_BY_MODE = {
    "fastest": "fastest_cost",
    "balanced": "balanced_cost",
    "connected": "connected_cost",
}
ROAD_SPEEDS_KPH = {
    "motorway": 90.0,
    "trunk": 70.0,
    "primary": 50.0,
    "secondary": 40.0,
    "tertiary": 30.0,
    "residential": 20.0,
    "construction": 15.0,
    "unknown": 25.0,
}
TEST_ROUTE_COORDS: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "bangalore": ((12.9716, 77.5946), (12.9948, 77.6699)),
    "chennai": ((13.0827, 80.2707), (13.0569, 80.2425)),
}


def detect_system_gpu() -> None:
    global GPU_NAME

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        gpu_output = result.stdout.strip()
        if gpu_output:
            GPU_NAME = gpu_output.split(",", 1)[0].strip()
            print(f"[gpu] {gpu_output}")
        else:
            print("[gpu] nvidia-smi not found, running on CPU")
    except Exception:
        print("[gpu] nvidia-smi not found, running on CPU")


def validate_cupy_runtime() -> None:
    global USE_CUPY

    if not USE_CUPY or cp is None:
        return

    try:
        probe = cp.arange(4, dtype=cp.float32)
        float(probe.sum().item())
    except Exception as exc:
        USE_CUPY = False
        print(f"[routing] CuPy runtime unavailable, using CPU numpy: {exc}")


def configure_cpu_affinity() -> None:
    print(f"[routing] CPU cores available: {CPU_CORES}")
    try:
        import psutil  # type: ignore

        process = psutil.Process()
        process.cpu_affinity(list(range(CPU_CORES)))
        print(f"[routing] CPU affinity set to {CPU_CORES} cores")
    except Exception as exc:
        print(f"[routing] CPU affinity not set: {exc}")


def default_city() -> str:
    configured = slugify_city_name(os.getenv("DEFAULT_CITY", DEFAULT_DEFAULT_CITY))
    cities = supported_cities()
    if configured in cities:
        return configured
    return cities[0]


def free_gpu_memory() -> None:
    if not USE_CUPY or cp is None:
        return
    try:
        cp.get_default_memory_pool().free_all_blocks()
    except Exception:
        pass


def process_memory_mb() -> float:
    try:
        import psutil  # type: ignore

        return float(psutil.Process(os.getpid()).memory_info().rss) / (1024 * 1024)
    except Exception:
        pass

    if os.name == "nt":
        try:
            import ctypes

            class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS_EX()
            counters.cb = ctypes.sizeof(counters)
            ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(),
                ctypes.byref(counters),
                counters.cb,
            )
            return float(counters.WorkingSetSize) / (1024 * 1024)
        except Exception:
            return 0.0

    try:
        with open("/proc/self/statm", "r", encoding="utf-8") as handle:
            resident_pages = int(handle.read().split()[1])
        return float(resident_pages * os.sysconf("SC_PAGE_SIZE")) / (1024 * 1024)
    except Exception:
        return 0.0


def current_vram_mb() -> float:
    if not USE_CUPY or cp is None:
        return 0.0
    try:
        free_bytes, total_bytes = cp.cuda.runtime.memGetInfo()
        return float(total_bytes - free_bytes) / (1024 * 1024)
    except Exception:
        return 0.0


def log_vram_usage(label: str = "") -> None:
    if not USE_CUPY or cp is None:
        return
    try:
        pool = cp.get_default_memory_pool()
        used_mb = pool.used_bytes() / (1024 * 1024)
        total_mb = pool.total_bytes() / (1024 * 1024)
        prefix = f"[vram] {label} " if label else "[vram] "
        print(f"{prefix}used={used_mb:.0f}MB total={total_mb:.0f}MB")
    except Exception:
        pass


def load_route_cache() -> None:
    if not ROUTE_CACHE_PATH.exists():
        return
    try:
        payload = json.loads(ROUTE_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[cache] failed to read route cache: {exc}")
        return

    if not isinstance(payload, dict):
        return
    with ROUTE_CACHE_LOCK:
        ROUTE_CACHE.clear()
        for cache_key, entry in payload.items():
            if isinstance(entry, dict):
                ROUTE_CACHE[str(cache_key)] = entry


def persist_route_cache() -> None:
    ROUTE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ROUTE_CACHE_LOCK:
        payload = dict(ROUTE_CACHE)
    ROUTE_CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")


def route_cache_key(
    city: str,
    origin: tuple[float, float],
    destination: tuple[float, float],
    mode: str,
    vehicle: str,
    risk_time_bucket: str | None = None,
) -> str:
    return json.dumps(
        {
            "city": city,
            "origin": [round(origin[0], 5), round(origin[1], 5)],
            "destination": [round(destination[0], 5), round(destination[1], 5)],
            "mode": mode,
            "vehicle": vehicle,
            "risk_time_bucket": risk_time_bucket or city_risk_time_bucket(city),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def get_cached_route(
    city: str,
    origin: tuple[float, float],
    destination: tuple[float, float],
    mode: str,
    vehicle: str,
    score_version: float,
    risk_time_bucket: str | None = None,
) -> dict[str, Any] | None:
    cache_key = route_cache_key(
        city,
        origin,
        destination,
        mode,
        vehicle,
        risk_time_bucket,
    )
    now = time.time()
    with ROUTE_CACHE_LOCK:
        entry = ROUTE_CACHE.get(cache_key)
        if entry is None:
            return None
        stored_at = float(entry.get("stored_at") or 0.0)
        cached_score_version = float(entry.get("score_version") or 0.0)
        schema_version = int(entry.get("schema_version") or 0)
        if (
            schema_version != ROUTE_CACHE_SCHEMA_VERSION
            or now - stored_at > ROUTE_CACHE_TTL_SECONDS
            or cached_score_version < score_version
        ):
            ROUTE_CACHE.pop(cache_key, None)
            return None
        ROUTE_CACHE.move_to_end(cache_key)
        response = entry.get("response")
        if isinstance(response, dict):
            print(f"[cache] route hit for {city}/{mode}/{vehicle}")
            return response
    return None


def store_cached_route(
    city: str,
    origin: tuple[float, float],
    destination: tuple[float, float],
    mode: str,
    vehicle: str,
    score_version: float,
    response: dict[str, Any],
    risk_time_bucket: str | None = None,
) -> None:
    cache_key = route_cache_key(
        city,
        origin,
        destination,
        mode,
        vehicle,
        risk_time_bucket,
    )
    with ROUTE_CACHE_LOCK:
        ROUTE_CACHE[cache_key] = {
            "schema_version": ROUTE_CACHE_SCHEMA_VERSION,
            "stored_at": time.time(),
            "score_version": score_version,
            "response": response,
        }
        ROUTE_CACHE.move_to_end(cache_key)
        while len(ROUTE_CACHE) > ROUTE_CACHE_MAX_ENTRIES:
            ROUTE_CACHE.popitem(last=False)
    persist_route_cache()


def array_nbytes(values: Any) -> int:
    try:
        return int(values.nbytes)
    except Exception:
        return 0


def to_device_array(values: np.ndarray) -> Any:
    float32_values = np.asarray(values, dtype=np.float32)
    if USE_CUPY and cp is not None:
        gpu_values = cp.asarray(float32_values, dtype=cp.float32)
        del float32_values
        return gpu_values
    return float32_values


def to_bool_device_array(values: np.ndarray) -> Any:
    bool_values = np.asarray(values, dtype=bool)
    if USE_CUPY and cp is not None:
        gpu_values = cp.asarray(bool_values)
        del bool_values
        return gpu_values
    return bool_values


def extract_array(values: Any, indexes: np.ndarray | list[int]) -> np.ndarray:
    index_array = np.asarray(indexes, dtype=np.int32)
    if USE_CUPY and cp is not None and isinstance(values, cp.ndarray):
        return cp.asnumpy(values[cp.asarray(index_array, dtype=cp.int32)])
    return np.asarray(values[index_array])


def weight_array_for_mode(prepared: PreparedVehicleGraph, mode: str) -> Any:
    if mode == "fastest":
        return prepared.fastest_cost
    if mode == "connected":
        return prepared.connected_cost
    return prepared.balanced_cost


def log_memory_limit(service_name: str) -> None:
    current_mb = process_memory_mb()
    if MAX_RAM_MB > 0:
        print(f"[memory] {service_name} limit {MAX_RAM_MB}MB, current {current_mb:.1f}MB")


def data_service_url() -> str:
    return os.getenv("DATA_SERVICE_URL", DEFAULT_DATA_SERVICE_URL).rstrip("/")


def slugify_city_name(city: str) -> str:
    return "_".join(
        part
        for part in city.strip().lower().replace("-", "_").replace(" ", "_").split("_")
        if part
    )


def supported_cities() -> list[str]:
    configured = os.getenv("SUPPORTED_CITIES", DEFAULT_SUPPORTED_CITIES)
    cities: list[str] = []
    for raw_city in configured.split(","):
        city_slug = slugify_city_name(raw_city)
        if city_slug and city_slug not in cities:
            cities.append(city_slug)
    return cities


def normalize_city(city: str) -> str:
    city_slug = slugify_city_name(city)
    all_cities = supported_cities()
    if city_slug not in all_cities:
        supported = ", ".join(all_cities)
        raise ValueError(f"Unsupported city '{city}'. Supported cities: {supported}.")
    return city_slug


def place_query(city: str) -> str:
    city_slug = normalize_city(city)
    return CITY_PLACE_QUERIES.get(city_slug, DEFAULT_BANGALORE_QUERY)


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


def normalize_surface(surface: Any) -> str:
    surface = normalize_listish(surface)
    if isinstance(surface, list):
        surface = surface[0] if surface else None
    if isinstance(surface, str) and ";" in surface:
        surface = surface.split(";", 1)[0]
    return str(surface) if surface else ""


def normalize_name(name: Any) -> str:
    name = normalize_listish(name)
    if isinstance(name, list):
        return ", ".join(str(part) for part in name if part)
    return str(name) if name else ""


def add_edge_speeds_and_times(graph):
    if hasattr(ox, "add_edge_speeds") and hasattr(ox, "add_edge_travel_times"):
        graph = ox.add_edge_speeds(graph)
        return ox.add_edge_travel_times(graph)
    graph = ox.routing.add_edge_speeds(graph)
    return ox.routing.add_edge_travel_times(graph)


def build_node_index(graph) -> dict[str, Any]:
    node_items = list(graph.nodes(data=True))
    node_ids = np.asarray([serialize_node(node) for node, _ in node_items], dtype=np.int64)
    latitudes = np.asarray([float(data.get("y", 0.0)) for _, data in node_items], dtype=np.float32)
    longitudes = np.asarray([float(data.get("x", 0.0)) for _, data in node_items], dtype=np.float32)
    index: dict[str, Any] = {
        "ids_cpu": node_ids,
        "lats_cpu": latitudes,
        "lons_cpu": longitudes,
    }
    if USE_CUPY and cp is not None and node_ids.size:
        try:
            index["ids_gpu"] = cp.asarray(node_ids)
            index["lats_gpu"] = cp.asarray(latitudes)
            index["lons_gpu"] = cp.asarray(longitudes)
        except Exception as exc:
            print(f"[routing] GPU node index unavailable, using CPU lookup: {exc}")
    return index


def nearest_node_gpu(node_index: dict[str, Any], latitude: float, longitude: float) -> int:
    ids_gpu = node_index.get("ids_gpu")
    lats_gpu = node_index.get("lats_gpu")
    lons_gpu = node_index.get("lons_gpu")
    if not USE_CUPY or cp is None or ids_gpu is None or lats_gpu is None or lons_gpu is None:
        raise RuntimeError("GPU node index unavailable")

    q_lat = cp.float32(latitude)
    q_lon = cp.float32(longitude)
    d_lat = (lats_gpu - q_lat) * cp.float32(111000.0)
    d_lon = (lons_gpu - q_lon) * cp.float32(111000.0) * cp.cos(cp.radians(q_lat))
    nearest_idx = int(cp.argmin(d_lat * d_lat + d_lon * d_lon).item())
    return int(ids_gpu[nearest_idx].item())


def nearest_node_cpu(node_index: dict[str, Any], latitude: float, longitude: float) -> int:
    latitudes = np.asarray(node_index["lats_cpu"], dtype=np.float32)
    longitudes = np.asarray(node_index["lons_cpu"], dtype=np.float32)
    distances = (latitudes - np.float32(latitude)) ** 2 + (longitudes - np.float32(longitude)) ** 2
    nearest_idx = int(np.argmin(distances))
    return int(np.asarray(node_index["ids_cpu"], dtype=np.int64)[nearest_idx])


def find_nearest_node(graph, latitude: float, longitude: float, node_index: dict[str, Any] | None = None) -> int:
    try:
        if node_index is not None and USE_CUPY and cp is not None and node_index.get("ids_gpu") is not None:
            node = nearest_node_gpu(node_index, latitude, longitude)
        elif hasattr(ox, "distance") and hasattr(ox.distance, "nearest_nodes"):
            node = ox.distance.nearest_nodes(graph, X=longitude, Y=latitude)
        else:
            node = ox.nearest_nodes(graph, X=longitude, Y=latitude)
    except Exception as exc:
        print(f"[routing] nearest_nodes fallback for ({latitude}, {longitude}): {exc}")
        if node_index is not None:
            node = nearest_node_cpu(node_index, latitude, longitude)
        else:
            node = min(
                graph.nodes,
                key=lambda candidate: (
                    (float(graph.nodes[candidate]["y"]) - latitude) ** 2
                    + (float(graph.nodes[candidate]["x"]) - longitude) ** 2
                ),
            )

    if node not in graph.nodes:
        print(f"[routing] nearest node {node} not in connected graph, using manual fallback")
        if node_index is None:
            raise HTTPException(status_code=500, detail="No connected graph nodes available")
        node = nearest_node_cpu(node_index, latitude, longitude)
    return int(node)


def normalize_geometry(geometry: Any) -> LineString | None:
    if geometry is None:
        return None
    if isinstance(geometry, str):
        return wkt.loads(geometry)
    return geometry


def edge_geometry(graph, u: int, v: int, data: dict[str, Any]) -> LineString:
    geometry = normalize_geometry(data.get("geometry"))
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


def midpoint_lat_lon(geometry: LineString) -> tuple[float, float]:
    midpoint = geometry.interpolate(0.5, normalized=True)
    return float(midpoint.y), float(midpoint.x)


def graph_cache_path(city: str) -> Path:
    return GRAPH_CACHE_DIR / f"{normalize_city(city)}.graphml"


def ensure_connected_graph(graph):
    print("[graph] checking connectivity...")
    total_nodes = graph.number_of_nodes()
    total_edges = graph.number_of_edges()
    print(f"[graph] nodes: {total_nodes}, edges: {total_edges}")
    if total_nodes == 0:
        raise RuntimeError("Loaded graph has no nodes")

    if graph.is_directed():
        largest_component = max(nx.strongly_connected_components(graph), key=len)
        component_name = "SCC"
    else:
        largest_component = max(nx.connected_components(graph), key=len)
        component_name = "CC"

    connected_graph = graph.subgraph(largest_component).copy()
    kept_ratio = (len(largest_component) / max(total_nodes, 1)) * 100.0
    print(
        f"[graph] largest {component_name}: {connected_graph.number_of_nodes()} nodes "
        f"({kept_ratio:.1f}% of graph)"
    )
    removed_nodes = total_nodes - connected_graph.number_of_nodes()
    if removed_nodes > 0:
        print(f"[graph] removed {removed_nodes} disconnected nodes")
    return connected_graph


def simplify_city_graph(city: str, graph):
    try:
        graph = ox.simplify_graph(graph)
        graph = ensure_connected_graph(graph)
    except Exception:
        pass

    try:
        graph_projected = ox.project_graph(graph)
        graph_projected = ox.consolidate_intersections(
            graph_projected,
            tolerance=15,
            rebuild_graph=True,
            dead_ends=False,
        )
        graph = ox.project_graph(graph_projected, to_crs="epsg:4326")
        graph = ensure_connected_graph(graph)
    except Exception as exc:
        print(f"[graph] consolidation skipped for {city}: {exc}")

    print(
        f"[graph] simplified: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges"
    )
    graph = ensure_connected_graph(graph)
    return graph


def load_or_fetch_graph(city: str):
    city_slug = normalize_city(city)
    cache_path = graph_cache_path(city_slug)
    GRAPH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if cache_path.exists():
        print("[graph] Loading Bangalore graph (cached: yes)")
        graph = ensure_connected_graph(ox.load_graphml(cache_path))
        ox.save_graphml(graph, cache_path)
        return graph

    print("[graph] Loading Bangalore graph (cached: no)")
    graph = ox.graph_from_place(
        place_query(city_slug),
        network_type="drive",
        simplify=False,
        retain_all=False,
        truncate_by_edge=True,
    )
    graph = simplify_city_graph(city_slug, graph)
    ox.save_graphml(graph, cache_path)
    print(f"[graph] Saved Bangalore graph cache to {cache_path}")
    return graph


def normalize_speed_kph(raw_speed: Any, road_type: str) -> float:
    raw_speed = normalize_listish(raw_speed)
    if isinstance(raw_speed, list):
        raw_speed = raw_speed[0] if raw_speed else None
    if isinstance(raw_speed, str):
        cleaned = raw_speed.replace("km/h", "").replace("kph", "").strip()
        cleaned = cleaned.split(";", 1)[0].strip()
        try:
            return max(float(cleaned), 1.0)
        except ValueError:
            return ROAD_SPEEDS_KPH.get(road_type, ROAD_SPEEDS_KPH["unknown"])
    if raw_speed is None:
        return ROAD_SPEEDS_KPH.get(road_type, ROAD_SPEEDS_KPH["unknown"])
    try:
        return max(float(raw_speed), 1.0)
    except (TypeError, ValueError):
        return ROAD_SPEEDS_KPH.get(road_type, ROAD_SPEEDS_KPH["unknown"])


def fetch_city_scores(
    city: str,
) -> tuple[dict[str, float], float, dict[str, str]]:
    score_request = request.Request(f"{data_service_url()}/scores/{city}", method="GET")
    with request.urlopen(score_request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))

    raw_scores = payload.get("scores", {})
    if not isinstance(raw_scores, dict):
        raise ValueError("Data service returned a non-object scores payload")
    updated_at = float(payload.get("updated_at", 0.0) or 0.0)
    scores = {str(key): float(value) for key, value in raw_scores.items()}
    raw_edge_sources = payload.get("edge_sources", {})
    aggregate_source = canonical_provenance(
        payload.get("provenance_source") or payload.get("source")
    )
    fallback_source = (
        aggregate_source
        if aggregate_source in {PROVENANCE_OPENCELLID, PROVENANCE_TRAI}
        else PROVENANCE_ML_SYNTHETIC
    )
    edge_sources: dict[str, str] = {}
    for segment_id in scores:
        edge_source = canonical_provenance(
            raw_edge_sources.get(segment_id, fallback_source)
            if isinstance(raw_edge_sources, dict)
            else fallback_source
        )
        edge_sources[segment_id] = (
            PROVENANCE_UNKNOWN
            if edge_source == PROVENANCE_HYBRID
            else edge_source
        )
    return scores, updated_at, edge_sources


def safe_fetch_city_scores(
    city: str,
) -> tuple[dict[str, float], float, dict[str, str]]:
    try:
        return fetch_city_scores(city)
    except (TimeoutError, error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[scores] failed to fetch {city}: {exc}")
        return {}, 0.0, {}


def edge_travel_time_seconds(data: dict[str, Any]) -> float:
    try:
        length = float(data.get("length", 50.0) or 50.0)
    except (TypeError, ValueError):
        length = 50.0
    if not math.isfinite(length) or length <= 0:
        length = 50.0
    road_type = str(data.get("road_type") or normalize_highway(data.get("highway")))
    speed_kph = normalize_speed_kph(data.get("speed_kph"), road_type)
    speed_mps = max(speed_kph * (1000.0 / 3600.0), 1.0)
    try:
        travel_time = float(data.get("travel_time", 0.0) or 0.0)
    except (TypeError, ValueError):
        travel_time = 0.0
    if not math.isfinite(travel_time) or travel_time <= 0:
        travel_time = length / speed_mps
    return max(travel_time, 0.001)


def annotate_base_graph(graph):
    graph = add_edge_speeds_and_times(graph)
    travel_times: list[float] = []

    for edge_index, (u, v, key, data) in enumerate(graph.edges(keys=True, data=True)):
        geometry = edge_geometry(graph, u, v, data)
        lat, lon = midpoint_lat_lon(geometry)
        road_type = normalize_highway(data.get("highway"))
        try:
            length = float(data.get("length") or 1.0)
        except (TypeError, ValueError):
            length = 1.0
        if not math.isfinite(length) or length <= 0:
            length = 1.0
        speed_kph = normalize_speed_kph(data.get("speed_kph"), road_type)
        normalized_time_data = {
            **data,
            "length": length,
            "road_type": road_type,
            "speed_kph": speed_kph,
        }
        travel_time = edge_travel_time_seconds(normalized_time_data)
        data["edge_index"] = edge_index
        data["segment_id"] = f"{u}-{v}-{key}"
        data["road_type"] = road_type
        data["surface_type"] = normalize_surface(data.get("surface"))
        data["road_name"] = normalize_name(data.get("name"))
        data["mid_lat"] = lat
        data["mid_lon"] = lon
        data["length"] = length
        data["travel_time"] = travel_time
        data["connectivity_score"] = float(data.get("connectivity_score") or 0.5)
        data["provenance_source"] = PROVENANCE_ML_SYNTHETIC
        data["speed_kph"] = speed_kph
        data["composite_cost"] = float(data.get("composite_cost", travel_time))
        travel_times.append(travel_time)

    min_time = min(travel_times) if travel_times else 0.0
    max_time = max(travel_times) if travel_times else 1.0
    spread = max(max_time - min_time, 1e-9)
    for _, _, _, data in graph.edges(keys=True, data=True):
        data["travel_time_norm"] = (float(data["travel_time"]) - min_time) / spread

    return graph


def apply_scores_to_base_graph(
    graph,
    scores: dict[str, float],
    edge_sources: dict[str, str] | None = None,
) -> None:
    provided_sources = edge_sources or {}
    for _, _, _, data in graph.edges(keys=True, data=True):
        segment_id = str(data["segment_id"])
        data["connectivity_score"] = float(scores.get(segment_id, 0.5))
        data["provenance_source"] = canonical_provenance(
            provided_sources.get(segment_id, PROVENANCE_ML_SYNTHETIC)
        )


def haversine_meters(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    radius_m = 6_371_000.0
    d_lat = math.radians(b_lat - a_lat)
    d_lon = math.radians(b_lon - a_lon)
    lat_1 = math.radians(a_lat)
    lat_2 = math.radians(b_lat)
    term = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat_1) * math.cos(lat_2) * math.sin(d_lon / 2) ** 2
    )
    return radius_m * 2 * math.atan2(math.sqrt(term), math.sqrt(max(1 - term, 1e-9)))


def is_night_hour(hour: int) -> bool:
    return hour in {20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6}


def city_local_hour(city: str, timestamp: float | None = None) -> int:
    offset_minutes = CITY_UTC_OFFSETS_MINUTES.get(normalize_city(city), 0)
    city_timezone = timezone(timedelta(minutes=offset_minutes))
    instant = time.time() if timestamp is None else float(timestamp)
    return datetime.fromtimestamp(instant, tz=city_timezone).hour


def city_risk_time_bucket(city: str, timestamp: float | None = None) -> str:
    return "night" if is_night_hour(city_local_hour(city, timestamp)) else "day"


def flood_zone_label(city: str, lat: float, lon: float) -> str | None:
    for zone in FLOOD_ZONES.get(city, []):
        if haversine_meters(lat, lon, float(zone["lat"]), float(zone["lon"])) <= RISK_RADIUS_METERS:
            return str(zone["label"])
    return None


def road_label(data: dict[str, Any], fallback_city: str) -> str:
    if data.get("road_name"):
        return str(data["road_name"])
    flood_label = data.get("flood_zone_label")
    if flood_label:
        return str(flood_label)
    return f"{fallback_city.title()} {str(data.get('road_type', 'road')).replace('_', ' ')}"


def base_risk_profile(
    city: str,
    data: dict[str, Any],
    hour: int,
    *,
    score_override: float | None = None,
) -> dict[str, Any]:
    road_type = str(data.get("road_type", "unknown"))
    surface = str(data.get("surface_type", ""))
    score = float(score_override if score_override is not None else data.get("connectivity_score", 0.5))
    lat = float(data.get("mid_lat", 0.0))
    lon = float(data.get("mid_lon", 0.0))
    night = is_night_hour(hour)

    multiplier = 1.0
    risk_points = 0.0
    reasons: list[str] = []

    if score < 0.3:
        multiplier *= 3.0
        risk_points += 0.7
        reasons.append("connectivity dead zone")

    if road_type == "residential" and night:
        multiplier *= 2.0
        risk_points += 0.35
        reasons.append("residential night coverage drop")

    if city == "chennai" and night and (lat < 12.95 or lat > 13.15):
        multiplier *= 2.0
        risk_points += 0.35
        reasons.append("outer suburb night coverage risk")

    zone_label = flood_zone_label(city, lat, lon)
    if zone_label:
        multiplier *= 1.5
        risk_points += 0.25
        reasons.append(f"flood-prone near {zone_label}")

    if road_type == "construction" or surface == "unpaved":
        multiplier *= 1.8
        risk_points += 0.3
        reasons.append("construction or unpaved segment")

    risk_points = min(risk_points, 1.0)
    if risk_points >= 0.75 or score < 0.25:
        risk_level = "high"
    elif risk_points >= 0.35 or score < 0.45:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "multiplier": multiplier,
        "risk_points": risk_points,
        "risk_level": risk_level,
        "reasons": reasons,
        "flood_zone_label": zone_label,
    }


def array_backend(use_gpu: bool):
    return cp if use_gpu else np


def to_numpy_array(values):
    if USE_CUPY and cp is not None and isinstance(values, cp.ndarray):
        return cp.asnumpy(values)
    return np.asarray(values)


def haversine_meters_vectorized(xp, latitudes, longitudes, target_lat: float, target_lon: float):
    radius_m = 6_371_000.0
    latitudes_rad = latitudes * (math.pi / 180.0)
    target_lat_rad = float(target_lat) * (math.pi / 180.0)
    d_lat = (float(target_lat) - latitudes) * (math.pi / 180.0)
    d_lon = (float(target_lon) - longitudes) * (math.pi / 180.0)
    term = (
        xp.sin(d_lat / 2.0) ** 2
        + xp.cos(latitudes_rad) * math.cos(target_lat_rad) * xp.sin(d_lon / 2.0) ** 2
    )
    return radius_m * 2.0 * xp.arctan2(xp.sqrt(term), xp.sqrt(xp.maximum(1.0 - term, 1e-9)))


def fallback_edge_weight(edge_data: dict[str, Any]) -> float:
    return max(float(edge_data.get("length", 50.0)) / 30.0, 0.001)


def multiedge_weight_lookup(weights_cpu: np.ndarray):
    def weight(_: Any, __: Any, edge_data: dict[str, Any]) -> float:
        if "edge_index" in edge_data:
            edge_index = edge_data.get("edge_index")
            if isinstance(edge_index, int) and 0 <= edge_index < len(weights_cpu):
                return float(weights_cpu[edge_index])
            return fallback_edge_weight(edge_data)

        best_weight: float | None = None
        for attrs in edge_data.values():
            edge_index = attrs.get("edge_index")
            if isinstance(edge_index, int) and 0 <= edge_index < len(weights_cpu):
                candidate = float(weights_cpu[edge_index])
            else:
                candidate = fallback_edge_weight(attrs)
            if best_weight is None or candidate < best_weight:
                best_weight = candidate
        return best_weight if best_weight is not None else 1.0

    return weight


def shortest_path_nodes(graph, origin_node, destination_node, weights_cpu: np.ndarray):
    return nx.shortest_path(
        graph,
        origin_node,
        destination_node,
        weight=multiedge_weight_lookup(weights_cpu),
    )


def astar_path_nodes(graph, origin_node, destination_node, weights_cpu: np.ndarray):
    def heuristic(node_a: Any, node_b: Any) -> float:
        return haversine_meters(
            float(graph.nodes[node_a]["y"]),
            float(graph.nodes[node_a]["x"]),
            float(graph.nodes[node_b]["y"]),
            float(graph.nodes[node_b]["x"]),
        ) / 33.33

    return nx.astar_path(
        graph,
        origin_node,
        destination_node,
        heuristic=heuristic,
        weight=multiedge_weight_lookup(weights_cpu),
    )


def validate_path(graph, path_nodes: list[Any]) -> None:
    if len(path_nodes) < 2:
        raise ValueError("Path must contain at least two nodes")

    for node in path_nodes:
        if node not in graph.nodes:
            raise ValueError(f"Path references missing node {node}")

    for start, end in zip(path_nodes, path_nodes[1:]):
        if graph.get_edge_data(start, end) is None:
            raise ValueError(f"Path discontinuity between nodes {start} and {end}")


def compute_path_with_fallbacks(
    graph,
    origin_node: Any,
    destination_node: Any,
    weights_cpu: np.ndarray,
) -> list[Any]:
    path_attempts = [
        (
            "weighted dijkstra",
            lambda: shortest_path_nodes(graph, origin_node, destination_node, weights_cpu),
        ),
        (
            "reverse weighted dijkstra",
            lambda: list(reversed(shortest_path_nodes(graph, destination_node, origin_node, weights_cpu))),
        ),
        (
            "unweighted shortest path",
            lambda: nx.shortest_path(graph, origin_node, destination_node, weight=None),
        ),
        (
            "A* path",
            lambda: astar_path_nodes(graph, origin_node, destination_node, weights_cpu),
        ),
    ]

    last_error: Exception | None = None
    for label, resolver in path_attempts:
        try:
            path_nodes = resolver()
            validate_path(graph, path_nodes)
            if label != "weighted dijkstra":
                print(f"[routing] fallback pathfinder succeeded via {label}")
            return path_nodes
        except nx.NetworkXNoPath as exc:
            last_error = exc
            print(f"[routing] {label} failed: no path")
        except Exception as exc:
            last_error = exc
            print(f"[routing] {label} failed: {type(exc).__name__}: {exc}")

    print(f"[routing] No path found: {origin_node} -> {destination_node}")
    print(f"[routing] Graph nodes: {graph.number_of_nodes()}")
    print(f"[routing] Origin in graph: {origin_node in graph.nodes}")
    print(f"[routing] Dest in graph: {destination_node in graph.nodes}")
    if last_error is not None:
        print(f"[routing] Last routing error: {type(last_error).__name__}: {last_error}")
    raise HTTPException(
        status_code=422,
        detail=(
            "No route found. The selected points may be in disconnected areas. "
            "Try points closer to main roads."
        ),
    )


def precompute_vehicle_graph(
    city: str,
    base_graph,
    vehicle: str,
    scores_updated_at: float,
    *,
    hour: int | None = None,
) -> PreparedVehicleGraph:
    hour = city_local_hour(city) if hour is None else int(hour) % 24
    risk_time_bucket = "night" if is_night_hour(hour) else "day"
    profile = VEHICLE_PROFILES[vehicle]
    edge_rows = list(base_graph.edges(keys=True, data=True))

    if not edge_rows:
        return PreparedVehicleGraph(
            vehicle=vehicle,
            scores=to_device_array(np.zeros(0, dtype=np.float32)),
            risk_points=to_device_array(np.zeros(0, dtype=np.float32)),
            risk_multiplier=to_device_array(np.zeros(0, dtype=np.float32)),
            fastest_cost=to_device_array(np.zeros(0, dtype=np.float32)),
            balanced_cost=to_device_array(np.zeros(0, dtype=np.float32)),
            connected_cost=to_device_array(np.zeros(0, dtype=np.float32)),
            dead_zone_mask=to_bool_device_array(np.zeros(0, dtype=bool)),
            residential_night_mask=to_bool_device_array(np.zeros(0, dtype=bool)),
            chennai_outer_mask=to_bool_device_array(np.zeros(0, dtype=bool)),
            flood_mask=to_bool_device_array(np.zeros(0, dtype=bool)),
            highway_mask=to_bool_device_array(np.zeros(0, dtype=bool)),
            below_tolerance_mask=to_bool_device_array(np.zeros(0, dtype=bool)),
            stable_mask=to_bool_device_array(np.zeros(0, dtype=bool)),
            risk_time_bucket=risk_time_bucket,
            risk_hour=hour,
            computed_at=time.time(),
            source_scores_updated_at=scores_updated_at,
        )

    edge_count = len(edge_rows)
    lengths_np = np.asarray([float(data.get("length", 50.0)) for _, _, _, data in edge_rows], dtype=np.float32)
    travel_times_np = np.asarray(
        [edge_travel_time_seconds(data) for _, _, _, data in edge_rows],
        dtype=np.float32,
    )
    travel_norms = np.asarray([float(data.get("travel_time_norm", 0.0)) for _, _, _, data in edge_rows], dtype=np.float32)
    scores_np = np.clip(
        np.asarray([float(data.get("connectivity_score", 0.5)) for _, _, _, data in edge_rows], dtype=np.float32),
        0.0,
        1.0,
    )
    speed_kph_np = np.asarray([float(data.get("speed_kph", 25.0)) for _, _, _, data in edge_rows], dtype=np.float32)
    latitudes_np = np.asarray([float(data.get("mid_lat", 0.0)) for _, _, _, data in edge_rows], dtype=np.float32)
    longitudes_np = np.asarray([float(data.get("mid_lon", 0.0)) for _, _, _, data in edge_rows], dtype=np.float32)
    road_types = np.asarray([str(data.get("road_type", "unknown")) for _, _, _, data in edge_rows], dtype=object)
    surface_types = np.asarray([str(data.get("surface_type", "")) for _, _, _, data in edge_rows], dtype=object)

    highway_mask_np = np.isin(road_types, np.asarray(["motorway", "trunk"], dtype=object))
    residential_mask_np = road_types == "residential"
    construction_mask_np = road_types == "construction"
    unpaved_mask_np = surface_types == "unpaved"
    construction_or_unpaved_np = np.logical_or(construction_mask_np, unpaved_mask_np)

    flood_labels: dict[int, str] = {}

    def compute_cost_arrays(use_gpu: bool) -> dict[str, Any]:
        xp = array_backend(use_gpu)
        lengths = xp.asarray(lengths_np, dtype=xp.float32)
        travel_times = xp.asarray(travel_times_np, dtype=xp.float32)
        scores = xp.clip(xp.asarray(scores_np, dtype=xp.float32), 0.0, 1.0)
        speed_kph = xp.asarray(speed_kph_np, dtype=xp.float32)
        latitudes = xp.asarray(latitudes_np, dtype=xp.float32)
        longitudes = xp.asarray(longitudes_np, dtype=xp.float32)

        speed_mps = xp.maximum(speed_kph * (1000.0 / 3600.0), 1.0)
        time_cost = xp.where(travel_times > 0, travel_times, lengths / speed_mps).astype(xp.float32)

        base_multipliers = xp.ones(edge_count, dtype=xp.float32)
        risk_points = xp.zeros(edge_count, dtype=xp.float32)

        dead_zone_mask = scores < 0.3
        base_multipliers = base_multipliers * xp.where(dead_zone_mask, 3.0, 1.0)
        risk_points = xp.minimum(1.0, risk_points + xp.where(dead_zone_mask, 0.7, 0.0))

        if is_night_hour(hour):
            residential_night_mask = xp.asarray(residential_mask_np, dtype=xp.bool_)
            base_multipliers = base_multipliers * xp.where(residential_night_mask, 2.0, 1.0)
            risk_points = xp.minimum(1.0, risk_points + xp.where(residential_night_mask, 0.35, 0.0))
        else:
            residential_night_mask = xp.zeros(edge_count, dtype=xp.bool_)

        if city == "chennai" and is_night_hour(hour):
            chennai_outer_mask = (latitudes < 12.95) | (latitudes > 13.15)
            base_multipliers = base_multipliers * xp.where(chennai_outer_mask, 2.0, 1.0)
            risk_points = xp.minimum(1.0, risk_points + xp.where(chennai_outer_mask, 0.35, 0.0))
        else:
            chennai_outer_mask = xp.zeros(edge_count, dtype=xp.bool_)

        flood_mask = xp.zeros(edge_count, dtype=xp.bool_)
        for zone in FLOOD_ZONES.get(city, []):
            zone_mask = haversine_meters_vectorized(
                xp,
                latitudes,
                longitudes,
                float(zone["lat"]),
                float(zone["lon"]),
            ) <= RISK_RADIUS_METERS
            zone_hits = np.asarray(to_numpy_array(zone_mask), dtype=bool)
            for index, is_hit in enumerate(zone_hits.tolist()):
                if is_hit and index not in flood_labels:
                    flood_labels[index] = str(zone["label"])
            flood_mask = xp.logical_or(flood_mask, zone_mask)

        base_multipliers = base_multipliers * xp.where(flood_mask, 1.5, 1.0)
        risk_points = xp.minimum(1.0, risk_points + xp.where(flood_mask, 0.25, 0.0))

        construction_or_unpaved_mask = xp.asarray(construction_or_unpaved_np, dtype=xp.bool_)
        base_multipliers = base_multipliers * xp.where(construction_or_unpaved_mask, 1.8, 1.0)
        risk_points = xp.minimum(1.0, risk_points + xp.where(construction_or_unpaved_mask, 0.3, 0.0))

        vehicle_multiplier = xp.ones(edge_count, dtype=xp.float32)
        if profile.get("avoid_highways"):
            highway_mask = xp.asarray(highway_mask_np, dtype=xp.bool_)
            vehicle_multiplier = xp.where(highway_mask, vehicle_multiplier * 1.35, vehicle_multiplier)
            risk_points = xp.minimum(1.0, risk_points + xp.where(highway_mask, 0.15, 0.0))
        else:
            highway_mask = xp.zeros(edge_count, dtype=xp.bool_)

        dead_zone_deficit = xp.clip(float(profile["dead_zone_tolerance"]) - scores, 0.0, None)
        vehicle_multiplier = vehicle_multiplier * (1.0 + dead_zone_deficit * 2.5)
        risk_points = xp.minimum(1.0, risk_points + xp.minimum(0.4, dead_zone_deficit * 2.0))

        if profile.get("require_stable_v2x"):
            stable_mask = scores < 0.55
            vehicle_multiplier = xp.where(stable_mask, vehicle_multiplier * 1.6, vehicle_multiplier)
            risk_points = xp.minimum(1.0, risk_points + xp.where(stable_mask, 0.25, 0.0))
        else:
            stable_mask = xp.zeros(edge_count, dtype=xp.bool_)

        combined_multiplier = xp.maximum(base_multipliers * vehicle_multiplier, 1.0)
        composite_cost = (
            float(profile["speed"]) * time_cost
            + float(profile["connectivity"]) * (1.0 - scores) * time_cost
            + float(profile["risk"]) * combined_multiplier * time_cost
        ).astype(xp.float32)
        fastest_cost = xp.maximum(time_cost, 0.001).astype(xp.float32)
        balanced_cost = xp.maximum(composite_cost, 0.001).astype(xp.float32)
        connected_cost = xp.where(
            scores > 0.35,
            balanced_cost + (1.0 - scores) * time_cost * 0.75 + (combined_multiplier - 1.0) * time_cost,
            1e12,
        ).astype(xp.float32)

        return {
            "scores": scores,
            "risk_points": risk_points,
            "combined_multiplier": combined_multiplier,
            "fastest_cost": fastest_cost,
            "balanced_cost": balanced_cost,
            "connected_cost": connected_cost,
            "dead_zone_mask": dead_zone_mask,
            "residential_night_mask": residential_night_mask,
            "chennai_outer_mask": chennai_outer_mask,
            "flood_mask": flood_mask,
            "highway_mask": highway_mask,
            "below_tolerance_mask": dead_zone_deficit > 0,
            "stable_mask": stable_mask,
        }

    try:
        computed = compute_cost_arrays(USE_CUPY)
    except Exception as exc:
        if USE_CUPY:
            print(f"[routing] CuPy precompute failed for {city}/{vehicle}: {exc}; falling back to CPU")
            flood_labels = {}
            computed = compute_cost_arrays(False)
        else:
            raise

    return PreparedVehicleGraph(
        vehicle=vehicle,
        scores=computed["scores"],
        risk_points=computed["risk_points"],
        risk_multiplier=computed["combined_multiplier"],
        fastest_cost=computed["fastest_cost"],
        balanced_cost=computed["balanced_cost"],
        connected_cost=computed["connected_cost"],
        dead_zone_mask=computed["dead_zone_mask"],
        residential_night_mask=computed["residential_night_mask"],
        chennai_outer_mask=computed["chennai_outer_mask"],
        flood_mask=computed["flood_mask"],
        highway_mask=computed["highway_mask"],
        below_tolerance_mask=computed["below_tolerance_mask"],
        stable_mask=computed["stable_mask"],
        flood_labels=flood_labels,
        risk_time_bucket=risk_time_bucket,
        risk_hour=hour,
        computed_at=time.time(),
        source_scores_updated_at=scores_updated_at,
    )


def build_graph_state(city: str) -> GraphState:
    global ACTIVE_CITY

    city_slug = normalize_city(city)
    now = time.time()
    cached_state = GRAPH_CACHE.get(city_slug)
    if cached_state and cached_state.expires_at > now and cached_state.vehicle_graphs:
        ACTIVE_CITY = city_slug
        return cached_state

    with CITY_LOCKS[city_slug]:
        now = time.time()
        cached_state = GRAPH_CACHE.get(city_slug)
        if cached_state and cached_state.expires_at > now and cached_state.vehicle_graphs:
            ACTIVE_CITY = city_slug
            return cached_state

        graph = load_or_fetch_graph(city_slug)
        graph = annotate_base_graph(graph)
        scores, updated_at, edge_sources = safe_fetch_city_scores(city_slug)
        if scores:
            apply_scores_to_base_graph(graph, scores, edge_sources)

        node_index = build_node_index(graph)
        risk_hour = city_local_hour(city_slug)
        vehicle_graphs = {
            vehicle: precompute_vehicle_graph(
                city_slug,
                graph,
                vehicle,
                updated_at,
                hour=risk_hour,
            )
            for vehicle in VEHICLE_PROFILES
        }
        state = GraphState(
            city=city_slug,
            base_graph=graph,
            expires_at=now + CACHE_TTL_SECONDS,
            scores_updated_at=updated_at,
            edge_count=graph.number_of_edges(),
            node_index=node_index,
            vehicle_graphs=vehicle_graphs,
        )
        ACTIVE_CITY = city_slug
        GRAPH_CACHE[city_slug] = state
        if USE_CUPY:
            gpu_arrays_mb = sum(
                array_nbytes(prepared.scores)
                + array_nbytes(prepared.risk_points)
                + array_nbytes(prepared.risk_multiplier)
                + array_nbytes(prepared.fastest_cost)
                + array_nbytes(prepared.balanced_cost)
                + array_nbytes(prepared.connected_cost)
                for prepared in vehicle_graphs.values()
            ) / (1024 * 1024)
            print(f"[gpu] {city_slug} weights cached in VRAM: {gpu_arrays_mb:.1f}MB")
            log_vram_usage(city_slug)
        return state


def graph_is_ready(city: str) -> bool:
    city_slug = normalize_city(city)
    state = GRAPH_CACHE.get(city_slug)
    return bool(
        GRAPH_STATUS.get(city_slug) == "ready"
        and state is not None
        and state.expires_at > time.time()
        and state.vehicle_graphs
    )


def require_graph_state(city: str) -> GraphState:
    city_slug = normalize_city(city)
    state = GRAPH_CACHE.get(city_slug)

    if graph_is_ready(city_slug) and state is not None:
        return state

    status = GRAPH_STATUS.get(city_slug, "idle")
    if status == "loading":
        raise HTTPException(status_code=503, detail="Graph is still loading")
    if status == "error":
        raise HTTPException(status_code=503, detail=GRAPH_ERRORS.get(city_slug, "Graph unavailable"))
    raise HTTPException(status_code=503, detail="Graph not loaded")


def rebuild_vehicle_graphs(city: str, updated_at: float) -> None:
    state = GRAPH_CACHE.get(city)
    if state is None:
        return

    try:
        risk_hour = city_local_hour(city)
        new_graphs = {
            vehicle: precompute_vehicle_graph(
                city,
                state.base_graph,
                vehicle,
                updated_at,
                hour=risk_hour,
            )
            for vehicle in VEHICLE_PROFILES
        }
        with state.lock:
            state.vehicle_graphs = new_graphs
            state.scores_updated_at = updated_at
            state.score_refreshing = False
        print(f"[weights] refreshed precomputed weights for {city}")
    except Exception as exc:
        with state.lock:
            state.score_refreshing = False
        print(f"[weights] failed to recompute {city}: {exc}")


def ensure_current_risk_weights(state: GraphState) -> None:
    required_hour = city_local_hour(state.city)
    required_bucket = "night" if is_night_hour(required_hour) else "day"
    if state.vehicle_graphs and all(
        prepared.risk_time_bucket == required_bucket
        for prepared in state.vehicle_graphs.values()
    ):
        return

    with state.lock:
        if state.vehicle_graphs and all(
            prepared.risk_time_bucket == required_bucket
            for prepared in state.vehicle_graphs.values()
        ):
            return
        state.vehicle_graphs = {
            vehicle: precompute_vehicle_graph(
                state.city,
                state.base_graph,
                vehicle,
                state.scores_updated_at,
                hour=required_hour,
            )
            for vehicle in VEHICLE_PROFILES
        }
    print(f"[weights] refreshed {state.city} risk weights for {required_bucket}")


def refresh_scores_for_city(city: str) -> None:
    state = GRAPH_CACHE.get(city)
    if state is None or GRAPH_STATUS.get(city) != "ready":
        return

    scores, updated_at, edge_sources = safe_fetch_city_scores(city)
    if not scores:
        return
    if updated_at <= state.scores_updated_at and state.scores_updated_at > 0:
        return

    with state.lock:
        if state.score_refreshing:
            return
        apply_scores_to_base_graph(state.base_graph, scores, edge_sources)
        state.score_refreshing = True

    THREAD_POOL.submit(rebuild_vehicle_graphs, city, updated_at)


def score_refresh_loop() -> None:
    while not SCORE_REFRESH_STOP.is_set():
        for city in list(GRAPH_CACHE.keys()):
            refresh_scores_for_city(city)
        if SCORE_REFRESH_STOP.wait(SCORE_REFRESH_SECONDS):
            return


def request_data_service_preload(city: str) -> None:
    preload_request = request.Request(f"{data_service_url()}/preload/{city}", method="POST")
    try:
        with request.urlopen(preload_request, timeout=5):
            return
    except Exception as exc:
        print(f"[preload] data-service preload skipped for {city}: {exc}")


async def preload_city_graph(city: str) -> None:
    city_slug = normalize_city(city)
    GRAPH_STATUS[city_slug] = "loading"
    GRAPH_ERRORS.pop(city_slug, None)

    try:
        await asyncio.to_thread(request_data_service_preload, city_slug)
        await asyncio.to_thread(build_graph_state, city_slug)
        GRAPH_STATUS[city_slug] = "ready"
        print(f"[graph] {city_slug} ready")
    except Exception as exc:
        GRAPH_STATUS[city_slug] = "error"
        GRAPH_ERRORS[city_slug] = str(exc)
        print(f"[graph] {city_slug} failed to load: {exc}")


def validate_point(name: str, point: list[float]) -> tuple[float, float]:
    if len(point) != 2:
        raise HTTPException(status_code=422, detail=f"{name} must contain [lat, lon].")
    return float(point[0]), float(point[1])


def resolve_edge(graph, u: int, v: int, weights_cpu: np.ndarray):
    edges = graph.get_edge_data(u, v)
    if not edges:
        raise HTTPException(status_code=500, detail=f"Edge data missing between nodes {u} and {v}.")
    return min(
        edges.items(),
        key=lambda item: (
            float(weights_cpu[item[1]["edge_index"]])
            if isinstance(item[1].get("edge_index"), int) and item[1]["edge_index"] < len(weights_cpu)
            else fallback_edge_weight(item[1])
        ),
    )


def serialize_node(node: Any) -> Any:
    try:
        return int(node)
    except (TypeError, ValueError):
        return node


def format_percent(value: float) -> str:
    return f"{round(value * 100):.0f}%"


def build_explanation(
    city: str,
    mode: str,
    vehicle: str,
    edges: list[dict[str, Any]],
    avg_connectivity: float,
) -> dict[str, Any]:
    total_length = sum(float(edge["length"]) for edge in edges) or 1.0
    high_connect_length = sum(float(edge["length"]) for edge in edges if float(edge["score"]) >= 0.7)
    dead_zone_length = sum(float(edge["length"]) for edge in edges if float(edge["score"]) < 0.3)
    major_road_length = sum(
        float(edge["length"])
        for edge in edges
        if edge["road_type"] in {"motorway", "trunk", "primary", "secondary"}
    )
    dead_zone_count = sum(1 for edge in edges if float(edge["score"]) < 0.3)
    high_connect_pct = high_connect_length / total_length
    dead_zone_pct = dead_zone_length / total_length
    major_road_pct = major_road_length / total_length
    avg_risk = sum(float(edge["risk_points"]) for edge in edges) / max(len(edges), 1)
    avg_speed_norm = sum(float(edge["travel_time_norm"]) for edge in edges) / max(len(edges), 1)

    tier_counts = Counter(
        "good" if edge["score"] >= 0.7 else "medium" if edge["score"] >= 0.3 else "dead"
        for edge in edges
    )
    riskiest_segments = sorted(
        edges,
        key=lambda edge: (float(edge["risk_points"]), float(edge["length"])),
        reverse=True,
    )[:3]

    if dead_zone_count and riskiest_segments:
        primary_risk_label = road_label(riskiest_segments[0], city)
        dead_zone_summary = f"and crosses {dead_zone_count} dead-zone segment(s) near {primary_risk_label}."
    else:
        dead_zone_summary = "and avoids known dead zones."

    summary = (
        f"Optimized for {vehicle}: {VEHICLE_PROFILES[vehicle]['summary']}. "
        f"This route uses {format_percent(high_connect_pct)} high-connectivity roads "
        f"{dead_zone_summary}"
    )

    dominant_road_type = max(
        (edge["road_type"] for edge in edges),
        key=lambda road_type: sum(float(edge["length"]) for edge in edges if edge["road_type"] == road_type),
        default="mixed roads",
    )

    factors = [
        {
            "factor": "Signal Coverage",
            "impact": "positive" if high_connect_pct >= 0.6 else "negative",
            "detail": f"{format_percent(high_connect_pct)} of route has strong signal",
        },
        {
            "factor": "Dead Zones",
            "impact": "negative" if dead_zone_count else "positive",
            "detail": (
                f"{format_percent(dead_zone_pct)} of route passes through dead zones"
                if dead_zone_count
                else "Route avoids major dead zones"
            ),
        },
        {
            "factor": "Road Type",
            "impact": "positive" if major_road_pct >= 0.5 else "negative",
            "detail": f"Primarily uses {dominant_road_type.replace('_', ' ')} roads",
        },
    ]

    return {
        "summary": summary,
        "factors": factors,
        "score_breakdown": {
            "connectivity": round(max(0.0, min(1.0, avg_connectivity)), 2),
            "speed": round(max(0.0, min(1.0, 1.0 - avg_speed_norm)), 2),
            "risk": round(max(0.0, min(1.0, 1.0 - avg_risk)), 2),
        },
        "tiers": dict(tier_counts),
        "riskiest_segments": [
            {
                "name": road_label(edge, city),
                "risk": edge["risk_level"],
                "detail": ", ".join(edge["risk_reasons"]) or "stable segment",
            }
            for edge in riskiest_segments
        ],
    }


def risk_level_for_values(score: float, risk_points: float) -> str:
    if risk_points >= 0.75 or score < 0.25:
        return "high"
    if risk_points >= 0.35 or score < 0.45:
        return "medium"
    return "low"


def corridor_bbox(
    origin: tuple[float, float],
    destination: tuple[float, float],
    padding_km: float | None = None,
) -> tuple[float, float, float, float]:
    if padding_km is None:
        padding_km = get_corridor_padding(origin, destination)
    pad = padding_km / 111.0
    min_lat = min(origin[0], destination[0]) - pad
    max_lat = max(origin[0], destination[0]) + pad
    min_lon = min(origin[1], destination[1]) - pad
    max_lon = max(origin[1], destination[1]) + pad
    return min_lat, min_lon, max_lat, max_lon


def get_corridor_padding(origin: tuple[float, float], destination: tuple[float, float]) -> float:
    dlat = abs(destination[0] - origin[0]) * 111.0
    dlon = abs(destination[1] - origin[1]) * 111.0
    route_km = math.sqrt(dlat**2 + dlon**2)
    if route_km < 5.0:
        return 1.5
    if route_km < 15.0:
        return 3.0
    if route_km < 30.0:
        return 5.0
    return 8.0


def corridor_edge_inputs(
    graph,
    origin: tuple[float, float],
    destination: tuple[float, float],
    padding_km: float | None = None,
) -> tuple[dict[str, list[float]], dict[int, dict[str, Any]]]:
    min_lat, min_lon, max_lat, max_lon = corridor_bbox(origin, destination, padding_km)
    edge_coords: dict[str, list[float]] = {}
    edge_lookup: dict[int, dict[str, Any]] = {}

    for _, _, _, data in graph.edges(keys=True, data=True):
        lat = float(data.get("mid_lat", 0.0))
        lon = float(data.get("mid_lon", 0.0))
        if lat < min_lat or lat > max_lat or lon < min_lon or lon > max_lon:
            continue

        segment_id = str(data.get("segment_id") or "")
        edge_index = data.get("edge_index")
        if not segment_id or not isinstance(edge_index, int) or edge_index < 0:
            continue

        edge_coords[segment_id] = [lat, lon]
        edge_lookup[edge_index] = data

    return edge_coords, edge_lookup


def fetch_corridor_scores(
    origin: tuple[float, float],
    destination: tuple[float, float],
    edge_coords: dict[str, list[float]],
) -> tuple[dict[str, float], str, int, float, float, dict[str, str]]:
    if not edge_coords:
        return {}, PROVENANCE_ML_SYNTHETIC, 0, 0.0, 0.0, {}

    padding_km = get_corridor_padding(origin, destination)
    corridor_request = request.Request(
        f"{data_service_url()}/corridor-scores",
        data=json.dumps(
            {
                "origin": [origin[0], origin[1]],
                "destination": [destination[0], destination[1]],
                "edge_coords": edge_coords,
                "padding_km": padding_km,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(corridor_request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"[routing] corridor score fetch failed, using ML estimate: {exc}")
        return (
            {},
            PROVENANCE_ML_SYNTHETIC,
            0,
            0.0,
            0.0,
            {segment_id: PROVENANCE_ML_SYNTHETIC for segment_id in edge_coords},
        )

    raw_scores = payload.get("scores", {})
    if not isinstance(raw_scores, dict):
        raw_scores = {}
    scores: dict[str, float] = {}
    for segment_id, score in raw_scores.items():
        segment_key = str(segment_id)
        if segment_key not in edge_coords:
            continue
        try:
            scores[segment_key] = max(0.0, min(1.0, float(score)))
        except (TypeError, ValueError):
            continue

    source = canonical_provenance(payload.get("provenance_source") or payload.get("source"))
    real_data_source = canonical_provenance(payload.get("real_data_source"))
    raw_edge_sources = payload.get("edge_sources", {})
    if not isinstance(raw_edge_sources, dict):
        raw_edge_sources = {}
    edge_sources: dict[str, str] = {}
    for segment_id in edge_coords:
        if segment_id not in scores:
            edge_sources[segment_id] = PROVENANCE_ML_SYNTHETIC
            continue
        explicit_source = canonical_provenance(raw_edge_sources.get(segment_id))
        if explicit_source != PROVENANCE_UNKNOWN:
            edge_sources[segment_id] = explicit_source
        elif source in {PROVENANCE_OPENCELLID, PROVENANCE_TRAI, PROVENANCE_ML_SYNTHETIC}:
            edge_sources[segment_id] = source
        elif real_data_source in {PROVENANCE_OPENCELLID, PROVENANCE_TRAI}:
            edge_sources[segment_id] = real_data_source
        else:
            edge_sources[segment_id] = PROVENANCE_UNKNOWN

    scores = {
        segment_id: score
        for segment_id, score in scores.items()
        if edge_sources.get(segment_id) != PROVENANCE_ML_SYNTHETIC
    }

    return (
        scores,
        source,
        int(payload.get("tower_count") or 0),
        first_payload_percentage(
            payload,
            "real_data_coverage_percent",
            "coverage_percent",
            "real_data_percent",
        ),
        first_payload_percentage(payload, "good_signal_percent"),
        edge_sources,
    )


def push_corridor_scores_to_tiles(
    city: str,
    route_scores: dict[str, float],
    edge_sources: dict[str, str],
) -> None:
    if not route_scores:
        return
    feedback_request = request.Request(
        f"{data_service_url()}/corridor-feedback/{city}",
        data=json.dumps(
            {"scores": route_scores, "edge_sources": edge_sources}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(feedback_request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        print(
            f"[tiles] applied corridor real-score feedback "
            f"({int(payload.get('updated_edges') or 0)} edges)"
        )
    except Exception as exc:
        print(f"[tiles] corridor feedback skipped for {city}: {exc}")


def edge_time_cost(data: dict[str, Any]) -> float:
    return edge_travel_time_seconds(data)


def compute_scalar_route_cost(
    city: str,
    data: dict[str, Any],
    mode: str,
    vehicle: str,
    score: float,
    *,
    hour: int | None = None,
) -> tuple[float, dict[str, Any]]:
    profile = VEHICLE_PROFILES[vehicle]
    current_hour = city_local_hour(city) if hour is None else hour
    risk_profile = base_risk_profile(city, data, current_hour, score_override=score)
    time_cost = edge_time_cost(data)

    vehicle_multiplier = 1.0
    reasons = list(risk_profile["reasons"])

    if profile.get("avoid_highways") and str(data.get("road_type", "unknown")) in {"motorway", "trunk"}:
        vehicle_multiplier *= 1.35
        reasons.append("vehicle profile avoids highways")

    dead_zone_deficit = max(float(profile["dead_zone_tolerance"]) - score, 0.0)
    if dead_zone_deficit > 0:
        vehicle_multiplier *= 1.0 + dead_zone_deficit * 2.5
        reasons.append("below vehicle dead-zone tolerance")

    stable_penalty = False
    if profile.get("require_stable_v2x") and score < 0.55:
        vehicle_multiplier *= 1.6
        stable_penalty = True
        reasons.append("truck profile requires stable V2X")

    combined_multiplier = max(float(risk_profile["multiplier"]) * vehicle_multiplier, 1.0)
    score_penalty = (1.0 - score) * time_cost
    composite_cost = (
        float(profile["speed"]) * time_cost
        + float(profile["connectivity"]) * score_penalty
        + float(profile["risk"]) * combined_multiplier * time_cost
    )

    if mode == "fastest":
        cost = time_cost
    elif mode == "connected":
        cost = (
            composite_cost
            + score_penalty * 0.75
            + max(combined_multiplier - 1.0, 0.0) * time_cost
            if score > 0.35
            else 1e12
        )
    else:
        cost = composite_cost

    risk_points = float(risk_profile["risk_points"])
    if str(data.get("road_type", "")) in {"motorway", "trunk"} and profile.get("avoid_highways"):
        risk_points = min(1.0, risk_points + 0.15)
    if dead_zone_deficit > 0:
        risk_points = min(1.0, risk_points + min(0.4, dead_zone_deficit * 2.0))
    if stable_penalty:
        risk_points = min(1.0, risk_points + 0.25)

    return float(max(cost, 0.001)), {
        "score": float(max(0.0, min(1.0, score))),
        "risk_points": risk_points,
        "risk_level": risk_level_for_values(score, risk_points),
        "reasons": reasons,
        "flood_zone_label": risk_profile["flood_zone_label"],
        "combined_multiplier": combined_multiplier,
    }


def compute_route(city: str, origin: tuple[float, float], destination: tuple[float, float], mode: str, vehicle: str) -> dict[str, Any]:
    city_slug = normalize_city(city)
    state = require_graph_state(city_slug)
    ensure_current_risk_weights(state)

    prepared = state.vehicle_graphs.get(vehicle)
    if prepared is None:
        raise HTTPException(status_code=503, detail="Vehicle graph unavailable")

    cached_response = get_cached_route(
        city_slug,
        origin,
        destination,
        mode,
        vehicle,
        max(state.scores_updated_at, prepared.source_scores_updated_at),
        prepared.risk_time_bucket,
    )
    if cached_response is not None:
        return cached_response

    graph = state.base_graph
    weight_array = weight_array_for_mode(prepared, mode)
    weights_cpu = to_numpy_array(weight_array).astype(np.float32, copy=False)
    missing_weights = sum(
        1
        for _, _, _, data in graph.edges(keys=True, data=True)
        if "composite_cost" not in data
    )
    if missing_weights > 0:
        print(f"[routing] WARNING: {missing_weights} edges missing composite_cost")
        for _, _, _, data in graph.edges(keys=True, data=True):
            if "composite_cost" not in data:
                data["composite_cost"] = fallback_edge_weight(data)

    corridor_edge_coords, corridor_edge_lookup = corridor_edge_inputs(graph, origin, destination)
    (
        corridor_scores,
        signal_source,
        tower_count,
        corridor_real_data_coverage,
        corridor_good_signal_percent,
        corridor_edge_sources,
    ) = fetch_corridor_scores(
        origin,
        destination,
        corridor_edge_coords,
    )
    corridor_risk_details: dict[int, dict[str, Any]] = {}
    if corridor_scores:
        weights_cpu = np.array(weights_cpu, dtype=np.float32, copy=True)
        current_hour = prepared.risk_hour
        for edge_index, data in corridor_edge_lookup.items():
            segment_id = str(data.get("segment_id") or "")
            if not segment_id:
                continue
            score = corridor_scores.get(segment_id)
            if score is None:
                continue
            updated_weight, risk_details = compute_scalar_route_cost(
                city_slug,
                data,
                mode,
                vehicle,
                float(score),
                hour=current_hour,
            )
            weights_cpu[edge_index] = np.float32(updated_weight)
            corridor_risk_details[edge_index] = risk_details
        print(
            f"[routing] applied corridor scores for {len(corridor_risk_details)} edges "
            f"from {signal_source} ({tower_count} towers)"
        )
    else:
        signal_source = PROVENANCE_ML_SYNTHETIC

    origin_node = find_nearest_node(graph, origin[0], origin[1], state.node_index)
    destination_node = find_nearest_node(graph, destination[0], destination[1], state.node_index)

    try:
        path_nodes = compute_path_with_fallbacks(graph, origin_node, destination_node, weights_cpu)
        validate_path(graph, path_nodes)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        print(f"[routing] Pathfinding error: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    coordinates: list[tuple[float, float]] = []
    route_points: list[dict[str, Any]] = []
    signal_segments: list[dict[str, Any]] = []
    edge_snapshots: list[dict[str, Any]] = []
    path_edges: list[tuple[int, int, dict[str, Any]]] = []
    edge_indexes: list[int] = []

    for u, v in zip(path_nodes, path_nodes[1:]):
        _, data = resolve_edge(graph, u, v, weights_cpu)
        edge_index = int(data.get("edge_index", -1))
        if edge_index < 0:
            raise HTTPException(status_code=500, detail=f"Edge index missing between nodes {u} and {v}")
        edge_indexes.append(edge_index)
        path_edges.append((u, v, data))

    edge_index_array = np.asarray(edge_indexes, dtype=np.int32)
    edge_scores = extract_array(prepared.scores, edge_index_array).astype(np.float32, copy=False)
    edge_risk_points = extract_array(prepared.risk_points, edge_index_array).astype(np.float32, copy=False)
    dead_zone_mask = extract_array(prepared.dead_zone_mask, edge_index_array).astype(bool, copy=False)
    residential_night_mask = extract_array(prepared.residential_night_mask, edge_index_array).astype(bool, copy=False)
    chennai_outer_mask = extract_array(prepared.chennai_outer_mask, edge_index_array).astype(bool, copy=False)
    flood_mask = extract_array(prepared.flood_mask, edge_index_array).astype(bool, copy=False)
    highway_mask = extract_array(prepared.highway_mask, edge_index_array).astype(bool, copy=False)
    below_tolerance_mask = extract_array(prepared.below_tolerance_mask, edge_index_array).astype(bool, copy=False)
    stable_mask = extract_array(prepared.stable_mask, edge_index_array).astype(bool, copy=False)

    edge_times: list[float] = []
    route_scores: list[float] = []
    route_provenance: list[str] = []
    route_real_data: list[bool] = []
    route_score_payload: dict[str, float] = {}
    route_score_sources: dict[str, str] = {}

    for index, (u, v, data) in enumerate(path_edges):
        geometry = edge_geometry(graph, u, v, data)
        coords = orient_coordinates(
            list(geometry.coords),
            (float(graph.nodes[u]["x"]), float(graph.nodes[u]["y"])),
        )

        if coordinates:
            oriented_coords = coords[1:] if coordinates[-1] == coords[0] else coords
            coordinates.extend(oriented_coords)
        else:
            oriented_coords = coords
            coordinates.extend(coords)

        edge_index = edge_indexes[index]
        override_details = corridor_risk_details.get(edge_index)
        score = float(override_details["score"]) if override_details else float(edge_scores[index])
        risk_points = (
            float(override_details["risk_points"])
            if override_details
            else float(edge_risk_points[index])
        )
        risk_level = (
            str(override_details["risk_level"])
            if override_details
            else risk_level_for_values(score, risk_points)
        )
        route_scores.append(score)
        segment_id = str(data.get("segment_id") or "")
        base_provenance_source = canonical_provenance(
            data.get("provenance_source", PROVENANCE_ML_SYNTHETIC)
        )
        is_real_override = bool(segment_id and segment_id in corridor_scores)
        provenance_source = (
            canonical_provenance(
                corridor_edge_sources.get(segment_id, PROVENANCE_UNKNOWN)
            )
            if is_real_override
            else base_provenance_source
        )
        route_provenance.append(provenance_source)
        route_real_data.append(
            is_real_override or base_provenance_source != PROVENANCE_ML_SYNTHETIC
        )
        if is_real_override:
            route_score_payload[segment_id] = round(score, 3)
            route_score_sources[segment_id] = provenance_source
        for lon, lat in oriented_coords:
            route_points.append({"lat": lat, "lon": lon, "risk": risk_level})
        signal_segments.append(
            {
                "segment_id": segment_id,
                "coordinates": [[lat, lon] for lon, lat in oriented_coords],
                "score": round(score, 3),
                "risk": risk_level,
                "provenance_source": provenance_source,
            }
        )

        edge_times.append(edge_time_cost(data))
        if override_details:
            reasons = list(dict.fromkeys(str(reason) for reason in override_details["reasons"]))
            flood_label = override_details.get("flood_zone_label")
        else:
            reasons = []
            if bool(dead_zone_mask[index]):
                reasons.append("connectivity dead zone")
            if bool(residential_night_mask[index]):
                reasons.append("residential night coverage drop")
            if bool(chennai_outer_mask[index]):
                reasons.append("outer suburb night coverage risk")
            flood_label = prepared.flood_labels.get(int(edge_indexes[index]))
            if bool(flood_mask[index]) and flood_label:
                reasons.append(f"flood-prone near {flood_label}")
            if str(data.get("road_type", "")) == "construction" or str(data.get("surface_type", "")) == "unpaved":
                reasons.append("construction or unpaved segment")
            if bool(highway_mask[index]):
                reasons.append("vehicle profile avoids highways")
            if bool(below_tolerance_mask[index]):
                reasons.append("below vehicle dead-zone tolerance")
            if bool(stable_mask[index]):
                reasons.append("truck profile requires stable V2X")
        edge_snapshots.append(
            {
                "segment_id": data.get("segment_id"),
                "name": data.get("road_name"),
                "road_type": data.get("road_type"),
                "surface_type": data.get("surface_type"),
                "length": float(data.get("length", 1.0)),
                "score": score,
                "travel_time": edge_time_cost(data),
                "travel_time_norm": float(data.get("travel_time_norm", 0.0)),
                "risk_level": risk_level,
                "risk_points": risk_points,
                "risk_reasons": reasons,
                "flood_zone_label": flood_label,
                "road_name": data.get("road_name"),
            }
        )

    total_time_minutes = round(sum(edge_times) / 60.0, 1) if edge_times else 0.0
    avg_connectivity = round(float(np.mean(route_scores)), 3) if route_scores else 0.0
    route_signal_percent = round(avg_connectivity * 100.0, 1)
    good_signal_percent = round(
        (sum(1 for score in route_scores if score >= 0.6) / max(len(route_scores), 1)) * 100.0,
        1,
    ) if route_scores else 0.0
    real_sources = {PROVENANCE_OPENCELLID, PROVENANCE_TRAI}
    real_edge_count = sum(1 for is_real in route_real_data if is_real)
    real_data_coverage_percent = round(
        (real_edge_count / max(len(route_provenance), 1)) * 100.0,
        1,
    ) if route_provenance else 0.0
    route_source_set = set(route_provenance)
    if not route_source_set:
        signal_source = PROVENANCE_UNKNOWN
    elif 0 < real_edge_count < len(route_real_data):
        signal_source = PROVENANCE_HYBRID
    elif real_edge_count == len(route_real_data):
        known_real_sources = route_source_set & real_sources
        signal_source = (
            next(iter(known_real_sources))
            if len(known_real_sources) == 1
            and route_source_set <= (known_real_sources | {PROVENANCE_UNKNOWN})
            and PROVENANCE_UNKNOWN not in route_source_set
            else PROVENANCE_UNKNOWN
        )
    elif route_source_set == {PROVENANCE_ML_SYNTHETIC}:
        signal_source = PROVENANCE_ML_SYNTHETIC
    else:
        signal_source = PROVENANCE_UNKNOWN
    if len(path_nodes) < 2 or len(coordinates) < 2:
        print(
            f"[routing] invalid route result: nodes={len(path_nodes)} coordinates={len(coordinates)} "
            f"origin={origin_node} destination={destination_node}"
        )
        raise HTTPException(
            status_code=422,
            detail=(
                "No route found. The selected points may be in disconnected areas. "
                "Try points closer to main roads."
            ),
        )
    explanation = build_explanation(city_slug, mode, vehicle, edge_snapshots, avg_connectivity)
    if route_score_payload:
        push_corridor_scores_to_tiles(
            city_slug,
            route_score_payload,
            route_score_sources,
        )

    response = {
        "mode": mode,
        "vehicle": vehicle,
        "nodes": [serialize_node(node) for node in path_nodes],
        "path_geojson": {
            "type": "LineString",
            "coordinates": coordinates,
        },
        "segments": route_points,
        "signal_segments": signal_segments,
        "total_time_min": total_time_minutes,
        "avg_connectivity": avg_connectivity,
        "route_signal_percent": route_signal_percent,
        "signal_source": signal_source,
        "provenance_source": signal_source,
        "tower_count": tower_count,
        "real_data_coverage_percent": real_data_coverage_percent,
        "coverage_percent": real_data_coverage_percent,
        "real_data_percent": real_data_coverage_percent,
        "good_signal_percent": good_signal_percent,
        "edge_sources": {
            segment["segment_id"]: segment["provenance_source"]
            for segment in signal_segments
            if segment["segment_id"]
        },
        "corridor_real_data_coverage_percent": corridor_real_data_coverage,
        "corridor_good_signal_percent": corridor_good_signal_percent,
        "explanation": explanation,
    }
    store_cached_route(
        city_slug,
        origin,
        destination,
        mode,
        vehicle,
        max(state.scores_updated_at, prepared.source_scores_updated_at),
        response,
        prepared.risk_time_bucket,
    )
    return response


async def compute_all_routes(
    city: str,
    origin: tuple[float, float],
    destination: tuple[float, float],
    vehicle: str,
) -> list[dict[str, Any]]:
    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(THREAD_POOL, compute_route, city, origin, destination, strategy, vehicle)
        for strategy in STRATEGY_ORDER
    ]
    return await asyncio.gather(*tasks)


def schedule_preload(city: str) -> str:
    city_slug = normalize_city(city)
    if graph_is_ready(city_slug):
        return "ready"

    current_task = PRELOAD_TASKS.get(city_slug)
    if current_task is not None and not current_task.done():
        return "already loading"

    GRAPH_STATUS[city_slug] = "loading"
    PRELOAD_TASKS[city_slug] = asyncio.create_task(preload_city_graph(city_slug))
    return "loading"


@app.on_event("startup")
async def startup_event() -> None:
    global SCORE_REFRESH_THREAD

    detect_system_gpu()
    validate_cupy_runtime()
    configure_cpu_affinity()
    load_route_cache()
    APP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    GRAPH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for city in supported_cities():
        GRAPH_STATUS[city] = "idle"
    default_city_slug = default_city()
    log_memory_limit("routing-engine")
    schedule_preload(default_city_slug)

    if SCORE_REFRESH_THREAD is None or not SCORE_REFRESH_THREAD.is_alive():
        SCORE_REFRESH_STOP.clear()
        SCORE_REFRESH_THREAD = Thread(target=score_refresh_loop, daemon=True)
        SCORE_REFRESH_THREAD.start()


@app.on_event("shutdown")
def shutdown_event() -> None:
    SCORE_REFRESH_STOP.set()
    persist_route_cache()
    THREAD_POOL.shutdown(wait=False, cancel_futures=True)


@app.post("/route")
async def route(request_model: RouteRequest):
    try:
        city_slug = normalize_city(request_model.city)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    origin = validate_point("origin", request_model.origin)
    destination = validate_point("destination", request_model.destination)
    status = GRAPH_STATUS.get(city_slug, "idle")
    if status not in {"loading", "error"} and not graph_is_ready(city_slug):
        schedule_preload(city_slug)
        status = GRAPH_STATUS.get(city_slug, "loading")
    if status == "loading":
        return JSONResponse(
            status_code=202,
            headers={"Retry-After": "5"},
            content={
                "status": "loading",
                "city": city_slug,
                "message": "Graph is loading",
                "retry_after": 5,
            },
        )
    if status == "error":
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "code": "graph_unavailable",
                "message": GRAPH_ERRORS.get(city_slug, "Graph unavailable"),
            },
        )

    try:
        return compute_route(city_slug, origin, destination, request_model.mode, request_model.vehicle)
    finally:
        gc.collect()
        free_gpu_memory()


@app.post("/preload/{city}")
async def preload(city: str) -> dict[str, Any]:
    city_slug = normalize_city(city)
    preload_status = schedule_preload(city_slug)
    return {"status": preload_status, "city": city_slug}


@app.get("/test-route/{city}")
async def test_route(city: str) -> dict[str, Any]:
    city_slug = normalize_city(city)
    origin, destination = TEST_ROUTE_COORDS.get(
        city_slug,
        TEST_ROUTE_COORDS["bangalore"],
    )
    if GRAPH_STATUS.get(city_slug, "idle") != "ready":
        return {
            "status": "error",
            "message": "Graph not loaded",
            "city": city_slug,
        }
    try:
        return compute_route(city_slug, origin, destination, "balanced", "car")
    except HTTPException as exc:
        return {
            "status": "error",
            "city": city_slug,
            "detail": exc.detail,
        }
    finally:
        gc.collect()
        free_gpu_memory()


@app.get("/memory")
def memory() -> dict[str, Any]:
    state = GRAPH_CACHE.get(ACTIVE_CITY) if ACTIVE_CITY else None
    gpu_arrays_mb = 0.0
    if state is not None:
        for prepared in state.vehicle_graphs.values():
            gpu_arrays_mb += (
                array_nbytes(prepared.scores)
                + array_nbytes(prepared.risk_points)
                + array_nbytes(prepared.risk_multiplier)
                + array_nbytes(prepared.fastest_cost)
                + array_nbytes(prepared.balanced_cost)
                + array_nbytes(prepared.connected_cost)
                + array_nbytes(prepared.dead_zone_mask)
                + array_nbytes(prepared.residential_night_mask)
                + array_nbytes(prepared.chennai_outer_mask)
                + array_nbytes(prepared.flood_mask)
                + array_nbytes(prepared.highway_mask)
                + array_nbytes(prepared.below_tolerance_mask)
                + array_nbytes(prepared.stable_mask)
            )
        if state.node_index is not None:
            gpu_arrays_mb += (
                array_nbytes(state.node_index.get("ids_gpu"))
                + array_nbytes(state.node_index.get("lats_gpu"))
                + array_nbytes(state.node_index.get("lons_gpu"))
            )
    return {
        "ram_mb": round(process_memory_mb(), 1),
        "vram_mb": round(current_vram_mb(), 1),
        "graph_loaded": ACTIVE_CITY,
        "tile_cache_size": 0,
        "gpu_arrays_mb": round(gpu_arrays_mb / (1024 * 1024), 1),
        "max_ram_mb": MAX_RAM_MB,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    city_slug = default_city()
    return {
        "status": "ok",
        "cached_cities": list(GRAPH_CACHE.keys()),
        "graph_status": GRAPH_STATUS,
        "gpu_enabled": USE_CUPY,
        "gpu_name": GPU_NAME,
        "active_city": ACTIVE_CITY,
        "graph_ready": graph_is_ready(city_slug),
    }


@app.get("/ready")
def ready() -> JSONResponse:
    city_slug = default_city()
    graph_ready = graph_is_ready(city_slug)
    return JSONResponse(
        status_code=200 if graph_ready else 503,
        content={
            "status": "ready" if graph_ready else "not_ready",
            "service": "routing-engine",
            "city": city_slug,
            "graph_ready": graph_ready,
            "graph_status": GRAPH_STATUS.get(city_slug, "idle"),
        },
    )
