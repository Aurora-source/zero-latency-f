from __future__ import annotations

import csv
import gc
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel, Field
import xgboost as xgb

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

try:
    import torch
except ImportError:
    torch = None

try:
    import cupy as cp
except ImportError:
    cp = None

app = FastAPI(title="Connectivity Prediction Service", version="0.2.0")

DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_DIR = Path(os.getenv("MODEL_DIR", str(DEFAULT_MODEL_DIR)))
MODEL_PATH = MODEL_DIR / "connectivity_model.pkl"
SYNTHETIC_SAMPLE_COUNT = 500_000
TOWER_DATA_DIR = Path(__file__).resolve().parents[1] / "data-service" / "data" / "towers"

CITY_CENTERS: dict[str, tuple[float, float]] = {
    "bangalore": (12.97, 77.59),
    "chennai": (13.08, 80.27),
    "mumbai": (19.07, 72.88),
    "delhi": (28.61, 77.21),
    "hyderabad": (17.39, 78.49),
}
HIGHWAY_ENCODING: dict[str, int] = {
    "motorway": 5,
    "trunk": 4,
    "primary": 3,
    "secondary": 2,
    "tertiary": 1,
    "residential": 0,
}

MODEL: Any | None = None
MODEL_FAMILY = "unknown"
MODEL_DEVICE = "cpu"
MODEL_READY_AT = 0.0
USE_GPU = False
USE_CUPY = False
GPU_NAME = "CPU"
MAX_RAM_MB = int(os.getenv("MAX_RAM_MB", "1024"))
MODEL_SOURCE = "synthetic"
MODEL_CONFIDENCE = 0.65
TOWER_CHUNK_SIZE = 4096
GPU_BATCH_SIZE = int(os.getenv("GPU_BATCH_SIZE", "50000"))
TOWER_WEIGHT_ENCODING = {
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
class TowerDataset:
    city: str
    coords: np.ndarray
    ranges: np.ndarray
    weights: np.ndarray
    count: int


class SegmentPayload(BaseModel):
    id: str
    highway: str = "unknown"
    lat: float
    lon: float
    length: float = Field(default=1.0, ge=0.0)


class PredictRequest(BaseModel):
    city: str | None = None
    segments: list[SegmentPayload]


class PredictResponse(BaseModel):
    scores: dict[str, float]
    data_source: str
    confidence: float


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


def configure_gpu_runtime() -> None:
    global USE_GPU
    global USE_CUPY
    global GPU_NAME

    if torch is None:
        USE_GPU = False
        USE_CUPY = False
        GPU_NAME = "CPU"
        print("[prediction] torch not installed, using CPU")
        return

    try:
        if torch.cuda.is_available():
            GPU_NAME = torch.cuda.get_device_name(0)
            USE_GPU = True
            if cp is not None:
                try:
                    probe = cp.arange(4, dtype=cp.float32)
                    float(probe.sum().item())
                    USE_CUPY = True
                except Exception as exc:
                    USE_CUPY = False
                    print(f"[prediction] CuPy runtime unavailable, using torch-only GPU path: {exc}")
            print(f"[prediction] Using GPU: {GPU_NAME}")
            return
    except Exception as exc:
        print(f"[prediction] CUDA probe failed: {exc}")

    USE_GPU = False
    USE_CUPY = False
    GPU_NAME = "CPU"
    print("[prediction] CUDA not available, using CPU")


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
    if USE_CUPY and cp is not None:
        try:
            return float(cp.get_default_memory_pool().used_bytes()) / (1024 * 1024)
        except Exception:
            pass
    if torch is None or not torch.cuda.is_available():
        return 0.0
    try:
        return float(torch.cuda.memory_allocated(0)) / (1024 * 1024)
    except Exception:
        return 0.0


def log_vram_usage(label: str = "") -> None:
    try:
        used_mb = current_vram_mb()
        prefix = f"[vram] {label} " if label else "[vram] "
        print(f"{prefix}used={used_mb:.0f}MB")
    except Exception:
        pass


def normalize_radio_weight(value: str) -> float:
    return float(TOWER_WEIGHT_ENCODING.get(str(value or "").strip().lower(), 0.5))


def load_available_tower_datasets() -> dict[str, TowerDataset]:
    datasets: dict[str, TowerDataset] = {}
    if not TOWER_DATA_DIR.exists():
        return datasets

    for csv_path in sorted(TOWER_DATA_DIR.glob("*_towers.csv")):
        city = csv_path.stem.replace("_towers", "")
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

                try:
                    tower_range = float(row.get("range") or 0.0)
                except (TypeError, ValueError):
                    tower_range = 0.0

                tower_range = min(max(tower_range, 250.0), 2000.0)
                if tower_range <= 0:
                    tower_range = 2000.0

                coords.append((lat, lon))
                ranges.append(tower_range)
                weights.append(normalize_radio_weight(row.get("radio", "")))

        if not coords:
            continue

        datasets[city] = TowerDataset(
            city=city,
            coords=np.asarray(coords, dtype=np.float32),
            ranges=np.asarray(ranges, dtype=np.float32),
            weights=np.asarray(weights, dtype=np.float32),
            count=len(coords),
        )

    return datasets


def score_points_against_towers_numpy(points: np.ndarray, towers: TowerDataset) -> np.ndarray:
    scores = np.full(points.shape[0], 0.05, dtype=np.float32)
    if points.size == 0 or towers.count == 0:
        return scores

    for start in range(0, points.shape[0], TOWER_CHUNK_SIZE):
        stop = min(start + TOWER_CHUNK_SIZE, points.shape[0])
        chunk = points[start:stop]
        dlat = towers.coords[:, 0][None, :] - chunk[:, 0][:, None]
        dlon = towers.coords[:, 1][None, :] - chunk[:, 1][:, None]
        dist = np.sqrt(dlat * dlat + dlon * dlon).astype(np.float32, copy=False) * np.float32(111000.0)
        in_range = dist <= towers.ranges[None, :]
        coverage_ratio = 1.0 - (dist / towers.ranges[None, :])
        weighted = np.clip(coverage_ratio * 0.9 + 0.1, 0.05, 1.0) * towers.weights[None, :]
        weighted = np.where(in_range, weighted, 0.05)
        scores[start:stop] = np.clip(weighted.max(axis=1), 0.05, 1.0).astype(np.float32, copy=False)
    return scores


def score_points_against_towers(points: np.ndarray, towers: TowerDataset) -> np.ndarray:
    if torch is None or not USE_GPU:
        return score_points_against_towers_numpy(points, towers)

    try:
        point_tensor = torch.as_tensor(points, dtype=torch.float32, device="cuda")
        tower_tensor = torch.as_tensor(towers.coords, dtype=torch.float32, device="cuda")
        range_tensor = torch.as_tensor(towers.ranges, dtype=torch.float32, device="cuda")
        weight_tensor = torch.as_tensor(towers.weights, dtype=torch.float32, device="cuda")
        scores = np.full(points.shape[0], 0.05, dtype=np.float32)

        for start in range(0, points.shape[0], TOWER_CHUNK_SIZE):
            stop = min(start + TOWER_CHUNK_SIZE, points.shape[0])
            chunk = point_tensor[start:stop]
            dlat = tower_tensor[:, 0].unsqueeze(0) - chunk[:, 0].unsqueeze(1)
            dlon = tower_tensor[:, 1].unsqueeze(0) - chunk[:, 1].unsqueeze(1)
            dist = torch.sqrt(dlat * dlat + dlon * dlon) * 111000.0
            in_range = dist <= range_tensor.unsqueeze(0)
            coverage_ratio = 1.0 - (dist / range_tensor.unsqueeze(0))
            weighted = torch.clamp(coverage_ratio * 0.9 + 0.1, 0.05, 1.0) * weight_tensor.unsqueeze(0)
            weighted = torch.where(in_range, weighted, torch.full_like(weighted, 0.05))
            chunk_scores = torch.clamp(weighted.max(dim=1).values, 0.05, 1.0)
            scores[start:stop] = chunk_scores.detach().cpu().numpy().astype(np.float32, copy=False)
        return scores
    except Exception as exc:
        print(f"[prediction] GPU tower scoring failed, using CPU: {exc}")
        return score_points_against_towers_numpy(points, towers)


def tower_based_targets(
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    city_labels: np.ndarray,
    datasets: dict[str, TowerDataset],
) -> np.ndarray:
    scores = np.full(latitudes.shape[0], 0.05, dtype=np.float32)
    points = np.column_stack([latitudes, longitudes]).astype(np.float32, copy=False)

    for city, dataset in datasets.items():
        mask = city_labels == city
        if not np.any(mask):
            continue
        scores[mask] = score_points_against_towers(points[mask], dataset)
    return scores


def normalize_city(city: str | None) -> str:
    if not city:
        return "bangalore"
    return city.strip().lower().replace("-", "_").replace(" ", "_")


def highway_value(highway: str) -> int:
    if not highway:
        return 0
    normalized = highway.strip().lower().split(";", 1)[0]
    return HIGHWAY_ENCODING.get(normalized, 1)


def is_night_hour(hour: int) -> int:
    return int(hour >= 20 or hour <= 6)


def terrain_proxy(lat: float, lon: float, city: str | None) -> float:
    city_key = normalize_city(city)
    center_lat, center_lon = CITY_CENTERS.get(city_key, CITY_CENTERS["bangalore"])
    return abs(lat - center_lat) + abs(lon - center_lon)


def build_feature_matrix(
    segments: list[SegmentPayload],
    *,
    city: str | None,
    hour_of_day: int | None = None,
) -> np.ndarray:
    hour = hour_of_day if hour_of_day is not None else time.localtime().tm_hour
    night_flag = is_night_hour(hour)
    rows: list[list[float]] = []

    for segment in segments:
        rows.append(
            [
                float(highway_value(segment.highway)),
                float(segment.lat),
                float(segment.lon),
                float(hour),
                float(night_flag),
                float(terrain_proxy(segment.lat, segment.lon, city)),
                float(segment.length),
            ]
        )

    return np.asarray(rows, dtype=np.float32)


def synthetic_score(
    highway_codes: np.ndarray,
    hour_of_day: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    lengths: np.ndarray,
    city_labels: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    is_night = (hour_of_day >= 20) | (hour_of_day <= 6)
    base = np.empty_like(latitudes, dtype=np.float32)

    motorway_mask = highway_codes >= 4
    primary_mask = (highway_codes >= 2) & (highway_codes <= 3)
    residential_mask = highway_codes == 0
    tertiary_mask = highway_codes == 1

    base[motorway_mask & ~is_night] = rng.uniform(0.75, 0.95, np.sum(motorway_mask & ~is_night))
    base[motorway_mask & is_night] = rng.uniform(0.55, 0.80, np.sum(motorway_mask & is_night))
    base[primary_mask & ~is_night] = rng.uniform(0.50, 0.80, np.sum(primary_mask & ~is_night))
    base[primary_mask & is_night] = rng.uniform(0.38, 0.68, np.sum(primary_mask & is_night))
    base[tertiary_mask & ~is_night] = rng.uniform(0.35, 0.65, np.sum(tertiary_mask & ~is_night))
    base[tertiary_mask & is_night] = rng.uniform(0.22, 0.52, np.sum(tertiary_mask & is_night))
    base[residential_mask & ~is_night] = rng.uniform(0.22, 0.58, np.sum(residential_mask & ~is_night))
    base[residential_mask & is_night] = rng.uniform(0.10, 0.45, np.sum(residential_mask & is_night))

    terrain = np.empty_like(latitudes, dtype=np.float32)
    for city_name, (center_lat, center_lon) in CITY_CENTERS.items():
        mask = city_labels == city_name
        terrain[mask] = np.abs(latitudes[mask] - center_lat) + np.abs(longitudes[mask] - center_lon)

    terrain_penalty = np.clip(terrain * 0.8, 0.0, 0.18)
    length_penalty = np.clip(lengths / 5000.0, 0.0, 0.1)
    night_penalty = np.where(is_night, 0.04, 0.0)
    noise = rng.normal(0.0, 0.08, size=latitudes.shape[0])

    scores = base - terrain_penalty - length_penalty - night_penalty + noise
    return np.clip(scores, 0.0, 1.0).astype(np.float32)


def generate_synthetic_training_data(
    sample_count: int,
    tower_datasets: dict[str, TowerDataset] | None = None,
) -> tuple[np.ndarray, np.ndarray, str, float]:
    rng = np.random.default_rng(42)
    if tower_datasets:
        city_names = np.array(sorted(tower_datasets.keys()))
    else:
        city_names = np.array(list(CITY_CENTERS.keys()))
    sampled_cities = rng.choice(city_names, size=sample_count, replace=True)

    latitudes = np.empty(sample_count, dtype=np.float32)
    longitudes = np.empty(sample_count, dtype=np.float32)
    for city_name, (center_lat, center_lon) in CITY_CENTERS.items():
        mask = sampled_cities == city_name
        latitudes[mask] = rng.normal(center_lat, 0.09, np.sum(mask))
        longitudes[mask] = rng.normal(center_lon, 0.09, np.sum(mask))

    highway_codes = rng.choice(
        np.array([0, 1, 2, 3, 4, 5], dtype=np.int32),
        size=sample_count,
        p=[0.30, 0.16, 0.18, 0.16, 0.10, 0.10],
    )
    hour_of_day = rng.integers(0, 24, size=sample_count, dtype=np.int32)
    lengths = rng.uniform(25.0, 2500.0, size=sample_count).astype(np.float32)
    is_night = np.where((hour_of_day >= 20) | (hour_of_day <= 6), 1.0, 0.0).astype(np.float32)

    terrain = np.empty(sample_count, dtype=np.float32)
    for city_name, (center_lat, center_lon) in CITY_CENTERS.items():
        mask = sampled_cities == city_name
        terrain[mask] = np.abs(latitudes[mask] - center_lat) + np.abs(longitudes[mask] - center_lon)

    features = np.column_stack(
        [
            highway_codes.astype(np.float32),
            latitudes,
            longitudes,
            hour_of_day.astype(np.float32),
            is_night,
            terrain,
            lengths,
        ]
    ).astype(np.float32)
    if tower_datasets:
        targets = tower_based_targets(latitudes, longitudes, sampled_cities, tower_datasets)
        return features, targets, "real_towers", 0.87

    targets = synthetic_score(
        highway_codes,
        hour_of_day,
        latitudes,
        longitudes,
        lengths,
        sampled_cities,
        rng,
    )
    return features, targets, "synthetic", 0.68


def build_xgboost_model(use_gpu: bool) -> Any:
    return xgb.XGBRegressor(
        objective="reg:squarederror",
        n_estimators=500,
        max_depth=8,
        learning_rate=0.05,
        tree_method="hist",
        device="cuda" if use_gpu else "cpu",
        n_jobs=-1,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_alpha=0.05,
        reg_lambda=1.0,
        random_state=42,
    )


def build_lightgbm_model(use_gpu: bool) -> Any:
    if lgb is None:
        raise RuntimeError("lightgbm is not installed")
    return lgb.LGBMRegressor(
        n_estimators=500,
        num_leaves=127,
        device="cuda" if use_gpu else "cpu",
        learning_rate=0.05,
        random_state=42,
    )


def save_model_bundle(model: Any, family: str) -> None:
    payload = {
        "model": model,
        "family": family,
        "device": MODEL_DEVICE,
        "sample_count": SYNTHETIC_SAMPLE_COUNT,
        "source": MODEL_SOURCE,
        "confidence": MODEL_CONFIDENCE,
    }
    joblib.dump(payload, MODEL_PATH)


def load_saved_model(desired_source: str) -> tuple[Any, str] | None:
    global MODEL_SOURCE
    global MODEL_CONFIDENCE

    if not MODEL_PATH.exists():
        return None

    loaded = joblib.load(MODEL_PATH)
    if isinstance(loaded, dict) and loaded.get("model") is not None:
        saved_source = str(loaded.get("source") or "synthetic")
        if saved_source != desired_source:
            print(
                f"[prediction] cached model uses {saved_source}; "
                f"retraining for {desired_source} labels"
            )
            return None
        MODEL_SOURCE = saved_source
        MODEL_CONFIDENCE = float(loaded.get("confidence") or MODEL_CONFIDENCE)
        family = str(loaded.get("family") or loaded["model"].__class__.__name__).lower()
        return loaded["model"], family

    if hasattr(loaded, "predict"):
        if desired_source != "synthetic":
            return None
        MODEL_SOURCE = "synthetic"
        MODEL_CONFIDENCE = 0.68
        return loaded, loaded.__class__.__name__.lower()

    return None


def train_or_load_model() -> tuple[Any, str]:
    global MODEL_DEVICE
    global MODEL_SOURCE
    global MODEL_CONFIDENCE

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tower_datasets = load_available_tower_datasets()
    desired_source = "real_towers" if tower_datasets else "synthetic"

    loaded = load_saved_model(desired_source)
    if loaded is not None:
        family = loaded[1]
        MODEL_DEVICE = "gpu" if USE_GPU else "cpu"
        return loaded

    features, targets, MODEL_SOURCE, MODEL_CONFIDENCE = generate_synthetic_training_data(
        SYNTHETIC_SAMPLE_COUNT,
        tower_datasets=tower_datasets or None,
    )
    split_index = max(int(features.shape[0] * 0.9), 1)
    X_train = features[:split_index]
    y_train = targets[:split_index]
    X_test = features[split_index:]
    y_test = targets[split_index:]
    training_errors: list[str] = []
    try:
        for family, builder in (("xgboost", build_xgboost_model), ("lightgbm", build_lightgbm_model)):
            for use_gpu in ([True, False] if USE_GPU else [False]):
                try:
                    model = builder(use_gpu)
                    model.fit(X_train, y_train)
                    MODEL_DEVICE = "gpu" if use_gpu else "cpu"
                    save_model_bundle(model, family)
                    return model, family
                except Exception as exc:
                    training_errors.append(f"{family} ({'gpu' if use_gpu else 'cpu'}): {exc}")
                    print(f"[prediction] {family} training failed on {'GPU' if use_gpu else 'CPU'}: {exc}")
    finally:
        del X_train, y_train, X_test, y_test, features, targets, tower_datasets
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass

    raise RuntimeError("Unable to train a connectivity model: " + "; ".join(training_errors))


def get_model() -> Any:
    global MODEL
    global MODEL_FAMILY
    global MODEL_READY_AT

    if MODEL is None:
        MODEL, MODEL_FAMILY = train_or_load_model()
        MODEL_READY_AT = time.time()
    return MODEL


def predict_batch_gpu(features_list: np.ndarray) -> np.ndarray:
    model = get_model()
    features_array = np.asarray(features_list, dtype=np.float32)

    if not USE_GPU or MODEL_DEVICE != "gpu":
        return np.asarray(model.predict(features_array), dtype=np.float32)

    try:
        if USE_CUPY and cp is not None:
            results: list[np.ndarray] = []
            for start in range(0, len(features_array), GPU_BATCH_SIZE):
                stop = min(start + GPU_BATCH_SIZE, len(features_array))
                batch_gpu = cp.asarray(features_array[start:stop], dtype=cp.float32)
                batch_predictions = np.asarray(
                    model.predict(cp.asnumpy(batch_gpu)),
                    dtype=np.float32,
                )
                results.append(batch_predictions)
                del batch_gpu
                cp.get_default_memory_pool().free_all_blocks()
            predictions = np.concatenate(results).astype(np.float32, copy=False)
            log_vram_usage("predict")
            return predictions

        if torch is not None and torch.cuda.is_available():
            features_tensor = torch.as_tensor(features_array, dtype=torch.float32, device="cuda")
            features_np = features_tensor.detach().cpu().numpy()
            predictions = np.asarray(model.predict(features_np), dtype=np.float32)
            torch.cuda.empty_cache()
            return predictions
    except Exception as exc:
        print(f"[prediction] GPU batch path failed, falling back to CPU arrays: {exc}")
        return np.asarray(model.predict(features_array), dtype=np.float32)

    return np.asarray(model.predict(features_array), dtype=np.float32)


@app.on_event("startup")
def startup_event() -> None:
    detect_system_gpu()
    configure_gpu_runtime()
    print(f"[memory] prediction-service limit {MAX_RAM_MB}MB, current {process_memory_mb():.1f}MB")
    get_model()
    log_vram_usage("startup")


@app.post("/predict", response_model=PredictResponse)
def predict_scores(request: PredictRequest) -> PredictResponse:
    if not request.segments:
        return PredictResponse(scores={}, data_source=MODEL_SOURCE, confidence=MODEL_CONFIDENCE)

    features = build_feature_matrix(request.segments, city=request.city)
    predictions = np.clip(predict_batch_gpu(features), 0.0, 1.0)

    return PredictResponse(
        scores={
            segment.id: float(round(score, 3))
            for segment, score in zip(request.segments, predictions, strict=False)
        },
        data_source=MODEL_SOURCE,
        confidence=MODEL_CONFIDENCE,
    )


@app.get("/health")
def health() -> dict[str, str | float | bool]:
    return {
        "status": "ok",
        "model_path": str(MODEL_PATH),
        "model_ready": bool(MODEL is not None),
        "ready_since": MODEL_READY_AT,
        "model_family": MODEL_FAMILY,
        "model_device": MODEL_DEVICE,
        "model_source": MODEL_SOURCE,
        "model_confidence": MODEL_CONFIDENCE,
        "gpu_enabled": USE_GPU,
        "gpu_name": GPU_NAME,
    }


@app.get("/memory")
def memory() -> dict[str, float | str | None]:
    return {
        "ram_mb": round(process_memory_mb(), 1),
        "vram_mb": round(current_vram_mb(), 1),
        "graph_loaded": None,
        "tile_cache_size": 0,
        "gpu_arrays_mb": round(current_vram_mb(), 1),
        "max_ram_mb": float(MAX_RAM_MB),
    }
