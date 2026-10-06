# Phase 2C1 — local runtime and initial Bengaluru checks

Implementation baseline: `cb7b454` on `codex/project-completion`. Initial startup
observations were collected on 2026-09-06; services had exited before continuation.
The final route matrix and validation below were collected on 2026-10-06 UTC.
This phase stops here. The results establish local integration behavior, not good
routes, calibrated traffic ETAs, or verified road legality on Bengaluru streets.

## Startup path and isolation

Compose remains the production runtime. The developer launcher is `run-local.ps1`;
it can install dependencies and normally loads the data-service environment file,
so it was inspected but not executed. PowerShell is unavailable here. The required
local routing path is data-service (8001), routing-engine (8002), and the
authoritative `services/visualization` Vite frontend (5173). Prediction (8003) is
the optional scoring dependency in this degraded validation; telemetry (8004)
and Nginx are unnecessary for the Vite proxy flow.

Existing environments: Python **3.11.16** in `.venv`, Node **22.23.2**, and the
installed frontend dependency tree. Data/routing imports are available.
Prediction fails at import with `ModuleNotFoundError: No module named 'joblib'`;
`xgboost` and `scikit-learn` are also absent, as are optional LightGBM/Torch.
The initial prediction process exited before model loading or training. No
prediction model was downloaded, loaded, or trained. No dependencies were installed.

All children received an explicit environment allowlist, without inherited
credentials or proxy settings. `LOCAL_DATA_ONLY=1` skips credential/dotenv loading,
external graph/tower requests, and background ingestion. `ENV_FILE_PATH=/dev/null`
adds a separate configuration safeguard. Vite already has `envDir: false`.
Services bind only to `127.0.0.1`, use one process each, and run on CPU.

Runtime directory, ignored by Git:

```text
/home/rikon/code/zero-latency-f/.cache/phase-2c1-20260906/
  graphs/                  migrated working GraphML
  towers/                  working SQLite copy and derived local CSV
  scores/ models/          empty; no accepted score envelope or usable model
  logs/ artifacts/         service logs, HTTP responses, route matrix, audits
  launch-env.json           explicit, credential-free child environment
  processes.json           exact commands, creation times, and owned PIDs
  stop-local.py             scoped shutdown helper
```

The directory is on `/dev/sdd`, ext4, inside the D:-backed WSL filesystem.
The original Windows project was not accessed. The laptop snapshot was read-only.
Source GraphML, database, WAL/SHM, and the six pre-existing line-ending changes
retain their initial SHA-256 hashes (`artifacts/source-integrity.json`).

Equivalent startup commands, run from the repository root in separate terminals
after the working copies described below exist:

```bash
phase2c1_root=/home/rikon/code/zero-latency-f
phase2c1_run="$phase2c1_root/.cache/phase-2c1-20260906"
phase2c1_node=/home/rikon/.nvm/versions/node/v22.23.2/bin
phase2c1_exec() {
  rtk proxy env -i PATH="$phase2c1_root/.venv/bin:$phase2c1_node:/usr/bin:/bin" \
    LANG=C.UTF-8 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 \
    TMPDIR="$phase2c1_run/tmp" XDG_CACHE_HOME="$phase2c1_run" \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 CUDA_VISIBLE_DEVICES= \
    SUPPORTED_CITIES=bangalore DEFAULT_CITY=bangalore LOCAL_DATA_ONLY=1 \
    ENV_FILE_PATH=/dev/null APP_CACHE_DIR="$phase2c1_run" \
    GRAPH_CACHE_DIR="$phase2c1_run/graphs" OSMNX_HTTP_CACHE_DIR="$phase2c1_run/osmnx-http" \
    TOWER_CACHE_DB_PATH="$phase2c1_run/towers/tower_cache.db" \
    LOCAL_TOWER_CSV_PATH="$phase2c1_run/towers/bangalore_legacy_unknown.csv" \
    LOCAL_TOWER_PROVENANCE=unknown TOWER_DIR="$phase2c1_run/towers" \
    REAL_SCORE_DIR="$phase2c1_run/scores" MODEL_DIR="$phase2c1_run/models" \
    HOTSPOT_CACHE_PATH="$phase2c1_run/hotspots.json" \
    ROUTE_CACHE_PATH="$phase2c1_run/route_cache.json" \
    PREDICTION_SERVICE_URL=http://127.0.0.1:8003 DATA_SERVICE_URL=http://127.0.0.1:8001 \
    "$@"
}

# Terminal 1; wait for http://127.0.0.1:8001/ready to return 200.
phase2c1_exec "$phase2c1_root/.venv/bin/python" -m uvicorn main:app \
  --app-dir "$phase2c1_root/services/data-service" --host 127.0.0.1 --port 8001 --workers 1
# Terminal 2; wait for http://127.0.0.1:8002/ready to return 200.
phase2c1_exec "$phase2c1_root/.venv/bin/python" -m uvicorn main:app \
  --app-dir "$phase2c1_root/services/routing-engine" --host 127.0.0.1 --port 8002 --workers 1
# Terminal 3, with services/visualization as the working directory.
phase2c1_exec "$phase2c1_node/node" "$phase2c1_root/services/visualization/node_modules/vite/bin/vite.js" \
  --host 127.0.0.1 --port 5173 --strictPort
```

These commands do not invoke prediction startup. Restoring that service also
requires preventing its automatic training path when a compatible model is absent.
The actual background launches used the same settings, redirected logs to the
ignored directory, and recorded each process in `processes.json`.

## Available data and legacy compatibility

The graph source was
`/home/rikon/code/zero-latency-f-laptop-snapshot/cache/graphs/bangalore.graphml`
(130,039,019 bytes). It identifies OSMnx 2.0.2, creation date 2026-04-18, and
already-simplified/consolidated topology. It contains **71,618 nodes and 227,047
directed edges**, approximately latitude 12.834870–13.142476 and longitude
77.467400–77.776914. Data-service assigned a durable revision and atomically
republished only `graphs/bangalore.graphml` in the working directory. Subsequent
service restarts retained that identity:

```text
graph_revision = 4e762aa11553433fadcfe493666fc841
```

All edges have normalized `oneway` and `reversed` fields. Only **6,025** have
`maxspeed`, and **3,108** have generic `access`. The edge inventory contains no
vehicle-specific access/speed/direction tags, truck dimensions, or conditional
restriction fields. Original OSM one-way distinctions and restriction relations
cannot be recovered from this simplified GraphML. Bicycle-only links excluded
from the original drive graph cannot be invented. These checks preserve the
represented directions and existing legality filters; absent tags do not establish
permission, especially for bikes and trucks.

Tower source: the repository's existing
`services/data-service/data/tower_cache.db`, with its WAL/SHM copied before any
SQLite operation. The working copy contains **122,409 Bengaluru records**:
52,952 GSM, 29,248 LTE, and 40,209 UMTS. Cache timestamps span
**2026-04-18T19:02:24Z–2026-04-19T02:52:00Z**. Tower ranges span 500–87,296 metres;
the existing scoring heuristic caps ranges at 2,000 metres.

The legacy database has no provider column. Schema migration added `source` with
`unknown` only to the working copy. Neither record shape nor a historical filename
establishes that these rows came from OpenCellID or TRAI. A derived CSV containing
the existing Bengaluru rows allows local queries without re-ingestion or timestamp
renewal. `LOCAL_TOWER_PROVENANCE=unknown` remains explicit. The original collection
provider, per-record observation dates, RF measurements, completeness, and current
coverage cannot be recovered. All **868** cache tiles remain stale under the
existing seven-day policy; fresh real coverage and ingestion progress are **0%**.
No legacy score cache was relabeled with the working graph revision.

## Integration defects fixed

- Added `LOCAL_DATA_ONLY`: startup cannot open dotenv/credential state or launch
  ingestion; missing local graphs take the existing bounded retry/error path
  without geocoding/downloading; local tower queries cannot fall through to HTTP.
- A real proxy request initially returned `source: unknown` with **100% real
  coverage**. Tower, corridor, city-score, persisted-score, cache-status, and route
  summaries now count only established `opencellid`/`trai` sources as real coverage.
  Unknown numerical estimates remain usable and retain their unknown labels.
  An unknown selected edge also prevents a misleading aggregate `hybrid` label.
- Bumped route-cache schema to **8**, invalidating previously persisted percentages
  calculated under the old unknown-source behavior.
- Changed the Linux local launcher from four routing workers to one, matching the
  current process-local snapshot, single-flight, and cache-lock guarantees.

Vehicle filtering, route objectives, speed/time calculations, revision admission,
and snapshot ownership were preserved. No frontend source changed in this phase.

## Startup, readiness, and proxy observations

- Data `/health` returned 200 during warming; `/ready` and Vite's city-context
  proxy returned 503 until the graph became ready. Prediction failure did not
  prevent data readiness; its neutral city base remains `ml_synthetic` without
  claiming that a model actually executed.
- Final cold routing readiness was observed at about **56 seconds** (initial run
  about 60 seconds). The real frontend API function received a loading response
  with a five-second retry delay. Direct route admission returned **202** and
  `Retry-After: 5` while `/ready` was 503.
- Vite `/api/cities`, `/api/city-context/bangalore`, `/api/scores/source/bangalore`,
  and `/api/cache-status` returned 200 after readiness.
- The frontend's actual TypeScript API module was transpiled with the installed
  TypeScript package and exercised against Vite from Node. It parsed loading,
  success, formatted distance/ETA, unknown provenance, zero real coverage, and
  the explicit no-route error. This is client/proxy validation, not browser rendering.
- `/api/tiles/bangalore/14/11723/7596.mvt` returned 200, the MVT content type,
  **78,424 bytes and 882 decoded road features**, with `unknown`/`ml_synthetic`
  provenance. Layer display/toggle behavior still needs browser validation.
- A mismatched graph revision returned **409**; a legacy corridor payload without
  required revisions returned **422**. Identical endpoints returned the documented
  **422 no-route** detail; an unsupported vehicle returned 422 and Chennai returned
  404. No synthetic road fallback bypassed those responses.

## Three endpoint pairs and compatible route results

Endpoints were selected from actual loaded graph nodes, without external geocoding:

| Pair | Area | Origin `[lat, lon]` / node | Destination `[lat, lon]` / node |
| --- | --- | --- | --- |
| P1 | Central | `[12.975056, 77.590304]` / 9303 | `[12.979822, 77.600917]` / 9586 |
| P2 | East | `[12.968687, 77.644844]` / 14319 | `[12.988037, 77.697158]` / 6554 |
| P3 | South | `[12.918884, 77.579787]` / 1028 | `[12.942492, 77.621331]` / 21768 |

Exact request coordinates and complete responses are in
`artifacts/route-pairs.json` and `artifacts/route-matrix.json`. Each batch sent
12 concurrent requests, one per vehicle/mode combination. The compared results
share graph, city-score, and corridor-score revisions within each pair and were
collected during the Bengaluru **day** bucket. No comparisons cross pair, revision,
or time inputs. Real nighttime routes were not checked.

| Pair / accepted batch | City score revision | Corridor score revision |
| --- | --- | --- |
| P1 / attempt 1 | `f4f19beaaabd43538dccdac5ce31f63e` | `ad90dceb4877c0ce38bcd31cbdb93547a112fc27cb57a0c7aa7b7187b17a9e30` |
| P2 / attempt 2 | `767c473281b94486af9c3265b7665d2a` | `329ea4d0c5bed2057e2df510b9fb43bbe7b73c7898fa1d46b658e5db65361986` |
| P3 / attempt 2 | `89e025a538584310a25964d3ef012ec4` | `6f535bc15d51240a9e4a45b9576057f8116f8983eca3d14c2889ee024b859308` |

Every cell below is **successful HTTP 200**, expressed as **distance km / ETA min**.
Distance is an independent haversine sum of the returned geometry; ETA is the
service's moving-time estimate.

| Pair | Vehicle | Fastest | Balanced | Connected |
| --- | --- | --- | --- | --- |
| P1 | scooter | 2.005 / 3.2 | 2.005 / 3.2 | 2.005 / 3.2 |
| P1 | bike | 1.793 / 6.0 | 1.793 / 6.0 | 1.793 / 6.0 |
| P1 | car | 2.005 / 2.9 | 2.005 / 2.9 | 2.005 / 2.9 |
| P1 | truck | 2.005 / 2.9 | 2.005 / 2.9 | 2.005 / 2.9 |
| P2 | scooter | 9.599 / 15.4 | 9.424 / 15.9 | 9.424 / 15.9 |
| P2 | bike | 8.143 / 27.1 | 8.143 / 27.1 | 8.143 / 27.1 |
| P2 | car | 9.599 / 14.5 | 9.599 / 14.5 | 9.599 / 14.5 |
| P2 | truck | 9.599 / 14.5 | 9.599 / 14.5 | 9.599 / 14.5 |
| P3 | scooter | 7.620 / 10.9 | 7.620 / 10.9 | 8.090 / 11.3 |
| P3 | bike | 7.266 / 24.2 | 7.266 / 24.2 | 7.266 / 24.2 |
| P3 | car | 7.620 / 9.9 | 7.620 / 9.9 | 7.620 / 9.9 |
| P3 | truck | 7.620 / 9.9 | 7.620 / 9.9 | 7.620 / 9.9 |

For **all 36 compared routes**: average connectivity **0.850**, signal **85.0%**,
good-signal edges **100.0%**, established real coverage **0.0%**, provenance
**`unknown`**. Corridor tower counts were **7,664 / 21,463 / 33,001** for P1/P2/P3;
these are records in the queried corridor, not independent observations per route.
The uniform 0.85 follows the existing best-in-range LTE heuristic. It provides no
evidence that connected mode improves measured connectivity.

P2 and P3 each initially completed 12 requests with stale city-score generations
relative to data-service feedback. Their corridor overrides were rejected, and
responses honestly retained the captured neutral base (`ml_synthetic`, typically
0.5, zero current real coverage, null corridor revision). Those **24 additional
successful fallback responses** are recorded but excluded from the table/comparisons.
After one 90-second wait for the existing periodic refresh, each second batch had
matching revisions. The harness capped attempts at three; no unlimited retry was
introduced. Thus the matrix contains **60 completed HTTP 200 requests**, including
36 compatible tower-derived results and 24 explicitly degraded results.

All 60 paths had **0 metres between adjacent signal-segment endpoints** and snapped
to the requested graph nodes. A separate GraphML audit found all 351 unique edges
used by the 36 compared routes in the represented travel direction. Independent
`length * 3.6 / selected_vehicle_speed` sums matched every reported rounded ETA.
Fastest was never slower than balanced/connected for the same compatible inputs.
**1,650 of 1,983 selected edge occurrences** used road-class fallback speeds.
This validates the current arithmetic, not those speed assumptions or actual traffic.

Detours worth checking on a real map: P2 motor routes span about 9.60 km against
6.06 km straight-line distance; P3 scooter connected takes 8.09 km versus the
7.62 km fastest path, with the same reported signal quality. No selected path
repeated a node, and no disconnected geometry was detected. Sparse access tags,
drive-only topology, turn restrictions, barriers, and truck constraints prevent
calling any of these routes legally verified or representative of city-wide quality.

## Resource usage and remaining blockers

The validation host exposes **32 logical CPUs and about 15.23 GiB RAM**. GPU
packages/runtime were absent. Measurements are from the 267 one-second samples
during 2026-10-06 12:18:31–12:22:58 UTC:

| Process | Peak sampled RSS MiB | CPU seconds during matrix |
| --- | ---: | ---: |
| Data | 2,176.91 | 31.92 |
| Routing | 2,437.67 | 169.96 |
| Vite | 148.18 | 0.11 |

Later data RSS was about 2,202 MiB. The configured `MAX_RAM_MB` values (1,536/2,048)
are advisory, not enforced caps, and both backends exceeded them. Concurrent
12-request batches completed in approximately **8.3–29.6 seconds**. A 32-core host
does not establish performance or memory safety for the production four-core,
12-GB machine. Missing scikit-learn caused logged OSMnx nearest-node exceptions;
the existing NumPy fallback served these exact-node inputs. Its approximate
coordinate-distance behavior for arbitrary off-node points remains unvalidated.

Remaining requirements and smallest next actions:

- Prediction: supply the missing existing ML dependencies and a compatible local
  model through a separately authorized environment repair; guard automatic training
  before attempting startup. The snapshot has a model file, but its compatibility
  and source were not examined by loading it.
- Browser: use an already available browser outside this environment, or separately
  authorize tooling installation later. No browser engine, Playwright, or Puppeteer
  is installed here. Rendering, controls, map interaction, and browser console
  behavior remain pending.
- Data: obtain provider/observation evidence before changing `unknown` labels. Do
  not make stale timestamps current or attach legacy score files to a new graph ID.
- Performance/quality: investigate graph duplication, refresh/corridor work,
  missing speed/access topology, uniform heuristic scores, and real-map detours
  in a separate phase. Multi-process/replica coordination remains unsupported.

## Precise manual browser checklist — pending

1. Open `http://127.0.0.1:5173/`, confirm Bengaluru is selectable, and inspect the
   console/network panels for errors. Enter P1 coordinates in the origin and
   destination inputs as comma-separated numbers without brackets (for example,
   `12.975056, 77.590304`) and use **Confirm origin / Confirm destination** (or Enter).
   Numeric coordinates avoid search geocoding, although labels/basemaps may still
   make their existing external requests.
2. Focus the origin field, click a map point, then repeat for destination. Confirm
   the correct marker moves and old route results are replaced after endpoint changes.
3. Select scooter, bike, car, and truck using the vehicle buttons on the right.
   Inspect `/api/route` payloads for the distinct values and ensure no old-vehicle
   response replaces a newer selection.
4. Select the fastest, balanced, and connected route cards. Confirm highlighting,
   coordinates, distance, ETA, explanations, and signal-segment colors agree with
   the selected card. Inspect response graph/score/corridor revisions before any
   comparison; the frontend currently does not expose these IDs in its formatted model.
5. Toggle **Heatmap**, pan, and zoom. Confirm relative `/api/tiles/...` requests,
   road layers, spinner completion, and visibility when toggled off. Unknown
   signal provenance and 0% real coverage must remain visible despite green roads.
6. During a scoped routing restart, confirm the loading message/countdown honors
   `Retry-After: 5` and recovers after readiness. Exercise network failure with
   browser devtools request blocking, then unblock and use **Retry**.
7. Set identical origin/destination coordinates. Confirm the explicit no-route
   error, then restore P1 and verify recovery. Repeat the coordinate/vehicle/mode
   flow for P2/P3; retain screenshots/console/network artifacts in the ignored directory.

## Tests and changed files

Focused final regressions:

```bash
rtk proxy env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_local_runtime.py tests/test_vehicle_routing.py
# 72 passed, 12 FastAPI deprecation warnings
```

The earlier broader focused run passed 89 cases. The complete Python suite ran
once at completion: **189 passed, 66 existing FastAPI lifecycle deprecation
warnings, 2.45 seconds**. It includes 17 new regression cases for local-only
startup/network guards, missing data, unknown coverage, legacy schema migration,
persisted-score metadata, and route provenance. Existing concurrency/revision and
vehicle/cost cases also passed.

```bash
rtk proxy env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
rtk proxy docker compose --env-file /dev/null config --no-interpolate --no-env-resolution --quiet
rtk git diff --check
```

Compose configuration validation passed without accessing dotenv. Whitespace checks
passed, including the new files. Frontend lint/type/build/unit checks were skipped
because no frontend files changed. Browser checks and PowerShell execution were
unavailable as described above. No container was built or started.

Changed files in this phase:

- `services/data-service/main.py`
- `services/data-service/tile_loader.py`
- `services/routing-engine/main.py`
- `run-local.ps1`
- `tests/test_local_runtime.py` (new)
- `tests/test_feature_integrity.py`
- `tests/test_vehicle_routing.py`
- `docs/api-contract.md`
- `docs/phase-2c1-runtime.md` (new)

The six original line-ending-only changes remain byte-identical. Nothing was
staged, committed, pushed, deployed, or sent to the remote server.

## Processes left running and scoped shutdown

At completion, these project processes remain bound to localhost:

| Process | PID | Port |
| --- | ---: | ---: |
| Data-service | 4106 | 8001 |
| Routing-engine | 4266 | 8002 |
| Vite | 4107 | 5173 |

Prediction has exited; telemetry, gateway, and containers were not started. Stop
only the recorded Phase 2C1 process groups with:

```bash
rtk proxy .venv/bin/python .cache/phase-2c1-20260906/stop-local.py --list
rtk proxy .venv/bin/python .cache/phase-2c1-20260906/stop-local.py
```

The helper checks PID creation time, exact command, working directory, and process
group ownership before sending SIGTERM. It skips exited/reused PIDs and does not
use broad port/name matching. Foreground launches from the example commands can
instead be stopped with Ctrl+C in their own terminals.
