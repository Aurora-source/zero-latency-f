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
- `services/visualization` is the authoritative React/Vite frontend (5173 locally).
  Its compiled assets are served by the production gateway.
- `services/visualization1` and `services/visualization/visualization` are historical
  reference copies. `app/app` is a separate dashboard UI. None of these three is the
  production frontend.
- `gateway/nginx.conf` is the public entry point and proxies browser `/api` requests.

```text
Browser -> Nginx (compiled frontend and /api proxy, localhost:8080)
                 -> routing-engine -> data-service -> prediction-service
                                   -> tower/graph caches
```

Docker Compose is the authoritative production runtime. `run-local.ps1` is the
developer-oriented Windows/WSL startup path.

## Local run

For credential-free CPU development on Linux/WSL, use the installed project-local
Python 3.11 environment and Node 22. The same mode is available through
`run-local.ps1 -LocalDataOnly -GraphPath ... -TowerCSVPath ... -ModelPath ...`.
It never opens dotenv files, installs packages, downloads road/tower data, or trains
models. Existing inputs are copied into an ignored working directory.

```bash
# Install declared CPU dependencies into .venv (uv or .venv/bin/python -m pip).
UV_CACHE_DIR=.cache/uv uv pip install --python .venv/bin/python --require-hashes -r requirements-test.lock
cd services/visualization
npm ci
cd ../..

.venv/bin/python run-local.py --graph /path/to/bangalore.graphml \
  --towers /path/to/existing_bengaluru_towers.csv \
  --model /path/to/trusted/connectivity_model.pkl
```

The supplied paths are inputs, not destinations. Use files on the D:-backed WSL
filesystem. Tower provenance stays `unknown`; no filename establishes a provider.
The model must match the seven-feature prediction API. The available legacy
XGBoost snapshot requires **XGBoost 3.2.0** and has unknown training provenance and
confidence. Its inference is an estimate, not measured coverage. There is no
bundled model or dataset in a fresh clone; missing artifacts are explicit blockers.

Open **http://127.0.0.1:5173**. The launcher waits for prediction, data, then routing
readiness and starts Vite last. All services bind to localhost with one worker.
Ctrl+C stops its children. `--detach` leaves them running; inspect or stop only
those recorded processes with:

```bash
.venv/bin/python run-local.py --status
.venv/bin/python run-local.py --stop
```

Use the same `--runtime-dir .cache/<name>` for start/status/stop when overriding
the default `.cache/local-runtime`. An occupied port is an error; the launcher
does not kill its owner. Logs and process ownership records are inside that runtime
directory. Startup failure cleans up the processes it started.

Type **latitude, longitude** and confirm each field, or focus a field and click
the map. Routes load automatically for all three modes; choose a vehicle and
priority/card. Editing text clears old results until the endpoint is confirmed.
Cards label moving-time ETAs, signal estimates, and provider-backed percentages
separately. Optional place search uses Nominatim through the data service;
map/coordinate input works without geocoding. Basemap tiles need internet access.

Local runtime evidence, browser prerequisites, and limitations are recorded in
[`docs/phase-2d-product-completion.md`](docs/phase-2d-product-completion.md).

### Existing Windows launcher

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

## Production-like local run

Use Docker Engine with Compose v2. Release images run CPU inference, one Python
worker per service, a compiled frontend, and one localhost gateway port. Backend
ports are internal. External ingestion and model training are disabled; no
credentials or dotenv files are required.
Do not increase worker counts or scale the stateful services to multiple replicas.

Prepare **trusted** existing Bengaluru GraphML, tower CSV, and seven-feature model
inputs. Pickle models can execute code: checksums detect changes but do not prove
authenticity, training provenance, or predictive quality. Original inputs stay
untouched; graph publication, databases and route caches use separate named volumes.

```bash
.venv/bin/python scripts/prepare-artifacts.py \
  --graph /path/to/bangalore.graphml --towers /path/to/bengaluru_towers.csv \
  --model /path/to/trusted/connectivity_model.pkl --output .cache/release-artifacts

docker compose --env-file config/production.example -p zlf-release config --quiet
docker compose --env-file config/production.example -p zlf-release build
docker compose --env-file config/production.example -p zlf-release up -d --wait --wait-timeout 600
.venv/bin/python scripts/production-smoke.py
```

Open **http://127.0.0.1:8080**. `config/production.example` documents artifact
location, port, image tag, and optional explicit CORS origins. Same-origin requests
need no CORS configuration, and changing the eventual hostname needs no frontend
rebuild. The frontend loads during backend warmup; gateway `/healthz` is liveness
and its Docker health check requires all three backend readiness endpoints.

Stop or restart **only the chosen Compose project**:

```bash
docker compose --env-file config/production.example -p zlf-release stop
docker compose --env-file config/production.example -p zlf-release up -d --wait --wait-timeout 600
docker compose --env-file config/production.example -p zlf-release restart prediction-service
docker compose --env-file config/production.example -p zlf-release logs --tail 100
```

`down` preserves named volumes unless explicitly requested otherwise. Do not delete
volumes to repair a loading error. Changed source artifacts require a new release
project/graph volume; startup rejects volumes belonging to different or unknown
inputs. Route caches account for graph and score generations. Docker Desktop
users must enable WSL integration and file sharing for their checkout.

With declared dependencies installed, `./scripts/release-check.sh` runs Python
tests, frontend unit/type/lint/build checks, Compose validation, and whitespace
checks. It does not install packages, commit, tag, or deploy. For browser checks,
start the real stack first and use existing installed Chromium:

```bash
cd services/visualization
E2E_RELEASE=1 E2E_BASE_URL=http://127.0.0.1:8080 npm run test:e2e
```

See [Phase 2E evidence and limitations](docs/phase-2e-production-release.md) for
image/resource measurements, browser and recovery results, and prerequisites.

## Version 0.1.0 release artifacts

The public deployment archive contains the tagged source, production Compose
files, and lock files. It intentionally does not contain the graph, tower CSV,
or model. Those validated inputs are in the private transfer archive
`zero-latency-f-0.1.0-private-runtime.tar.gz` (SHA-256
`1d476e87c08af8786857f53598b24b5dd7be19ac894bc58d518309a8ff96348b`). Keep it
private and transfer it manually for Phase 2F-B. Verify both the archive hash
and its internal `SHA256SUMS` before use. See [`DEPLOYMENT.md`](DEPLOYMENT.md),
[`deployment-artifacts-manifest.json`](deployment-artifacts-manifest.json), and
the GitHub Release manifest for artifact paths, provenance limits, and other
asset checksums. The visual basemap is not bundled and needs internet access.

## Routing modes

- `fastest` minimizes dimensionally correct travel time.
- `balanced` trades some travel time for connectivity and risk quality.
- `connected` strongly avoids weak/dead-signal edges when a viable alternative
  exists.

Vehicle profiles keep `scooter`, `bike`, `car`, and `truck` as separate API values.

## Data-service credentials and local tower data

OpenCellID credentials are optional. `OPENCELLID_KEYS` accepts a comma-separated rotation list and `OPENCELLID_TOKEN` is the single-key compatibility input. Both default to an empty value; the data service remains usable with prediction fallback when neither is configured. Never commit credential values.

Production Compose passes no OpenCellID credentials and disables ingestion.
`run-local.ps1` retains the optional development ingestion path and clears inherited
OpenCellID variables in non-data child processes.

Development may supply a local Bangalore CSV through `LOCAL_TOWER_CSV_PATH`.
Production mounts it read-only at `/artifacts/bangalore_towers.csv`, preserving
`unknown` provenance for available legacy inputs. Filenames do not establish a
provider or observation date. Never commit inputs or bake them into images.

Precomputed score metadata belongs under the shared cache path configured by
`REAL_SCORE_DIR`. The compatibility field `coverage_percent` means real-data
coverage; signal quality is reported separately as `good_signal_percent`.

## CPU and optional GPU acceleration

Production images use Python 3.11 CPU dependencies and omit CUDA/GPU packages.
GPU extras remain an optional local development path in `requirements-gpu.txt`;
release images omit those extras and their former build switch.

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
