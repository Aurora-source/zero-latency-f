from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import psutil
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Connectivity Telemetry Service", version="0.1.0")

MAX_RAM_MB = int(os.getenv("MAX_RAM_MB", "256"))
SERVICE_STARTED_AT = time.time()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def process_memory_mb() -> float:
    return float(psutil.Process(os.getpid()).memory_info().rss) / (1024 * 1024)


@app.on_event("startup")
def startup_event() -> None:
    detect_system_gpu()
    print(
        "[telemetry] service starting "
        f"(max_ram_mb={MAX_RAM_MB}, current_ram_mb={process_memory_mb():.1f})"
    )


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "telemetry-service",
        "status": "ok",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "telemetry-service",
        "uptime_seconds": round(time.time() - SERVICE_STARTED_AT, 1),
        "max_ram_mb": MAX_RAM_MB,
    }


@app.get("/memory")
def memory() -> dict[str, float | int | None]:
    return {
        "ram_mb": round(process_memory_mb(), 1),
        "vram_mb": 0.0,
        "graph_loaded": None,
        "tile_cache_size": 0,
        "gpu_arrays_mb": 0.0,
        "max_ram_mb": MAX_RAM_MB,
    }


@app.get("/events")
def events() -> dict[str, Any]:
    return {
        "events": [],
        "count": 0,
    }
