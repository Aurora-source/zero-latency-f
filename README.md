# Connectivity-Aware Routing

This project contains the routing engine, prediction service, data service, gateway, and visualization frontend for connectivity-aware route planning. Bangalore is the currently supported production region.

The stable service/frontend contract, loading semantics, provenance vocabulary, and compatibility aliases are documented in [`docs/api-contract.md`](docs/api-contract.md).

## Architecture and authoritative frontend

- `services/data-service` owns road tiles, city scores, local/live tower ingestion,
  and the persistent tower cache (port 8001).
- `services/routing-engine` owns fastest, balanced, and connected pathfinding
  (port 8002).
- `services/prediction-service` supplies the CPU-compatible ML fallback (port 8003).
- `services/telemetry-service` is an optional local service (port 8004); it is not
  currently part of the production Compose topology.
- `services/visualization` is the authoritative React/Vite frontend (port 3000 in
  Compose, normally 5173 in local development).
- `services/visualization1` and `services/visualization/visualization` are historical
  reference copies. `app/app` is a separate dashboard UI. None of these three is the
  production frontend.
- `gateway/nginx.conf` is the public entry point and proxies browser `/api` requests.

```text
Browser -> Nginx -> services/visualization
                 -> routing-engine -> data-service -> prediction-service
                                   -> tower/graph caches
```

Docker Compose is the authoritative production runtime. `run-local.ps1` is the
developer-oriented Windows/WSL startup path.

## Local run

Prerequisites are Python 3.11, Node.js 20.19+ or 22.12+, npm, and PowerShell 5.1 or newer.

Use `run-local.ps1` from the repo root to create or activate the root virtual environment, start the Python services with `uvicorn`, and launch the Vite frontend without Docker.

```powershell
Copy-Item services\data-service\.env.example services\data-service\.env
.\run-local.ps1
```

The service-local environment file is optional when no OpenCellID credential is
needed. The script may install missing dependencies, so review that action before
using it in a constrained or offline environment.

| Local service | URL |
| --- | --- |
| Data API | `http://localhost:8001` |
| Routing API | `http://localhost:8002` |
| Prediction API | `http://localhost:8003` |
| Telemetry API (when present) | `http://localhost:8004` |
| Authoritative frontend | `http://localhost:5173` |

## Compose run

Blank credentials are a supported configuration:

```bash
docker compose --env-file /dev/null config --no-interpolate
docker compose --env-file /dev/null up --build
```

To provide credentials without sharing them with other services, pass an external
environment file to Compose. The Compose file injects the two OpenCellID variables
only into `data-service`; never commit that environment file.

```bash
docker compose --env-file services/data-service/.env up --build
```

The gateway is available at `http://localhost/`. Compose health gates use each
backend's `/ready` endpoint, while `/health` remains a liveness/diagnostic endpoint.

## Routing modes

- `fastest` minimizes dimensionally correct travel time.
- `balanced` trades some travel time for connectivity and risk quality.
- `connected` strongly avoids weak/dead-signal edges when a viable alternative
  exists.

Vehicle profiles keep `scooter`, `bike`, `car`, and `truck` as separate API values.

## Data-service credentials and local tower data

OpenCellID credentials are optional. `OPENCELLID_KEYS` accepts a comma-separated rotation list and `OPENCELLID_TOKEN` is the single-key compatibility input. Both default to an empty value; the data service remains usable with prediction fallback when neither is configured. Never commit credential values.

Compose passes these variables only to `data-service`. Prediction, routing, telemetry, visualization, and gateway processes do not receive them. `run-local.ps1` likewise leaves service-local environment-file loading to the data service and explicitly clears inherited OpenCellID variables in non-data child processes.

An optional local Bangalore tower CSV can be supplied at the path named by `LOCAL_TOWER_CSV_PATH`. Compose expects it under the shared cache at `/app/shared-cache/towers/bangalore_towers.csv`; it is runtime data and must not be committed or included in an image. Set `LOCAL_TOWER_PROVENANCE` to `opencellid` or `trai` when the provider is known; its safe default is `unknown`.

Precomputed score metadata belongs under the shared cache path configured by
`REAL_SCORE_DIR`. The compatibility field `coverage_percent` means real-data
coverage; signal quality is reported separately as `good_signal_percent`.

## CPU and optional GPU acceleration

The default Compose topology uses Python 3.11 CPU images, does not reserve an NVIDIA
device, and runs on CPU-only hosts. GPU detection in the services remains
opportunistic. Set the Docker build argument `INSTALL_GPU_REQUIREMENTS=1` for the
prediction and routing images and expose an NVIDIA device through a host-specific
Compose override; the shared topology intentionally does not require one.

For local NVIDIA acceleration (RTX 5070 / CUDA 12.8+):

1. Install CUDA 12.8 toolkit:
   https://developer.nvidia.com/cuda-downloads
   Select: Windows > x86_64 > 11 > exe(local)

2. Verify CUDA install:
   `nvcc --version`  # should show 12.8 or higher
   `nvidia-smi`      # should show RTX 5070

3. Install GPU Python packages:
   `pip install torch --index-url https://download.pytorch.org/whl/cu128`
   `pip install xgboost>=2.1 lightgbm>=4.3`

4. Optional - GPU acceleration extras:
   `pip install cupy-cuda12x`
   `pip install cuspatial-cu12`  # tile indexing only; Linux support varies

5. Verify GPU is detected by the app:
   `python -c "import torch; print(torch.cuda.get_device_name(0))"`
   Expected: `NVIDIA GeForce RTX 5070`

All GPU features degrade gracefully to CPU if CUDA is unavailable.

## Common issues

- If a city is warming, `POST /api/route` returns HTTP 202 with `Retry-After`; the
  authoritative frontend waits and retries automatically.
- If a port is occupied, stop the conflicting process before rerunning
  `run-local.ps1`.
- Heatmap tiles must use relative `/api/tiles/...` URLs so the Vite proxy and Nginx
  gateway work consistently.
- A 503 from `/ready` means the service is alive but its graph/model is not yet able
  to serve dependent traffic. Inspect `/health` for diagnostic state.
