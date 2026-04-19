from __future__ import annotations

import ast
import csv
import gc
import json
import math
import os
import pickle
import sqlite3
import subprocess
import sys
import threading
import time
import zlib
from collections import OrderedDict, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error, request

import httpx
import mapbox_vector_tile
import mercantile
import numpy as np
import osmnx as ox
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from pyproj import Transformer
from shapely import wkt
from shapely.geometry import LineString, MultiLineString, box, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

SERVICE_DIR = Path(__file__).resolve().parent
REPO_ROOT = SERVICE_DIR.parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from api_key_manager import APIKeyManager
from tile_loader import (
    cache_status as persistent_cache_status,
    cached_towers_for_bbox,
    ensure_city_tiles,
    fetch_bbox_towers_live,
    local_tower_source_status,
    load_local_tower_source,
    tile_bounds as cached_tile_bounds,
)
from tower_ingestion_worker import TowerIngestionWorker

try:
    import cuspatial
    import cudf

    USE_CUSPATIAL = True
    print("[tiles] cuSpatial GPU spatial indexing enabled")
except ImportError:
    cuspatial = None
    cudf = None
    USE_CUSPATIAL = False
    print("[tiles] cuSpatial not available, using CPU spatial index")

try:
    import cupy as cp

    USE_CUPY = True
    print("[tiles] CuPy GPU arrays enabled")
except ImportError:
    cp = None
    USE_CUPY = False
    print("[tiles] CuPy not available, using CPU score arrays")

app = FastAPI(title="Connectivity-Aware Data Service", version="0.3.0")

CACHE_TTL_SECONDS = 24 * 60 * 60
PREDICTION_REFRESH_SECONDS = 30 * 60
DEFAULT_SUPPORTED_CITIES = "bangalore"
DEFAULT_DEFAULT_CITY = "bangalore"
DEFAULT_PREDICTION_SERVICE_URL = "http://prediction-service:8003"
DEFAULT_BANGALORE_QUERY = "Bangalore, Karnataka, India"
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api"
DEFAULT_OVERPASS_FALLBACK_URLS = "https://overpass.private.coffee/api"
HOTSPOT_CACHE_TTL_SECONDS = 2 * 60
HOTSPOT_CACHE_MAX_ENTRIES = 500
MIN_TILE_ZOOM = 10
MAX_TILE_ZOOM = 16
MVT_LAYER_NAME = "roads"
MVT_MEDIA_TYPE = "application/vnd.mapbox-vector-tile"
ROAD_FALLBACK_SCORE = 0.05
OPENCELLID_TOKEN = os.getenv("OPENCELLID_TOKEN", "pk.37dddd741049308fd26c175be7a5aea0")
OPENCELLID_MAX_BBOX_AREA_M2 = 4_000_000.0
OPENCELLID_CHUNK_SIDE_KM = 1.8
CORRIDOR_CACHE_TTL = 600
DATA_DIR = SERVICE_DIR / "data"
APP_CACHE_DIR = Path(os.getenv("APP_CACHE_DIR", str(SERVICE_DIR / "cache")))
GRAPH_CACHE_DIR = Path(os.getenv("GRAPH_CACHE_DIR", str(APP_CACHE_DIR / "graphs")))
HOTSPOT_CACHE_PATH = Path(os.getenv("HOTSPOT_CACHE_PATH", str(APP_CACHE_DIR / "hotspots.json")))
OSMNX_HTTP_CACHE_DIR = Path(os.getenv("OSMNX_HTTP_CACHE_DIR", str(APP_CACHE_DIR / "osmnx-http")))
OVERPASS_TIMEOUT_SECONDS = int(os.getenv("OSMNX_REQUEST_TIMEOUT", "60"))
REAL_SCORE_DIR = DATA_DIR / "scores"
TOWER_DIR = DATA_DIR / "towers"
TOWER_CACHE_DB_PATH = Path(os.getenv("TOWER_CACHE_DB_PATH", str(DATA_DIR / "tower_cache.db")))
API_KEY_STATE_PATH = Path(os.getenv("OPENCELLID_KEY_STATE_PATH", str(DATA_DIR / "api_key_state.json")))
ENV_FILE_PATH = Path(os.getenv("ENV_FILE_PATH", str(SERVICE_DIR / ".env")))
CITY_PLACE_QUERIES: dict[str, str] = {
    "bangalore": os.getenv("BANGALORE_PLACE_QUERY", DEFAULT_BANGALORE_QUERY),
}
GRAPH_CACHE: dict[str, "CityState"] = {}
CITY_LOCKS = defaultdict(threading.Lock)
PRELOAD_GUARD_LOCK = threading.Lock()
SCHEDULER_STOP = threading.Event()
SCHEDULER_THREAD: threading.Thread | None = None
PRELOAD_THREADS: dict[str, threading.Thread] = {}
CORRIDOR_CACHE: dict[tuple[float, float, float, float], tuple[list[dict[str, Any]], float]] = {}
WGS84_TO_WEB_MERCATOR = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
EMPTY_TILE = mapbox_vector_tile.encode({"name": MVT_LAYER_NAME, "features": []})
ACTIVE_CITY: str | None = None
GRAPH_STATUS: dict[str, str] = {}
GRAPH_ERRORS: dict[str, str] = {}
MAX_RAM_MB = int(os.getenv("MAX_RAM_MB", "1536"))
HOTSPOT_CACHE_LOCK = threading.Lock()
HOTSPOT_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
TOWER_WORKER: TowerIngestionWorker | None = None
API_KEY_MANAGER: APIKeyManager | None = None
LOCAL_TOWER_INDEX: dict[str, Any] | None = None

ox.settings.use_cache = True
ox.settings.log_console = False
ox.settings.cache_folder = str(OSMNX_HTTP_CACHE_DIR)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class SegmentRecord:
    segment_id: str
    geometry: BaseGeometry
    lat: float
    lon: float
    length: float
    highway: str
    surface: str
    properties: dict[str, Any]


@dataclass
class CityState:
    city: str
    graph: Any
    expires_at: float
    segments: list[SegmentRecord]
    segment_lookup: dict[str, int]
    tile_index: dict[int, dict[int, dict[int, list[int]]]] = field(default_factory=dict)
    edge_tile_map: dict[str, set[tuple[int, int, int]]] = field(default_factory=dict)
    tile_cache: "LRUTileCache" = field(default_factory=lambda: LRUTileCache(maxsize=500))
    context: dict[str, list[float]] = field(default_factory=dict)
    scores_updated_at: float = 0.0
    gpu_spatial_index: Any | None = None
    score_values: Any | None = None
    score_source: str = "ML_synthetic"
    score_metadata: dict[str, Any] = field(default_factory=dict)


class CorridorScoresRequest(BaseModel):
    origin: list[float]
    destination: list[float]
    edge_coords: dict[str, list[float]]
    padding_km: float = 3.0


class CorridorTileUpdateRequest(BaseModel):
    scores: dict[str, float]


class LRUTileCache:
    def __init__(self, maxsize: int = 500):
        self.cache: OrderedDict[tuple[int, int, int], bytes] = OrderedDict()
        self.maxsize = maxsize

    def get(self, key: tuple[int, int, int]) -> bytes | None:
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return zlib.decompress(self.cache[key])

    def set(self, key: tuple[int, int, int], value: bytes) -> None:
        compressed = zlib.compress(value, level=1)
        if key in self.cache:
            self.cache.move_to_end(key)
        elif len(self.cache) >= self.maxsize:
            self.cache.popitem(last=False)
        self.cache[key] = compressed

    def clear(self) -> None:
        self.cache.clear()

    def __len__(self) -> int:
        return len(self.cache)


def load_hotspot_cache() -> None:
    if not HOTSPOT_CACHE_PATH.exists():
        return
    try:
        payload = json.loads(HOTSPOT_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[cache] failed to read hotspot cache: {exc}")
        return
    if not isinstance(payload, dict):
        return
    with HOTSPOT_CACHE_LOCK:
        HOTSPOT_CACHE.clear()
        for cache_key, entry in payload.items():
            if isinstance(entry, dict):
                HOTSPOT_CACHE[str(cache_key)] = entry


def persist_hotspot_cache() -> None:
    HOTSPOT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HOTSPOT_CACHE_LOCK:
        payload = dict(HOTSPOT_CACHE)
    HOTSPOT_CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")


def hotspot_cache_key(
    city: str,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    zoom: int,
) -> str:
    return json.dumps(
        {
            "city": city,
            "bbox": [
                round(min_lat, 3),
                round(min_lon, 3),
                round(max_lat, 3),
                round(max_lon, 3),
            ],
            "zoom": int(zoom),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def get_cached_hotspots(
    city: str,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    zoom: int,
) -> list[dict[str, Any]] | None:
    cache_key = hotspot_cache_key(city, min_lat, min_lon, max_lat, max_lon, zoom)
    now = time.time()
    with HOTSPOT_CACHE_LOCK:
        entry = HOTSPOT_CACHE.get(cache_key)
        if entry is None:
            return None
        stored_at = float(entry.get("stored_at") or 0.0)
        if now - stored_at > HOTSPOT_CACHE_TTL_SECONDS:
            HOTSPOT_CACHE.pop(cache_key, None)
            return None
        HOTSPOT_CACHE.move_to_end(cache_key)
        payload = entry.get("payload")
        if isinstance(payload, list):
            print(f"[cache] hotspot hit for {city} @ z{zoom}")
            return payload
    return None


def store_cached_hotspots(
    city: str,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    zoom: int,
    payload: list[dict[str, Any]],
) -> None:
    cache_key = hotspot_cache_key(city, min_lat, min_lon, max_lat, max_lon, zoom)
    with HOTSPOT_CACHE_LOCK:
        HOTSPOT_CACHE[cache_key] = {"stored_at": time.time(), "payload": payload}
        HOTSPOT_CACHE.move_to_end(cache_key)
        while len(HOTSPOT_CACHE) > HOTSPOT_CACHE_MAX_ENTRIES:
            HOTSPOT_CACHE.popitem(last=False)
    persist_hotspot_cache()


def detect_system_gpu() -> None:
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
        print(f"[tiles] CuPy runtime unavailable, using CPU score arrays: {exc}")


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


def array_nbytes(values: Any) -> int:
    try:
        return int(values.nbytes)
    except Exception:
        return 0


def real_scores_path(city: str) -> Path:
    return REAL_SCORE_DIR / f"{city}_real_scores.pkl"


def real_scores_meta_path(city: str) -> Path:
    return REAL_SCORE_DIR / f"{city}_real_scores_meta.json"


def tower_meta_path(city: str) -> Path:
    return TOWER_DIR / f"{city}_towers_meta.json"


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def score_summary(values: np.ndarray) -> dict[str, float]:
    total = max(int(values.shape[0]), 1)
    dead = int(np.sum(values < 0.3))
    weak = int(np.sum((values >= 0.3) & (values < 0.6)))
    good = int(np.sum(values >= 0.6))
    return {
        "dead": dead,
        "weak": weak,
        "good": good,
        "coverage_percent": round((good / total) * 100.0, 1),
        "dead_zone_percent": round((dead / total) * 100.0, 1),
    }


def default_score_metadata(city: str, source: str, *, updated_at: float = 0.0) -> dict[str, Any]:
    timestamp = ""
    if updated_at:
        timestamp = time.strftime("%Y-%m-%d", time.gmtime(updated_at))
    return {
        "city": city,
        "source": source,
        "tower_count": 0,
        "coverage_percent": 0.0,
        "dead_zone_percent": 0.0,
        "last_updated": timestamp,
    }


def load_real_scores(city: str, state: CityState) -> tuple[np.ndarray, dict[str, Any]] | None:
    score_path = real_scores_path(city)
    if not score_path.exists():
        return None

    with score_path.open("rb") as handle:
        stored_scores = pickle.load(handle)

    if not isinstance(stored_scores, dict):
        raise ValueError(f"Unexpected score payload in {score_path}")

    score_values = np.full(len(state.segments), ROAD_FALLBACK_SCORE, dtype=np.float32)
    matched = 0
    for segment_id, score in stored_scores.items():
        segment_index = state.segment_lookup.get(str(segment_id))
        if segment_index is None:
            continue
        score_values[segment_index] = np.float32(max(0.0, min(1.0, float(score))))
        matched += 1

    metadata = load_json_file(real_scores_meta_path(city))
    if not metadata:
        metadata = load_json_file(tower_meta_path(city))
    metadata = {
        **default_score_metadata(city, "OpenCellID"),
        **metadata,
        "city": city,
        "matched_segments": matched,
    }

    summary = score_summary(score_values)
    metadata["coverage_percent"] = float(metadata.get("coverage_percent") or summary["coverage_percent"])
    metadata["dead_zone_percent"] = float(metadata.get("dead_zone_percent") or summary["dead_zone_percent"])
    metadata.setdefault("tower_count", 0)

    print(f"[scores] Loaded REAL TRAI/tower scores for {city}")
    print("[scores] Score distribution:")
    print(f"  Dead zones: {summary['dead']} ({summary['dead_zone_percent']:.1f}%)")
    print(f"  Weak signal: {summary['weak']} ({(summary['weak'] / max(len(score_values), 1)) * 100.0:.1f}%)")
    print(f"  Good signal: {summary['good']} ({summary['coverage_percent']:.1f}%)")
    return score_values, metadata


def cached_coverage_metadata(city: str) -> dict[str, Any] | None:
    city_slug = normalize_city(city)
    if not TOWER_CACHE_DB_PATH.exists():
        return None
    try:
        with sqlite3.connect(str(TOWER_CACHE_DB_PATH), timeout=1, check_same_thread=False) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=1000;")
            total_tiles = int(
                conn.execute(
                    "SELECT COUNT(*) FROM tiles WHERE city = ?",
                    (city_slug,),
                ).fetchone()[0]
            )
            covered_tiles = int(
                conn.execute(
                    "SELECT COUNT(*) FROM coverage_tiles WHERE city = ? AND has_real_data = 1",
                    (city_slug,),
                ).fetchone()[0]
            )
            if total_tiles <= 0 or covered_tiles <= 0:
                return None
            tower_count = int(
                conn.execute(
                    """
                    SELECT COUNT(DISTINCT tw.id)
                    FROM towers AS tw
                    JOIN tower_tile_map AS map
                      ON map.tower_id = tw.id
                    JOIN tiles AS t
                      ON t.tile_id = map.tile_id
                    WHERE t.city = ?
                    """,
                    (city_slug,),
                ).fetchone()[0]
            )
            last_updated = conn.execute(
                """
                SELECT MAX(last_updated)
                FROM tiles
                WHERE city = ? AND is_cached = 1
                """,
                (city_slug,),
            ).fetchone()[0]
    except sqlite3.OperationalError as exc:
        print(f"[coverage-debug] metadata query busy: {exc}")
        return None

    coverage_percent = round((covered_tiles / max(total_tiles, 1)) * 100.0, 1)
    print(f"[coverage-debug] covered tiles: {covered_tiles}")
    print(f"[coverage-debug] total tiles: {total_tiles}")
    return {
        "source": "OpenCellID",
        "tower_count": tower_count,
        "coverage_percent": coverage_percent,
        "dead_zone_percent": 0.0,
        "last_updated": last_updated or "",
        "covered_tiles": covered_tiles,
        "total_tiles": total_tiles,
    }


def to_device_array(values: np.ndarray) -> Any:
    float32_values = np.asarray(values, dtype=np.float32)
    if USE_CUPY and cp is not None:
        gpu_values = cp.asarray(float32_values, dtype=cp.float32)
        del float32_values
        return gpu_values
    return float32_values


def to_numpy_array(values: Any) -> np.ndarray:
    if USE_CUPY and cp is not None and isinstance(values, cp.ndarray):
        return cp.asnumpy(values)
    return np.asarray(values)


def extract_scores(values: Any, indexes: list[int]) -> np.ndarray:
    if not indexes:
        return np.asarray([], dtype=np.float32)
    index_array = np.asarray(indexes, dtype=np.int32)
    if USE_CUPY and cp is not None and isinstance(values, cp.ndarray):
        return cp.asnumpy(values[cp.asarray(index_array, dtype=cp.int32)]).astype(np.float32, copy=False)
    return np.asarray(values[index_array], dtype=np.float32)


def corridor_bbox(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    padding_km: float = 3.0,
) -> tuple[float, float, float, float]:
    pad = float(padding_km) / 111.0
    min_lat = min(origin_lat, dest_lat) - pad
    max_lat = max(origin_lat, dest_lat) + pad
    min_lon = min(origin_lon, dest_lon) - pad
    max_lon = max(origin_lon, dest_lon) + pad
    return min_lat, min_lon, max_lat, max_lon


def get_corridor_cache_key(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
) -> tuple[float, float, float, float]:
    return (
        round(min_lat, 2),
        round(min_lon, 2),
        round(max_lat, 2),
        round(max_lon, 2),
    )


def configured_proxy_env() -> dict[str, str]:
    return {
        name: value
        for name in PROXY_ENV_VARS
        if (value := os.getenv(name))
    }


def bbox_area_m2(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
) -> float:
    mid_lat = (min_lat + max_lat) / 2.0
    height_m = abs(max_lat - min_lat) * 111_000.0
    width_m = abs(max_lon - min_lon) * 111_000.0 * max(math.cos(math.radians(mid_lat)), 0.2)
    return height_m * width_m


def chunk_corridor_bbox(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
) -> list[tuple[float, float, float, float]]:
    area_m2 = bbox_area_m2(min_lat, min_lon, max_lat, max_lon)
    if area_m2 <= OPENCELLID_MAX_BBOX_AREA_M2:
        return [(min_lat, min_lon, max_lat, max_lon)]

    mid_lat = (min_lat + max_lat) / 2.0
    lat_step = OPENCELLID_CHUNK_SIDE_KM / 111.0
    lon_step = OPENCELLID_CHUNK_SIDE_KM / (111.0 * max(math.cos(math.radians(mid_lat)), 0.2))

    chunks: list[tuple[float, float, float, float]] = []
    lat_cursor = min_lat
    while lat_cursor < max_lat:
        next_lat = min(lat_cursor + lat_step, max_lat)
        lon_cursor = min_lon
        while lon_cursor < max_lon:
            next_lon = min(lon_cursor + lon_step, max_lon)
            chunks.append((lat_cursor, lon_cursor, next_lat, next_lon))
            lon_cursor = next_lon
        lat_cursor = next_lat
    return chunks


async def fetch_tower_chunk(
    client: httpx.AsyncClient,
    chunk_bbox: tuple[float, float, float, float],
    chunk_number: int,
    chunk_total: int,
) -> list[dict[str, Any]]:
    from tile_loader import fetch_tower_chunk as fetch_tower_chunk_impl

    while True:
        try:
            return await fetch_tower_chunk_impl(
                client,
                chunk_bbox,
                chunk_number=chunk_number,
                key_manager=API_KEY_MANAGER,
                token=OPENCELLID_TOKEN,
                logger=print,
            )
        except RuntimeError as exc:
            message = str(exc).lower()
            if API_KEY_MANAGER is not None and "daily limit" in message:
                print("[api-key] exception quota hit - rotating key")
                API_KEY_MANAGER.mark_exhausted(reason=str(exc))
                continue
            raise


async def fetch_towers_for_corridor(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    padding_km: float = 3.0,
) -> list[dict[str, Any]] | None:
    min_lat, min_lon, max_lat, max_lon = corridor_bbox(
        origin_lat,
        origin_lon,
        dest_lat,
        dest_lon,
        padding_km,
    )
    bbox_area = bbox_area_m2(min_lat, min_lon, max_lat, max_lon)
    proxy_env = configured_proxy_env()
    print(
        "[towers] fetching corridor towers: "
        f"bbox=({min_lat:.3f},{min_lon:.3f},{max_lat:.3f},{max_lon:.3f}) "
        f"area={bbox_area / 1_000_000:.2f}km^2"
    )
    if proxy_env:
        print(
            "[towers] proxy env detected for external requests; "
            f"ignoring {', '.join(sorted(proxy_env.keys()))}"
        )
    print(
        f"[towers] OpenCellID token configured: {'yes' if bool(OPENCELLID_TOKEN.strip()) else 'no'}"
    )

    try:
        towers = await fetch_bbox_towers_live(
            min_lat,
            min_lon,
            max_lat,
            max_lon,
            token=OPENCELLID_TOKEN,
            key_manager=API_KEY_MANAGER,
            logger=print,
        )
    except Exception as exc:
        print(f"[towers] fetch error: {type(exc).__name__}: {exc!s}")
        return None

    if not towers:
        print("[towers] no towers returned after OpenCellID chunk fetch")
        return None

    print(f"[towers] fetched {len(towers)} unique towers for corridor")
    return towers


def queue_missing_tower_tiles(tile_ids: list[str]) -> int:
    if not tile_ids:
        return 0
    if TOWER_WORKER is None:
        print("[tower-cache] queued tiles requested before worker startup")
        return 0
    return TOWER_WORKER.enqueue_tiles(tile_ids)


async def fetch_towers_cached(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    padding_km: float = 3.0,
) -> tuple[list[dict[str, Any]] | None, dict[str, float], dict[str, Any]]:
    min_lat, min_lon, max_lat, max_lon = corridor_bbox(
        origin_lat,
        origin_lon,
        dest_lat,
        dest_lon,
        padding_km,
    )
    key = get_corridor_cache_key(min_lat, min_lon, max_lat, max_lon)
    now = time.time()
    city_slug = default_city()
    cached = CORRIDOR_CACHE.get(key)
    if cached is not None:
        towers, cached_at = cached
        if now - cached_at < CORRIDOR_CACHE_TTL:
            print(f"[towers] cache hit for bbox {key} ({len(towers)} towers)")
            _cached_towers, _missing_tile_ids, covered_tile_ids, query_tiles = cached_towers_for_bbox(
                TOWER_CACHE_DB_PATH,
                city_slug,
                min_lat,
                min_lon,
                max_lat,
                max_lon,
            )
            coverage_percent = round((len(covered_tile_ids) / max(len(query_tiles), 1)) * 100.0, 1) if query_tiles else 0.0
            source = "OpenCellID" if (coverage_percent > 0.0 or bool(towers)) else "ML estimate"
            print(f"[coverage] percent: {coverage_percent}")
            print(f"[coverage-debug] covered tiles: {len(covered_tile_ids)}")
            print(f"[coverage-debug] total tiles: {len(query_tiles)}")
            return towers, {
                "min_lat": key[0],
                "min_lon": key[1],
                "max_lat": key[2],
                "max_lon": key[3],
            }, {
                "source": source,
                "covered_tile_ids": covered_tile_ids,
                "query_tiles": query_tiles,
                "total_tiles": len(query_tiles),
                "covered_tiles": len(covered_tile_ids),
                "coverage_percent": coverage_percent,
            }
        CORRIDOR_CACHE.pop(key, None)
        print(f"[towers] cache expired for bbox {key}")

    towers, missing_tile_ids, covered_tile_ids, query_tiles = cached_towers_for_bbox(
        TOWER_CACHE_DB_PATH,
        city_slug,
        min_lat,
        min_lon,
        max_lat,
        max_lon,
    )
    coverage_percent = round((len(covered_tile_ids) / max(len(query_tiles), 1)) * 100.0, 1) if query_tiles else 0.0
    metadata: dict[str, Any] = {
        "source": "OpenCellID" if (coverage_percent > 0.0 or bool(towers)) else "ML estimate",
        "covered_tile_ids": covered_tile_ids,
        "query_tiles": query_tiles,
        "total_tiles": len(query_tiles),
        "covered_tiles": len(covered_tile_ids),
        "coverage_percent": coverage_percent,
    }
    print(f"[coverage] percent: {coverage_percent}")
    print(f"[coverage-debug] covered tiles: {len(covered_tile_ids)}")
    print(f"[coverage-debug] total tiles: {len(query_tiles)}")
    if towers:
        print(f"[tower-cache] hit for bbox {key} ({len(towers)} towers)")
        CORRIDOR_CACHE[key] = (towers, now)
    else:
        print(f"[tower-cache] miss for bbox {key}")

    if missing_tile_ids:
        queued = queue_missing_tower_tiles(missing_tile_ids)
        print(f"[tower-cache] queued {queued} missing tile(s) for bbox {key}")
        if not towers or coverage_percent > 0.0:
            print(f"[tower-cache] no persisted towers available for bbox {key}; using live corridor fetch")
            towers = await fetch_towers_for_corridor(
                origin_lat,
                origin_lon,
                dest_lat,
                dest_lon,
                padding_km,
            )
            if towers:
                CORRIDOR_CACHE[key] = (towers, now)
                metadata["source"] = "OpenCellID"

    return towers or None, {
        "min_lat": key[0],
        "min_lon": key[1],
        "max_lat": key[2],
        "max_lon": key[3],
    }, metadata


def tile_contains_point(tile: Any, lat: float, lon: float) -> bool:
    return (
        float(tile.min_lat) <= lat <= float(tile.max_lat)
        and float(tile.min_lon) <= lon <= float(tile.max_lon)
    )


def corridor_real_edge_coords(
    edge_coords: dict[str, list[float] | tuple[float, float]],
    query_tiles: list[Any],
    covered_tile_ids: set[str],
) -> dict[str, tuple[float, float]]:
    if not edge_coords:
        return {}
    if not query_tiles or not covered_tile_ids:
        return {}

    real_edges: dict[str, tuple[float, float]] = {}
    for edge_id, coords in edge_coords.items():
        lat = float(coords[0])
        lon = float(coords[1])
        for tile in query_tiles:
            if tile.tile_id in covered_tile_ids and tile_contains_point(tile, lat, lon):
                real_edges[str(edge_id)] = (lat, lon)
                break
    return real_edges


def update_coverage_model(city: str, tile_id: str, tower_count: int) -> None:
    city_slug = normalize_city(city)
    state = GRAPH_CACHE.get(city_slug)
    tile = cached_tile_bounds(TOWER_CACHE_DB_PATH, tile_id)
    if state is None or tile is None:
        return

    towers, _missing_tiles, _covered_tile_ids, _query_tiles = cached_towers_for_bbox(
        TOWER_CACHE_DB_PATH,
        city_slug,
        tile.min_lat,
        tile.min_lon,
        tile.max_lat,
        tile.max_lon,
    )
    if not towers:
        return

    tile_polygon = box(tile.min_lon, tile.min_lat, tile.max_lon, tile.max_lat)
    edge_coords: dict[str, tuple[float, float]] = {}
    for segment in state.segments:
        if segment.geometry.intersects(tile_polygon):
            edge_coords[segment.segment_id] = (segment.lat, segment.lon)
    if not edge_coords:
        return

    scores = compute_scores_from_towers(edge_coords, towers)
    if not scores:
        return

    apply_city_scores(
        city_slug,
        state,
        scores,
        {
            "source": "OpenCellID",
            "tower_count": tower_count,
            "last_updated": time.strftime("%Y-%m-%d", time.gmtime()),
        },
    )
    print(f"[adaptive] updated {len(scores)} segment scores from tile {tile_id}")


def compute_scores_from_towers(
    edge_coords: dict[str, list[float] | tuple[float, float]],
    towers: list[dict[str, Any]],
) -> dict[str, float]:
    if not towers or not edge_coords:
        return {}

    radio_scores = {
        "NR": 1.0,
        "LTE": 0.85,
        "UMTS": 0.5,
        "GSM": 0.25,
    }

    tower_lats = np.asarray([float(tower["lat"]) for tower in towers], dtype=np.float32)
    tower_lons = np.asarray([float(tower["lon"]) for tower in towers], dtype=np.float32)
    tower_ranges = np.asarray(
        [min(float(tower.get("range", 500.0) or 500.0), 2000.0) for tower in towers],
        dtype=np.float32,
    )
    tower_weights = np.asarray(
        [radio_scores.get(str(tower.get("radio", "LTE")).upper(), 0.5) for tower in towers],
        dtype=np.float32,
    )

    edge_ids = list(edge_coords.keys())
    seg_lats = np.asarray([float(edge_coords[edge_id][0]) for edge_id in edge_ids], dtype=np.float32)
    seg_lons = np.asarray([float(edge_coords[edge_id][1]) for edge_id in edge_ids], dtype=np.float32)

    if USE_CUPY and cp is not None:
        try:
            t_lats = cp.asarray(tower_lats)
            t_lons = cp.asarray(tower_lons)
            t_ranges = cp.asarray(tower_ranges)
            t_weights = cp.asarray(tower_weights)
            s_lats = cp.asarray(seg_lats)
            s_lons = cp.asarray(seg_lons)
            scores = cp.zeros(len(edge_ids), dtype=cp.float32)
            batch_size = 1000

            for start in range(0, len(edge_ids), batch_size):
                stop = min(start + batch_size, len(edge_ids))
                lat_batch = s_lats[start:stop, cp.newaxis]
                lon_batch = s_lons[start:stop, cp.newaxis]
                dlat = (t_lats - lat_batch) * 111000.0
                dlon = (t_lons - lon_batch) * 111000.0 * cp.cos(cp.radians(lat_batch))
                dist = cp.sqrt(dlat**2 + dlon**2)
                in_range = dist < t_ranges
                weighted = in_range * t_weights
                best = cp.max(weighted, axis=1)
                scores[start:stop] = cp.clip(best, 0.05, 1.0)

            scores_np = cp.asnumpy(scores)
            free_gpu_memory()
        except Exception as exc:
            print(f"[towers] CuPy corridor scoring failed, using CPU: {exc}")
            scores_np = np.zeros(len(edge_ids), dtype=np.float32)
            for index, (seg_lat, seg_lon) in enumerate(zip(seg_lats, seg_lons, strict=False)):
                dlat = (tower_lats - seg_lat) * 111000.0
                dlon = (tower_lons - seg_lon) * 111000.0 * np.cos(np.radians(seg_lat))
                dist = np.sqrt(dlat**2 + dlon**2)
                in_range = dist < tower_ranges
                scores_np[index] = (
                    np.clip(np.max(tower_weights[in_range]), 0.05, 1.0) if np.any(in_range) else 0.05
                )
    else:
        scores_np = np.zeros(len(edge_ids), dtype=np.float32)
        for index, (seg_lat, seg_lon) in enumerate(zip(seg_lats, seg_lons, strict=False)):
            dlat = (tower_lats - seg_lat) * 111000.0
            dlon = (tower_lons - seg_lon) * 111000.0 * np.cos(np.radians(seg_lat))
            dist = np.sqrt(dlat**2 + dlon**2)
            in_range = dist < tower_ranges
            scores_np[index] = (
                np.clip(np.max(tower_weights[in_range]), 0.05, 1.0) if np.any(in_range) else 0.05
            )

    return {
        edge_ids[index]: round(float(scores_np[index]), 3)
        for index in range(len(edge_ids))
    }


def build_gpu_spatial_index(segments: list[SegmentRecord]) -> Any | None:
    if not USE_CUSPATIAL or not segments:
        return None

    try:
        return cudf.DataFrame(
            {
                "segment_index": list(range(len(segments))),
                "min_lon": [float(segment.geometry.bounds[0]) for segment in segments],
                "min_lat": [float(segment.geometry.bounds[1]) for segment in segments],
                "max_lon": [float(segment.geometry.bounds[2]) for segment in segments],
                "max_lat": [float(segment.geometry.bounds[3]) for segment in segments],
            }
        )
    except Exception as exc:
        print(f"[tiles] GPU spatial index build failed, falling back to CPU: {exc}")
        return None


def gpu_candidate_indexes(state: CityState, bounds) -> list[int]:
    if state.gpu_spatial_index is None:
        return []

    frame = state.gpu_spatial_index
    try:
        mask = (
            (frame["max_lon"] >= bounds.west)
            & (frame["min_lon"] <= bounds.east)
            & (frame["max_lat"] >= bounds.south)
            & (frame["min_lat"] <= bounds.north)
        )
        return [int(value) for value in frame.loc[mask, "segment_index"].to_arrow().to_pylist()]
    except Exception as exc:
        print(f"[tiles] GPU tile query failed, falling back to CPU: {exc}")
        state.gpu_spatial_index = None
        return []


def slugify_city_name(city: str) -> str:
    return "_".join(
        part
        for part in city.strip().lower().replace("-", "_").replace(" ", "_").split("_")
        if part
    )


def prediction_service_url() -> str:
    return os.getenv("PREDICTION_SERVICE_URL", DEFAULT_PREDICTION_SERVICE_URL).rstrip("/")


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
    if city_slug not in supported_cities():
        supported = ", ".join(supported_cities())
        raise ValueError(f"Unsupported city '{city}'. Supported cities: {supported}.")
    return city_slug


def place_query(city: str) -> str:
    city_slug = normalize_city(city)
    return CITY_PLACE_QUERIES.get(city_slug, DEFAULT_BANGALORE_QUERY)


def configured_overpass_urls() -> list[str]:
    primary_url = os.getenv("OSMNX_OVERPASS_URL", DEFAULT_OVERPASS_URL).strip()
    fallback_urls = os.getenv("OSMNX_OVERPASS_FALLBACK_URLS", DEFAULT_OVERPASS_FALLBACK_URLS)

    ordered_urls: list[str] = []
    for raw_url in [primary_url, *fallback_urls.split(",")]:
        endpoint = raw_url.strip().rstrip("/")
        if endpoint and endpoint not in ordered_urls:
            ordered_urls.append(endpoint)
    return ordered_urls


@contextmanager
def proxy_env_disabled(prefix: str = "[graph]"):
    removed: dict[str, str] = {}
    proxy_names = set(PROXY_ENV_VARS)
    proxy_names.update(name.lower() for name in PROXY_ENV_VARS)
    for name in proxy_names:
        value = os.environ.pop(name, None)
        if value is not None:
            removed[name] = value
    if removed:
        print(f"{prefix} proxy disabled")
    try:
        yield
    finally:
        os.environ.update(removed)


def configure_osmnx_request_settings(overpass_url: str) -> None:
    OSMNX_HTTP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ox.settings.use_cache = True
    ox.settings.log_console = False
    ox.settings.cache_folder = str(OSMNX_HTTP_CACHE_DIR)
    ox.settings.requests_timeout = int(OVERPASS_TIMEOUT_SECONDS)
    ox.settings.overpass_settings = f"[out:json][timeout:{int(OVERPASS_TIMEOUT_SECONDS)}]{{maxsize}}"
    ox.settings.overpass_rate_limit = True
    if hasattr(ox.settings, "requests_kwargs"):
        requests_kwargs = dict(getattr(ox.settings, "requests_kwargs", {}) or {})
        requests_kwargs["proxies"] = {"http": None, "https": None}
        ox.settings.requests_kwargs = requests_kwargs
    if hasattr(ox.settings, "overpass_url"):
        ox.settings.overpass_url = overpass_url
        return
    if hasattr(ox.settings, "overpass_endpoint"):
        ox.settings.overpass_endpoint = overpass_url
        return
    raise RuntimeError("OSMnx settings are missing overpass_url/overpass_endpoint")


def geocode_place_boundary(city: str):
    city_slug = normalize_city(city)
    place_name = place_query(city_slug)
    print(f"[graph] geocoding boundary for {city_slug}: {place_name}")
    with proxy_env_disabled():
        gdf = ox.geocode_to_gdf(place_name)
    if gdf.empty:
        raise RuntimeError(f"No boundary returned for {place_name}")
    geometry = gdf.geometry
    if hasattr(geometry, "union_all"):
        return geometry.union_all()
    return geometry.unary_union


def local_graph_fallback_paths(city: str) -> list[Path]:
    city_slug = normalize_city(city)
    return [
        GRAPH_CACHE_DIR / f"{city_slug}.graphml",
        DATA_DIR / "graphs" / f"{city_slug}.graphml",
        DATA_DIR / f"{city_slug}.graphml",
    ]


def load_local_graph_fallback(city: str) -> Any | None:
    city_slug = normalize_city(city)
    for path in local_graph_fallback_paths(city_slug):
        if not path.exists():
            continue
        print(f"[graph] local graph loaded from {path}")
        return ox.load_graphml(path)
    return None


def normalize_listish(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("[") and value.endswith("]"):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
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


def normalize_geometry(geometry: Any) -> BaseGeometry | None:
    if geometry is None:
        return None
    if isinstance(geometry, str):
        return wkt.loads(geometry)
    return geometry


def extract_linear_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type == "LineString":
        return geometry
    if geometry.geom_type == "MultiLineString":
        return geometry
    if geometry.geom_type != "GeometryCollection":
        return None

    line_parts: list[LineString] = []
    for part in geometry.geoms:
        if part.is_empty:
            continue
        if part.geom_type == "LineString":
            line_parts.append(part)
        elif part.geom_type == "MultiLineString":
            line_parts.extend(segment for segment in part.geoms if not segment.is_empty)

    if not line_parts:
        return None
    if len(line_parts) == 1:
        return line_parts[0]
    return MultiLineString(line_parts)


def edge_geometry(graph, u: int, v: int, data: dict[str, Any]) -> BaseGeometry | None:
    geometry = normalize_geometry(data.get("geometry"))
    if geometry is not None:
        return geometry
    start = graph.nodes[u]
    end = graph.nodes[v]
    return LineString([(start["x"], start["y"]), (end["x"], end["y"])])


def segment_midpoint(geometry: BaseGeometry) -> tuple[float, float]:
    centroid = geometry.centroid
    return float(centroid.y), float(centroid.x)


def build_segments(
    city: str,
    graph,
) -> tuple[
    list[SegmentRecord],
    dict[str, int],
    dict[int, dict[int, dict[int, list[int]]]],
    dict[str, set[tuple[int, int, int]]],
    dict[int, int],
]:
    city_slug = normalize_city(city)
    segments: list[SegmentRecord] = []
    segment_lookup: dict[str, int] = {}
    tile_index: dict[int, dict[int, dict[int, list[int]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    edge_tile_map: dict[str, set[tuple[int, int, int]]] = defaultdict(set)
    zoom_tile_counts: dict[int, set[tuple[int, int]]] = defaultdict(set)

    for u, v, key, data in graph.edges(keys=True, data=True):
        geometry = extract_linear_geometry(edge_geometry(graph, u, v, data))
        if geometry is None or geometry.is_empty:
            continue

        segment_id = f"{u}-{v}-{key}"
        lat, lon = segment_midpoint(geometry)
        highway = normalize_highway(data.get("highway"))
        surface = normalize_surface(data.get("surface"))
        length = float(data.get("length") or 1.0)
        segment = SegmentRecord(
            segment_id=segment_id,
            geometry=geometry,
            lat=lat,
            lon=lon,
            length=length,
            highway=highway,
            surface=surface,
            properties={
                "segment_id": segment_id,
                "road_type": highway,
                "surface": surface,
                "name": normalize_name(data.get("name")),
                "length": length,
                "lat": lat,
                "lon": lon,
            },
        )
        segment_index = len(segments)
        segments.append(segment)
        segment_lookup[segment_id] = segment_index

        min_lon, min_lat, max_lon, max_lat = geometry.bounds
        for tile in mercantile.tiles(
            min_lon,
            min_lat,
            max_lon,
            max_lat,
            range(MIN_TILE_ZOOM, MAX_TILE_ZOOM + 1),
        ):
            tile_index[tile.z][tile.x][tile.y].append(segment_index)
            edge_tile_map[segment_id].add((tile.z, tile.x, tile.y))
            zoom_tile_counts[tile.z].add((tile.x, tile.y))

    tile_count_summary = {
        zoom: len(tile_keys)
        for zoom, tile_keys in zoom_tile_counts.items()
    }
    return segments, segment_lookup, dict(tile_index), dict(edge_tile_map), tile_count_summary


def derive_city_context(graph) -> dict[str, list[float]]:
    points: list[tuple[float, float]] = []
    min_lat = float("inf")
    max_lat = float("-inf")
    min_lon = float("inf")
    max_lon = float("-inf")

    for _, data in graph.nodes(data=True):
        lat = float(data["y"])
        lon = float(data["x"])
        points.append((lat, lon))
        min_lat = min(min_lat, lat)
        max_lat = max(max_lat, lat)
        min_lon = min(min_lon, lon)
        max_lon = max(max_lon, lon)

    if len(points) < 2 or not all(
        value not in {float("inf"), float("-inf")}
        for value in (min_lat, max_lat, min_lon, max_lon)
    ):
        raise ValueError("Unable to derive a city context from the graph.")

    unique_points: list[tuple[float, float]] = []
    seen: set[str] = set()

    for lat, lon in points:
        key = f"{lat:.6f},{lon:.6f}"
        if key in seen:
            continue
        seen.add(key)
        unique_points.append((lat, lon))

    unique_points.sort(key=lambda point: point[0] + point[1])
    origin_index = int((len(unique_points) - 1) * 0.2)
    destination_index = int((len(unique_points) - 1) * 0.8)
    origin = unique_points[origin_index]
    destination = unique_points[destination_index]

    if origin == destination and len(unique_points) > 1:
        destination = unique_points[-1]

    if origin == destination:
        raise ValueError("Unable to derive distinct demo points from the graph.")

    return {
        "center": [(min_lat + max_lat) / 2, (min_lon + max_lon) / 2],
        "origin": [origin[0], origin[1]],
        "destination": [destination[0], destination[1]],
    }


def graph_cache_path(city: str) -> Path:
    return GRAPH_CACHE_DIR / f"{normalize_city(city)}.graphml"


def simplify_city_graph(city: str, graph):
    try:
        graph = ox.simplify_graph(graph)
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
    except Exception as exc:
        print(f"[graph] consolidation skipped for {city}: {exc}")

    return graph


def load_or_fetch_graph(city: str):
    city_slug = normalize_city(city)
    cache_path = graph_cache_path(city_slug)
    GRAPH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OSMNX_HTTP_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if cache_path.exists():
        print(f"[graph] Loading Bangalore graph (cached: yes)")
        return ox.load_graphml(cache_path)

    local_graph = load_local_graph_fallback(city_slug)
    if local_graph is not None:
        if cache_path != local_graph_fallback_paths(city_slug)[0]:
            try:
                ox.save_graphml(local_graph, cache_path)
            except Exception as exc:
                print(f"[graph] failed to persist local graph cache to {cache_path}: {exc}")
        print("[graph] local graph loaded")
        return local_graph

    print(f"[graph] Loading Bangalore graph (cached: no)")
    overpass_urls = configured_overpass_urls()
    configure_osmnx_request_settings(overpass_urls[0])
    print("[graph] geocode fallback used")
    polygon = geocode_place_boundary(city_slug)
    attempt_errors: list[str] = []

    for attempt_number, overpass_url in enumerate(overpass_urls, start=1):
        try:
            configure_osmnx_request_settings(overpass_url)
            print(
                f"[graph] attempt {attempt_number}: querying {overpass_url} "
                f"(timeout={OVERPASS_TIMEOUT_SECONDS}s)"
            )
            with proxy_env_disabled():
                graph = ox.graph_from_polygon(
                    polygon,
                    network_type="drive",
                    simplify=False,
                    retain_all=False,
                    truncate_by_edge=True,
                )
            graph = simplify_city_graph(city_slug, graph)
            ox.save_graphml(graph, cache_path)
            print(f"[graph] Saved Bangalore graph cache to {cache_path}")
            return graph
        except Exception as exc:
            error_message = f"{overpass_url} -> {type(exc).__name__}: {exc}"
            attempt_errors.append(error_message)
            print(f"[graph] attempt {attempt_number} failed: {error_message}")

    raise RuntimeError(
        "All Overpass endpoints failed for "
        f"{city_slug} after {len(attempt_errors)} attempt(s): {'; '.join(attempt_errors)}"
    )


def load_city_state(city: str) -> CityState:
    global ACTIVE_CITY

    city_slug = normalize_city(city)
    now = time.time()
    cached_state = GRAPH_CACHE.get(city_slug)
    if cached_state and cached_state.expires_at > now:
        ACTIVE_CITY = city_slug
        return cached_state

    with CITY_LOCKS[city_slug]:
        now = time.time()
        cached_state = GRAPH_CACHE.get(city_slug)
        if cached_state and cached_state.expires_at > now:
            ACTIVE_CITY = city_slug
            return cached_state

        graph = load_or_fetch_graph(city_slug)
        state = build_city_state(city_slug, graph, now + CACHE_TTL_SECONDS)
        GRAPH_CACHE[city_slug] = state
        ACTIVE_CITY = city_slug

    refresh_city_predictions(city_slug)
    return GRAPH_CACHE[city_slug]


def require_city_state(city: str) -> CityState:
    city_slug = normalize_city(city)
    cached_state = GRAPH_CACHE.get(city_slug)
    now = time.time()

    if cached_state and cached_state.expires_at > now and GRAPH_STATUS.get(city_slug) == "ready":
        return cached_state

    status = GRAPH_STATUS.get(city_slug, "idle")
    if status == "loading":
        raise HTTPException(status_code=503, detail="Graph is still loading")
    if status == "error":
        raise HTTPException(status_code=503, detail=GRAPH_ERRORS.get(city_slug, "Graph unavailable"))
    raise HTTPException(status_code=503, detail="Graph not loaded")


def build_prediction_payload(city: str, state: CityState) -> dict[str, Any]:
    return {
        "city": city,
        "segments": [
            {
                "id": segment.segment_id,
                "highway": segment.highway,
                "lat": segment.lat,
                "lon": segment.lon,
                "length": segment.length,
            }
            for segment in state.segments
        ],
    }


def post_prediction_scores(city: str, state: CityState) -> tuple[dict[str, float], dict[str, Any]]:
    payload = json.dumps(build_prediction_payload(city, state)).encode("utf-8")
    prediction_request = request.Request(
        f"{prediction_service_url()}/predict",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(prediction_request, timeout=120) as response:
        data = json.loads(response.read().decode("utf-8"))
    raw_scores = data.get("scores", {})
    metadata = {
        **default_score_metadata(city, "ML_synthetic", updated_at=time.time()),
        "source": "ML_synthetic",
        "data_source": str(data.get("data_source") or "synthetic"),
        "confidence": float(data.get("confidence") or 0.0),
    }
    return ({str(key): float(value) for key, value in raw_scores.items()}, metadata)


def apply_city_scores(
    city: str,
    state: CityState,
    scores: dict[str, float],
    metadata: dict[str, Any] | None = None,
) -> None:
    changed = False
    current_scores = (
        to_numpy_array(state.score_values).astype(np.float32, copy=True)
        if state.score_values is not None
        else np.full(len(state.segments), 0.5, dtype=np.float32)
    )

    for segment_id, score in scores.items():
        rounded_score = max(0.0, min(1.0, round(float(score), 3)))
        segment_index = state.segment_lookup.get(segment_id)
        if segment_index is None:
            continue
        if not math.isclose(float(current_scores[segment_index]), rounded_score, abs_tol=1e-4):
            current_scores[segment_index] = rounded_score
            changed = True

    state.score_values = to_device_array(current_scores)
    state.scores_updated_at = time.time()
    state.score_source = str((metadata or {}).get("source") or state.score_source or "ML_synthetic")
    state.score_metadata = {
        **default_score_metadata(city, state.score_source, updated_at=state.scores_updated_at),
        **state.score_metadata,
        **(metadata or {}),
    }
    summary = score_summary(current_scores)
    if state.score_source in {"OpenCellID", "OpenCelliD", "TRAI"}:
        state.score_metadata["coverage_percent"] = float(
            state.score_metadata.get("coverage_percent") or summary["coverage_percent"]
        )
        state.score_metadata["dead_zone_percent"] = float(
            state.score_metadata.get("dead_zone_percent") or summary["dead_zone_percent"]
        )
    else:
        state.score_metadata["coverage_percent"] = summary["coverage_percent"]
        state.score_metadata["dead_zone_percent"] = summary["dead_zone_percent"]
    state.score_metadata["last_updated"] = time.strftime("%Y-%m-%d", time.gmtime(state.scores_updated_at))
    if changed:
        state.tile_cache.clear()
    free_gpu_memory()


def update_corridor_tiles(city: str, scores: dict[str, float]) -> int:
    city_slug = normalize_city(city)
    state = GRAPH_CACHE.get(city_slug)
    if state is None or not scores:
        return 0

    current_scores = (
        to_numpy_array(state.score_values).astype(np.float32, copy=True)
        if state.score_values is not None
        else np.full(len(state.segments), 0.5, dtype=np.float32)
    )

    invalidated: set[tuple[int, int, int]] = set()
    updated = 0
    for edge_id, score in scores.items():
        segment_index = state.segment_lookup.get(str(edge_id))
        if segment_index is None:
            continue
        clamped = np.float32(max(0.0, min(1.0, float(score))))
        current_scores[segment_index] = clamped
        updated += 1
        for tile_key in state.edge_tile_map.get(str(edge_id), set()):
            invalidated.add(tile_key)

    state.score_values = to_device_array(current_scores)
    for tile_key in invalidated:
        state.tile_cache.cache.pop(tile_key, None)

    if updated:
        state.scores_updated_at = time.time()
        print(f"[tiles] invalidated corridor tiles with real scores ({len(invalidated)} tiles)")

    free_gpu_memory()
    return updated


def refresh_city_predictions(city: str) -> None:
    city_slug = normalize_city(city)
    state = GRAPH_CACHE.get(city_slug)
    if state is None or not state.segments:
        return
    if state.score_source in {"TRAI", "OpenCellID", "OpenCelliD"}:
        return

    try:
        scores, metadata = post_prediction_scores(city_slug, state)
    except (TimeoutError, error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[prediction] failed to refresh {city_slug}: {exc}")
        return

    apply_city_scores(city_slug, state, scores, metadata)
    print(
        f"[prediction] refreshed {city_slug} with {len(scores)} segment scores "
        f"from {metadata['data_source']}"
    )


def prediction_refresh_loop() -> None:
    while not SCHEDULER_STOP.is_set():
        for city_slug in list(GRAPH_CACHE.keys()):
            refresh_city_predictions(city_slug)

        if SCHEDULER_STOP.wait(PREDICTION_REFRESH_SECONDS):
            return


def build_city_state(city: str, graph, expires_at: float) -> CityState:
    city_slug = normalize_city(city)
    segments, segment_lookup, tile_index, edge_tile_map, tile_counts = build_segments(city_slug, graph)
    context = derive_city_context(graph)
    gpu_spatial_index = build_gpu_spatial_index(segments)
    zoom12_tiles = tile_counts.get(12, 0)
    print(
        f"[tiles] indexed {len(segments)} edges across {zoom12_tiles} tiles at zoom 12"
    )
    state = CityState(
        city=city_slug,
        graph=graph,
        expires_at=expires_at,
        segments=segments,
        segment_lookup=segment_lookup,
        tile_index=tile_index,
        edge_tile_map=edge_tile_map,
        tile_cache=LRUTileCache(maxsize=500),
        context=context,
        gpu_spatial_index=gpu_spatial_index,
        score_values=to_device_array(np.full(len(segments), 0.5, dtype=np.float32)),
        score_source="ML_synthetic",
        score_metadata=default_score_metadata(city_slug, "ML_synthetic"),
    )
    loaded_real = load_real_scores(city_slug, state)
    if loaded_real is not None:
        real_values, metadata = loaded_real
        state.score_values = to_device_array(real_values)
        state.score_source = str(metadata.get("source") or "OpenCellID")
        state.score_metadata = metadata
        state.scores_updated_at = time.time()
    else:
        coverage_metadata = cached_coverage_metadata(city_slug)
        if coverage_metadata is not None:
            state.score_source = "OpenCellID"
            state.score_metadata = {
                **default_score_metadata(city_slug, "OpenCellID", updated_at=time.time()),
                **coverage_metadata,
            }
            state.scores_updated_at = time.time()
            print(
                f"[scores] Using cached OpenCellID coverage for {city_slug} "
                f"({coverage_metadata['coverage_percent']}%)"
            )
        else:
            print(f"[scores] No real scores for {city_slug}, using ML prediction")
    return state


def tile_bounds(z: int, x: int, y: int):
    return mercantile.bounds(x, y, z)


def mercator_tile_bounds(z: int, x: int, y: int):
    return mercantile.xy_bounds(x, y, z)


def tile_index_candidates(state: CityState, z: int, x: int, y: int) -> list[int]:
    if z < MIN_TILE_ZOOM or z > MAX_TILE_ZOOM:
        return list(range(len(state.segments)))

    zoom_bucket = state.tile_index.get(z)
    if zoom_bucket:
        x_bucket = zoom_bucket.get(x)
        if x_bucket:
            candidates = x_bucket.get(y)
            if candidates:
                return candidates

    return list(range(len(state.segments)))


def encode_tile(features: list[dict[str, Any]], z: int, x: int, y: int) -> bytes:
    if not features:
        return EMPTY_TILE

    bounds = mercator_tile_bounds(z, x, y)
    return mapbox_vector_tile.encode(
        {"name": MVT_LAYER_NAME, "features": features},
        default_options={
            "quantize_bounds": (bounds.left, bounds.bottom, bounds.right, bounds.top),
            "extents": 4096,
        },
    )


def tile_features(state: CityState, z: int, x: int, y: int) -> list[dict[str, Any]]:
    tile = mercantile.Tile(x=x, y=y, z=z)
    bounds = mercantile.bounds(tile)
    tile_polygon = box(bounds.west, bounds.south, bounds.east, bounds.north)
    features: list[dict[str, Any]] = []
    candidate_indexes = (
        gpu_candidate_indexes(state, bounds)
        if state.gpu_spatial_index is not None
        else tile_index_candidates(state, z, x, y)
    )
    candidate_scores = (
        extract_scores(state.score_values, candidate_indexes)
        if candidate_indexes and state.score_values is not None
        else np.asarray([], dtype=np.float32)
    )

    for score_index, segment_index in enumerate(candidate_indexes):
        segment = state.segments[segment_index]
        if not segment.geometry.intersects(tile_polygon):
            continue

        clipped_geometry = extract_linear_geometry(segment.geometry.intersection(tile_polygon))
        if clipped_geometry is None or clipped_geometry.is_empty:
            continue

        mercator_geometry = shapely_transform(WGS84_TO_WEB_MERCATOR.transform, clipped_geometry)
        properties = dict(segment.properties)
        properties["connectivity_score"] = round(float(candidate_scores[score_index]), 3) if len(candidate_scores) else 0.5
        features.append(
            {
                "geometry": mercator_geometry,
                "properties": properties,
            }
        )

    return features


def viewport_candidate_indexes(
    state: CityState,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    zoom: int,
) -> list[int]:
    query_zoom = max(MIN_TILE_ZOOM, min(MAX_TILE_ZOOM, int(zoom)))
    candidate_indexes: set[int] = set()
    for tile in mercantile.tiles(min_lon, min_lat, max_lon, max_lat, [query_zoom]):
        for segment_index in tile_index_candidates(state, tile.z, tile.x, tile.y):
            candidate_indexes.add(segment_index)
    if candidate_indexes:
        return sorted(candidate_indexes)
    return list(range(len(state.segments)))


def signal_strength_for_score(score: float) -> str:
    if score < 0.3:
        return "weak"
    if score < 0.6:
        return "medium"
    return "strong"


def hotspots_for_viewport(
    state: CityState,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    zoom: int,
) -> list[dict[str, Any]]:
    viewport_polygon = box(min_lon, min_lat, max_lon, max_lat)
    candidate_indexes = viewport_candidate_indexes(state, min_lat, min_lon, max_lat, max_lon, zoom)
    candidate_scores = (
        extract_scores(state.score_values, candidate_indexes)
        if candidate_indexes and state.score_values is not None
        else np.asarray([], dtype=np.float32)
    )

    hotspots: list[dict[str, Any]] = []
    for score_index, segment_index in enumerate(candidate_indexes):
        segment = state.segments[segment_index]
        if not segment.geometry.intersects(viewport_polygon):
            continue
        score = float(candidate_scores[score_index]) if len(candidate_scores) else 0.5
        if score >= 0.6:
            continue
        road_name = str(segment.properties.get("name") or segment.highway.replace("_", " ").title())
        hotspots.append(
            {
                "id": segment.segment_id,
                "name": road_name,
                "lat": round(segment.lat, 6),
                "lon": round(segment.lon, 6),
                "signal_strength": signal_strength_for_score(score),
                "radius_meters": 140 if score < 0.3 else 90,
                "city": state.city,
                "score": round(score, 3),
            }
        )

    hotspots.sort(key=lambda hotspot: (hotspot["score"], hotspot["name"]))
    return hotspots[:60]


def schedule_preload(city: str) -> str:
    city_slug = normalize_city(city)

    def runner() -> None:
        try:
            print(f"[graph] Loading Bangalore graph (cached: {'yes' if graph_cache_path(city_slug).exists() else 'no'})")
            load_city_state(city_slug)
            GRAPH_STATUS[city_slug] = "ready"
            print("[graph] Loaded successfully")
        except Exception as exc:
            GRAPH_STATUS[city_slug] = "error"
            GRAPH_ERRORS[city_slug] = str(exc)
            print(f"[graph] preload failed for {city_slug}: {exc}")
        finally:
            with PRELOAD_GUARD_LOCK:
                active_thread = PRELOAD_THREADS.get(city_slug)
                if active_thread is thread:
                    PRELOAD_THREADS.pop(city_slug, None)

    with PRELOAD_GUARD_LOCK:
        existing_state = GRAPH_CACHE.get(city_slug)
        if existing_state is not None and existing_state.expires_at > time.time():
            GRAPH_STATUS[city_slug] = "ready"
            return "ready"

        existing = PRELOAD_THREADS.get(city_slug)
        if GRAPH_STATUS.get(city_slug) == "loading" and existing is not None and existing.is_alive():
            return "already loading"

        GRAPH_STATUS[city_slug] = "loading"
        GRAPH_ERRORS.pop(city_slug, None)
        thread = threading.Thread(target=runner, name=f"preload-{city_slug}", daemon=True)
        PRELOAD_THREADS[city_slug] = thread
        thread.start()
        return "loading"


def initialize_tower_cache() -> dict[str, int | float | str]:
    if not TOWER_CACHE_DB_PATH.exists():
        print("[startup] tower cache not found")
        print("[startup] building Bangalore tile grid")
    elif tower_tiles_table_empty(TOWER_CACHE_DB_PATH):
        print("[startup] building Bangalore tile grid")
    ensure_city_tiles(TOWER_CACHE_DB_PATH, default_city())
    payload = persistent_cache_status(TOWER_CACHE_DB_PATH, default_city())
    print(
        "[tower-cache] initialized "
        f"{payload['cached_tiles']}/{payload['total_tiles']} tiles "
        f"({payload['percent_complete']}% complete)"
    )
    return payload


def load_local_towers() -> dict[str, Any] | None:
    global LOCAL_TOWER_INDEX

    LOCAL_TOWER_INDEX = load_local_tower_source(logger=print)
    return LOCAL_TOWER_INDEX


def tower_tiles_table_empty(db_path: Path) -> bool:
    if not db_path.exists():
        return True
    try:
        with sqlite3.connect(str(db_path), timeout=5) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'tiles'"
            ).fetchone()
            if row is None or int(row[0]) == 0:
                return True
            count_row = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()
            return count_row is None or int(count_row[0]) == 0
    except sqlite3.Error:
        return True


def safe_cache_status_payload(city: str | None = None) -> dict[str, Any]:
    city_slug = normalize_city(city or default_city())
    loading_payload = {
        "status": "loading",
        "city": city_slug,
        "total_tiles": 0,
        "tile_count": 0,
        "cached_tiles": 0,
        "remaining_tiles": 0,
        "percent_complete": 0.0,
        "coverage_percent": 0.0,
        "real_coverage_tiles": 0,
        "real_coverage_percent": 0.0,
    }
    if not TOWER_CACHE_DB_PATH.exists():
        return loading_payload

    try:
        with sqlite3.connect(str(TOWER_CACHE_DB_PATH), timeout=1, check_same_thread=False) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=1000;")
            row = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'tiles'"
            ).fetchone()
            if row is None or int(row[0]) == 0:
                return loading_payload

            total_tiles = int(
                conn.execute(
                    "SELECT COUNT(*) FROM tiles WHERE city = ?",
                    (city_slug,),
                ).fetchone()[0]
            )
            cached_tiles = int(
                conn.execute(
                    "SELECT COUNT(*) FROM tiles WHERE city = ? AND is_cached = 1",
                    (city_slug,),
                ).fetchone()[0]
            )
            real_coverage_tiles = int(
                conn.execute(
                    "SELECT COUNT(*) FROM coverage_tiles WHERE city = ? AND has_real_data = 1",
                    (city_slug,),
                ).fetchone()[0]
            )
    except sqlite3.OperationalError as exc:
        print(f"[tower-cache] status query busy: {exc}")
        return loading_payload

    remaining_tiles = max(total_tiles - cached_tiles, 0)
    percent_complete = round((cached_tiles / max(total_tiles, 1)) * 100.0, 1)
    real_coverage_percent = round((real_coverage_tiles / max(total_tiles, 1)) * 100.0, 1)
    print(f"[coverage] percent: {real_coverage_percent}")
    print(f"[cache-status] coverage: {real_coverage_percent}")
    return {
        "status": "ready",
        "city": city_slug,
        "total_tiles": total_tiles,
        "tile_count": total_tiles,
        "cached_tiles": cached_tiles,
        "remaining_tiles": remaining_tiles,
        "percent_complete": percent_complete,
        "coverage_percent": real_coverage_percent,
        "real_coverage_tiles": real_coverage_tiles,
        "real_coverage_percent": real_coverage_percent,
    }


@app.on_event("startup")
def startup_event() -> None:
    global SCHEDULER_THREAD
    global TOWER_WORKER
    global API_KEY_MANAGER
    detect_system_gpu()
    validate_cupy_runtime()
    load_hotspot_cache()
    APP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    GRAPH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OSMNX_HTTP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    load_local_towers()
    initialize_tower_cache()
    if API_KEY_MANAGER is None:
        API_KEY_MANAGER = APIKeyManager(
            env_path=ENV_FILE_PATH,
            state_path=API_KEY_STATE_PATH,
            logger=print,
        )
    local_towers_ready = bool(LOCAL_TOWER_INDEX and int(LOCAL_TOWER_INDEX.get("count") or 0) > 0)
    key_status = API_KEY_MANAGER.status()
    if not local_towers_ready and int(key_status["total_keys"] or 0) <= 0:
        print("[startup] no local towers or OpenCellID API keys configured; ingestion worker disabled")
    elif TOWER_WORKER is None:
        print("[startup] starting ingestion worker")
        TOWER_WORKER = TowerIngestionWorker(
            db_path=TOWER_CACHE_DB_PATH,
            city=default_city(),
            key_manager=None if local_towers_ready else API_KEY_MANAGER,
            logger=print,
            on_tile_ingested=update_coverage_model,
            request_delay_seconds=float(os.getenv("OPENCELLID_REQUEST_DELAY_SECONDS", "3")),
        )
    if TOWER_WORKER is not None:
        TOWER_WORKER.start()
    for city in supported_cities():
        GRAPH_STATUS[city] = "idle"
    print(f"[memory] data-service limit {MAX_RAM_MB}MB, current {process_memory_mb():.1f}MB")
    schedule_preload(default_city())
    if SCHEDULER_THREAD is None or not SCHEDULER_THREAD.is_alive():
        SCHEDULER_STOP.clear()
        SCHEDULER_THREAD = threading.Thread(target=prediction_refresh_loop, daemon=True)
        SCHEDULER_THREAD.start()


@app.on_event("shutdown")
def shutdown_event() -> None:
    SCHEDULER_STOP.set()
    persist_hotspot_cache()
    if TOWER_WORKER is not None:
        TOWER_WORKER.stop()
    free_gpu_memory()


@app.get("/cities")
def get_cities() -> list[str]:
    return supported_cities()


@app.get("/city-context/{city}")
def get_city_context(city: str) -> dict[str, list[float]]:
    try:
        state = require_city_state(city)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return state.context


@app.get("/hotspots/{city}")
def get_hotspots(
    city: str,
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    zoom: int = 12,
) -> dict[str, Any]:
    try:
        state = require_city_state(city)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    cached_payload = get_cached_hotspots(city, min_lat, min_lon, max_lat, max_lon, zoom)
    if cached_payload is not None:
        return {
            "city": normalize_city(city),
            "hotspots": cached_payload,
            "source": state.score_source,
            "cached": True,
        }

    payload = hotspots_for_viewport(state, min_lat, min_lon, max_lat, max_lon, zoom)
    store_cached_hotspots(city, min_lat, min_lon, max_lat, max_lon, zoom, payload)
    return {
        "city": normalize_city(city),
        "hotspots": payload,
        "source": state.score_source,
        "cached": False,
    }


@app.get("/segments/{city}")
def get_segments(city: str) -> dict[str, Any]:
    try:
        state = require_city_state(city)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    score_values = (
        to_numpy_array(state.score_values).astype(np.float32, copy=False)
        if state.score_values is not None
        else np.full(len(state.segments), 0.5, dtype=np.float32)
    )

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(segment.geometry),
                "properties": {
                    **segment.properties,
                    "connectivity_score": round(float(score_values[index]), 3),
                },
            }
            for index, segment in enumerate(state.segments)
        ],
    }


def score_source_payload(state: CityState) -> dict[str, Any]:
    score_values = (
        to_numpy_array(state.score_values).astype(np.float32, copy=False)
        if state.score_values is not None
        else np.full(len(state.segments), 0.5, dtype=np.float32)
    )
    summary = score_summary(score_values)
    metadata = {
        **default_score_metadata(state.city, state.score_source, updated_at=state.scores_updated_at),
        **state.score_metadata,
    }
    metadata["city"] = state.city
    metadata["source"] = state.score_source
    if state.score_source in {"OpenCellID", "OpenCelliD", "TRAI"}:
        metadata["coverage_percent"] = float(metadata.get("coverage_percent") or summary["coverage_percent"])
        metadata["dead_zone_percent"] = float(metadata.get("dead_zone_percent") or summary["dead_zone_percent"])
    else:
        metadata["coverage_percent"] = summary["coverage_percent"]
        metadata["dead_zone_percent"] = summary["dead_zone_percent"]
    metadata.setdefault("tower_count", 0)
    if not metadata.get("last_updated"):
        metadata["last_updated"] = time.strftime("%Y-%m-%d", time.gmtime(state.scores_updated_at)) if state.scores_updated_at else ""
    return metadata


@app.get("/scores/{city}")
def get_scores(city: str) -> dict[str, Any]:
    try:
        state = require_city_state(city)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if state.score_values is None:
        refresh_city_predictions(city)

    score_values = (
        to_numpy_array(state.score_values).astype(np.float32, copy=False)
        if state.score_values is not None
        else np.full(len(state.segments), 0.5, dtype=np.float32)
    )

    return {
        "city": normalize_city(city),
        "updated_at": state.scores_updated_at,
        "source": state.score_source,
        "scores": {
            segment.segment_id: round(float(score_values[index]), 3)
            for index, segment in enumerate(state.segments)
        },
    }


@app.get("/scores/source/{city}")
def get_score_source(city: str) -> dict[str, Any]:
    try:
        state = require_city_state(city)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return score_source_payload(state)


@app.get("/tiles/{city}/{z}/{x}/{y}.mvt")
def get_tile(city: str, z: int, x: int, y: int) -> Response:
    try:
        state = require_city_state(city)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    tile_key = (z, x, y)
    cached_tile = state.tile_cache.get(tile_key)
    if cached_tile is not None:
        return Response(
            content=cached_tile,
            media_type=MVT_MEDIA_TYPE,
            headers={"Cache-Control": "public, max-age=300"},
        )

    encoded_tile = encode_tile(tile_features(state, z, x, y), z, x, y)
    state.tile_cache.set(tile_key, encoded_tile)

    return Response(
        content=encoded_tile,
        media_type=MVT_MEDIA_TYPE,
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/corridor-towers")
async def get_corridor_towers(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    padding_km: float = 3.0,
) -> dict[str, Any]:
    towers, bbox, metadata = await fetch_towers_cached(
        origin_lat,
        origin_lon,
        dest_lat,
        dest_lon,
        padding_km,
    )
    return {
        "towers": towers or [],
        "count": len(towers or []),
        "bbox": bbox,
        "source": metadata.get("source", "ML estimate"),
        "coverage_percent": metadata.get("coverage_percent", 0.0),
    }


@app.post("/corridor-scores")
async def post_corridor_scores(payload: CorridorScoresRequest) -> dict[str, Any]:
    if len(payload.origin) != 2 or len(payload.destination) != 2:
        raise HTTPException(status_code=422, detail="origin and destination must contain [lat, lon]")

    towers, bbox, metadata = await fetch_towers_cached(
        float(payload.origin[0]),
        float(payload.origin[1]),
        float(payload.destination[0]),
        float(payload.destination[1]),
        payload.padding_km,
    )
    coverage_percent = float(metadata.get("coverage_percent", 0.0))
    if not towers and coverage_percent == 0.0:
        return {
            "scores": {},
            "source": "ML estimate",
            "tower_count": 0,
            "bbox": bbox,
            "coverage_percent": coverage_percent,
            "real_data_percent": coverage_percent,
        }

    query_tiles = list(metadata.get("query_tiles") or [])
    covered_tile_ids = set(metadata.get("covered_tile_ids") or set())
    real_edge_coords = corridor_real_edge_coords(payload.edge_coords, query_tiles, covered_tile_ids)
    if towers and real_edge_coords:
        scores = compute_scores_from_towers(real_edge_coords, towers)
    elif towers:
        scores = compute_scores_from_towers(payload.edge_coords, towers)
    else:
        scores = {}
    return {
        "scores": scores,
        "source": metadata.get("source", "OpenCellID" if coverage_percent > 0.0 else "ML estimate"),
        "tower_count": len(towers or []),
        "bbox": bbox,
        "coverage_percent": coverage_percent,
        "real_data_percent": coverage_percent,
    }


@app.post("/corridor-feedback/{city}")
def post_corridor_feedback(city: str, payload: CorridorTileUpdateRequest) -> dict[str, Any]:
    try:
        updated = update_corridor_tiles(city, payload.scores)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "city": normalize_city(city),
        "updated_edges": updated,
        "status": "ok",
    }


@app.get("/cache-status")
def cache_status() -> dict[str, Any]:
    payload = safe_cache_status_payload(default_city())
    payload["db_path"] = str(TOWER_CACHE_DB_PATH)
    payload["ingestion_running"] = bool(TOWER_WORKER is not None and TOWER_WORKER.is_running())
    payload["local_towers"] = local_tower_source_status()
    return payload


@app.get("/api-key-status")
def api_key_status() -> dict[str, Any]:
    if API_KEY_MANAGER is None:
        return {
            "total_keys": 0,
            "active_key": None,
            "exhausted_keys": [],
            "remaining_keys": 0,
        }
    return API_KEY_MANAGER.status()


@app.post("/preload/{city}")
def preload(city: str) -> dict[str, Any]:
    city_slug = normalize_city(city)
    preload_status = schedule_preload(city_slug)
    return {"status": preload_status, "city": city_slug}


@app.get("/memory")
def memory() -> dict[str, Any]:
    state = GRAPH_CACHE.get(ACTIVE_CITY) if ACTIVE_CITY else None
    gpu_arrays_mb = round(array_nbytes(state.score_values) / (1024 * 1024), 1) if state and state.score_values is not None else 0.0
    cache_payload = persistent_cache_status(TOWER_CACHE_DB_PATH, default_city())
    return {
        "ram_mb": round(process_memory_mb(), 1),
        "vram_mb": round(current_vram_mb(), 1),
        "graph_loaded": ACTIVE_CITY,
        "tile_cache_size": len(state.tile_cache) if state else 0,
        "gpu_arrays_mb": gpu_arrays_mb,
        "max_ram_mb": MAX_RAM_MB,
        "tower_cached_tiles": cache_payload["cached_tiles"],
        "tower_total_tiles": cache_payload["total_tiles"],
    }


@app.get("/health")
def health() -> dict[str, Any]:
    city_slug = default_city()
    cache_payload = safe_cache_status_payload(city_slug)
    return {
        "status": "ok",
        "cached_cities": list(GRAPH_CACHE.keys()),
        "gpu_spatial_indexing": USE_CUSPATIAL,
        "active_city": ACTIVE_CITY,
        "graph_status": GRAPH_STATUS,
        "graph_errors": GRAPH_ERRORS,
        "graph_ready": bool(GRAPH_STATUS.get(city_slug) == "ready" and city_slug in GRAPH_CACHE),
        "tower_cache": cache_payload,
        "local_towers": local_tower_source_status(),
        "api_keys": API_KEY_MANAGER.status() if API_KEY_MANAGER is not None else None,
        "ingestion_running": bool(TOWER_WORKER is not None and TOWER_WORKER.is_running()),
    }
