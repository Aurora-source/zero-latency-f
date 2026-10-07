# Phase 2D — Product Completion

Validation date: 2026-10-06 UTC. Implementation baseline: `cb7b454` on
`codex/project-completion`, plus the complete uncommitted Phase 2C1 overlay.
This report concerns the local product only. Phase 2E is **Production Release**;
no deployment, public exposure, container startup, or server access occurred.
Status: **complete for the local product**, with the external-provider,
resource and data/model quality limitations below.

## Scope

Complete the credential-free CPU local path through data, real model inference,
routing, the API proxy, and the browser. Make startup reproducible, protect
frontend request state, validate responsive interaction, and preserve the
existing routing objectives, vehicle restrictions, revisions, and provenance.

## Starting state

[Phase 2C1](phase-2c1-runtime.md) had validated 36 compatible Bengaluru routes and
189 Python tests. Prediction lacked ML packages; browser validation was pending.
Tower provenance was unknown, road metadata sparse, and graph-service RAM above
advisory limits. The three recorded processes were inspected and verified before
the Phase 2C1 shutdown helper stopped only those processes (4106, 4266, 4107).

`git status`, the actual diff, setup/runtime manifests, service sources, frontend,
and existing tests were reviewed. There is **no CI workflow** in this checkout.
The six line-ending-only changes were recorded by SHA-256 before editing, as were
all nine starting modified/untracked Phase 2C1 functional/report/test files.
Baseline copies and the original diff remain under `.cache/phase-2d/baseline/`.
No reset, restore, normalization, staging, or commit was used.

## Changes

- Pin prediction's CPU dependencies and include them in the Python test manifest.
  Remove mandatory LightGBM/full GPU-capable XGBoost from the default install.
- Serving loads one existing model, validates its seven features and a finite
  inference probe, uses bounded native threads, and serializes inference.
  Available tower files no longer trigger training or model rejection during
  ordinary startup. Missing/corrupt artifacts leave liveness available, readiness
  false, and inference explicitly unavailable. Request failures do not retrain.
- Validate prediction coordinates, length, segment counts and duplicate IDs;
  reject invalid output shape/nonfinite values and expose safe inference errors.
  Use India Standard Time for default model features rather than the host clock.
- Add `run-local.py`, the shared CPU/local-only mode of the existing developer
  launcher; expose it through `run-local.ps1 -LocalDataOnly`. Inputs are copied,
  dotenv/inherited credentials are excluded, startup waits for readiness in order,
  occupied ports are rejected, and ownership-checked shutdown stops only children.
  Persisted graph migration survives restart without overwriting its working copy.
  An immediate-restart probe exposed a false occupied-port result for TCP
  `TIME_WAIT`; the POSIX probe now matches Uvicorn's reuse behavior while still
  rejecting active listeners. Windows PowerShell's dry-run option remains honored.
- Bound frontend HTTP/body reads and warming retries; abort obsolete requests,
  ignore stale responses, clear old routes as soon as endpoint text changes, and
  guard location searches, device-location callbacks and late city context.
  Add visible service retry paths.
- Reject malformed successful route payloads instead of displaying zero-valued
  empty routes. Fix the corridor client to send required graph/score revisions.
- Make vehicle/mode/heatmap controls accessible by name and state. Fit controls
  to tablet/mobile screens, constrain inputs, use dynamic viewport height, and
  keep the route list scrollable. Preserve Header, CitySelector and stylesheet bytes.
- Label signal values as estimates; distinguish unknown provenance and
  provider-backed share on each card. Identify ETA as estimated moving time.
  Label the map legend and priority as estimates rather than measured strength
  or guaranteed coverage. Show prediction unavailability and heatmap failures separately.
- Real screenshots revealed CARTO's configured URLs returned **API key required**
  watermarks. Use standard OpenStreetMap raster tiles with visible attribution,
  without acquiring a key. [CARTO's key requirement](https://www.carto.com/basemaps/apikey/)
  and [OSM's interactive tile policy](https://operations.osmfoundation.org/policies/tiles/)
  explain this choice; this phase did not download an offline tile dataset.
- Browser traces revealed automatic reverse-geocoding CORS failures. Coordinate
  and map picks now retain coordinate labels. Explicit place search goes through
  the data service, with a provider timeout, one-request-per-second spacing,
  bounded caching, and a useful failure response. Add the matching Vite and
  repository gateway API route; no production-host Nginx was configured or started.
- Add backend regressions and extend existing Vitest tests. Add a small Playwright
  suite against the actual stack; fault injection is limited to error/loading tests.
- Bound retained corridor tower lists to **32 entries / 100,000 total records**;
  purge expired entries on insertion and serve larger corridors without retaining
  their lists. Previously only revisiting a corridor expired it. Current responses,
  provenance, ingestion single-flight locks, and graph/score publication are preserved.

## Prediction

The existing manifest already listed joblib, XGBoost and scikit-learn, but versions
were unpinned, `.venv` did not contain them, and `requirements-test.txt` omitted
prediction. The default manifest now pins:

```text
fastapi 0.115.6                  uvicorn 0.32.1
xgboost-cpu 3.2.0               scikit-learn 1.6.1
numpy 2.2.1                     scipy 1.14.1
joblib 1.4.2                    threadpoolctl 3.6.0
psutil 6.1.1
```

Only four missing wheels were installed into the existing Python **3.11.16**
`.venv`: XGBoost CPU (5.60 MB), scikit-learn (13.50 MB), joblib (0.30 MB), and
threadpoolctl (0.02 MB). No global Python installation, Torch, CUDA/NCCL, LightGBM,
model download or training was used. Optional GPU installation explicitly replaces
the CPU XGBoost package to avoid two distributions owning the same Python module.

WSL resolution for `files.pythonhosted.org` stalled normal uv installation.
Verified PyPI wheels were fetched using a process-local DNS answer and normal
hostname/TLS verification, checked against their PyPI SHA-256 values, and installed
with `uv pip --no-index`. No system resolver was changed. `uv pip check` passed
for all 50 installed distributions.

The supplied model was copied from the read-only laptop snapshot:

```text
services/prediction-service/models/connectivity_model.pkl
672,086 bytes; bare XGBRegressor; serialized XGBoost 3.2.0
7 features; 140 boosted rounds; stored CPU configuration
```

Its feature count matches the API and the snapshot source uses the same seven-feature
order. **Training dataset, training command, evaluation quality and calibration
cannot be established from the artifact.** It reports `data_source: unknown` and
`confidence: null`; inference remains estimated provenance. Loading is reproducible
with the matching XGBoost version; [XGBoost documents pickle compatibility limits](https://xgboost.readthedocs.io/en/stable/tutorials/saving_model.html).
Only trusted local pickles should be supplied. No fake model or trained result was
created, and the source artifact remains unchanged.

Actual model probes produced 0.6544162 and 0.1455340 for two different explicit
feature rows. Runtime normal/repeated/empty requests returned 200; invalid
coordinates and duplicate IDs returned 422; **16 concurrent requests returned
identical real inference**. A separate localhost:18003 probe returned health 200,
readiness/inference 503 four times with no model, then readiness/inference 200 four
times after restart with the existing artifact. Both probe processes were stopped.
Evidence: `prediction-runtime.json`, `prediction-recovery.json`, `model-probe.json`.

`PREDICTION_DEVICE=cpu`, `MODEL_THREADS=2`, `ALLOW_MODEL_TRAINING=0` are ordinary
local defaults. A fresh clone requires an actual compatible model; it is not
downloaded or fabricated by startup. Explicit training remains a separate operator
action, outside this phase.

## End-to-end runtime

Node **22.23.2** and the existing frontend dependency tree were used. Launch from
the repository root; inputs may be any trusted existing files on the D:-backed WSL
filesystem. Paths in application code are relative to the checkout, not a username.

```bash
rtk proxy env UV_CACHE_DIR=.cache/uv uv pip install --python .venv/bin/python -r requirements-test.txt
# In services/visualization, with Node 22 on PATH:
rtk proxy npm ci

# From repository root; no credentials or dotenv files are needed:
rtk proxy .venv/bin/python run-local.py \
  --runtime-dir .cache/local-runtime \
  --graph /path/to/existing/bangalore.graphml \
  --towers /path/to/existing/bengaluru_towers.csv \
  --model /path/to/trusted/connectivity_model.pkl
```

The concrete validation command reused Phase 2C1's ignored working graph and CSV:

```bash
rtk proxy .venv/bin/python run-local.py --runtime-dir .cache/phase-2d/runtime \
  --graph .cache/phase-2c1-20260906/graphs/bangalore.graphml \
  --towers .cache/phase-2c1-20260906/towers/bangalore_legacy_unknown.csv \
  --model .cache/phase-2d/models/connectivity_model.pkl --detach
```

Startup order: prediction:8003 → data:8001 → routing:8002 → Vite:5173.
All four `/ready` or frontend-root gates returned 200. One Uvicorn worker per
backend preserves process-local snapshot and publisher guarantees. Children receive
an explicit environment allowlist with local-only ingestion guards, CPU settings,
cache paths, and localhost URLs. No undocumented shell variables or dotenv values
are required beyond Node 22 on PATH and the project environment/artifacts.

The stack was stopped and restarted through the new scoped launcher, preserving
the graph identity and invalidating old score-generation route results. Local
working paths contain copied data, generated tower DB, model, route cache, logs,
and ownership records. Original Windows files and the laptop snapshot were not
modified. The existing unknown tower source remains the Phase 2C1 dataset, not a
new collection or a verified provider.

The graph identity remains `4e762aa11553433fadcfe493666fc841`. Data logged real model
inference for **227,047 segments**, with unknown model training source; routing
accepted matching graph/city-score identities. Route results preserve both city
and corridor revisions. A corridor 409 during score-refresh lag retains compatible
city estimates, with no fabricated provider-backed coverage or unlimited retry.

Place search initially returned **503 after 10.24 seconds**, with an explicit
map/coordinate alternative. A later identical data-service request recovered to
**200 in 8.56 seconds**, returning `[12.9755264, 77.6067902]` for `MG Road Bengaluru`.
No resolver or service configuration was changed to obtain recovery. This verifies
a bounded search result, not independently verified place-name accuracy. Basemap
requests are external interactive requests; no offline map availability is claimed.

A real desktop browser search for `MG Road Bengaluru` received and displayed
the same safe 503 after **12.30 seconds**, with no page errors. The browser deadline
is fifteen seconds so the provider's ten-second timeout (plus serialization/transport)
can deliver its useful fallback. Evidence: `geocode-browser.json` and screenshot.
The repeated provider failure and later actual API recovery are preserved in
`geocode-browser-recovery.json`, `geocode-exact-diagnostic.json`, and
`geocode-idle-runtime.json`.
Finally, the real desktop workflow confirmed `MG Road Bengaluru`, used the returned
origin coordinates, and displayed **all three successful car routes** in **14.38 s**
including routing. This used the actual provider result retained in the bounded
data-service cache, not a mock. No page errors occurred. The final estimate legend
and priority wording were visible. Evidence: `geocode-browser-success.json` and
`geocode-browser-success.png`; route payloads and both revision types are retained.

The final restart completed all readiness gates and twelve direct/proxy checks
returned **200**. The following localhost processes remain running:

| Service | Port | PID |
| --- | ---: | ---: |
| Prediction | 8003 | 15968 |
| Data | 8001 | 15977 |
| Routing | 8002 | 16059 |
| Vite | 5173 | 16167 |

Evidence: `final-readiness.json` and `runtime/processes.json`. The old Phase 2C1
processes and both earlier Phase 2D stacks were stopped through their scoped
launchers. No probe/model-test/browser/sampler process is intentionally left running.
Stop only the recorded stack from the repository root:

```bash
rtk proxy .venv/bin/python run-local.py --runtime-dir .cache/phase-2d/runtime --status
rtk proxy .venv/bin/python run-local.py --runtime-dir .cache/phase-2d/runtime --stop
```

## Browser validation

Playwright **1.58.2** was added to the existing frontend quality tools. No browser
framework existed previously. Chromium headless **145.0.7632.6** runs against the
real local APIs. The downloader did not recognize Ubuntu 26.04, then stalled on a
CDN transfer. The matching Ubuntu 24.04 bundle was downloaded directly from the
browser vendor with TLS verification and ZIP integrity checks, inside ignored WSL
storage. Three absent libraries (`libnspr4`, `libnss3`, `libasound2t64`) were checked
against signed APT-list SHA-512 metadata and extracted locally; no system package
or unrelated service was modified. This is observed compatibility, not official
Playwright support for Ubuntu 26.04.

Use ordinary Playwright prerequisites on a supported host. This validation used:

```bash
# Run from services/visualization after the real stack is ready.
rtk proxy env PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 \
  PLAYWRIGHT_BROWSERS_PATH="$PWD/../../.cache/phase-2d/browsers" \
  LD_LIBRARY_PATH="$PWD/../../.cache/phase-2d/browser-libs/usr/lib/x86_64-linux-gnu" \
  TMPDIR="$PWD/../../.cache/phase-2d/runtime/tmp" npm run test:e2e
```

The suite covers four viewport projects: desktop **1440×900**, laptop **1280×720**,
tablet **768×1024**, mobile **390×844**. Each exercises actual endpoint confirmation,
four vehicles, three priority modes, route cards/ETA/distance/provenance, rendered
map/canvas and loaded raster tiles, repeated heatmap toggles, theme toggle, and
horizontal-overflow checks. Error scenarios cover invalid coordinates, same-node
no-route 422, recovery, editing endpoints clearing routes, controlled prediction
unavailability, warming 202, proxy HTML 502, and unavailable-city-list retry.
Only deliberate fault scenarios intercept responses; every successful route uses
the real routing/data/model stack.

Normal-flow tests inspect page errors, error-level console output, failed requests
and HTTP errors. Canceled obsolete/map-tile requests are expected and distinguished
from failures. Deliberate 502/503 tests naturally produce explained HTTP errors.
Screenshots and response/revision evidence remain under ignored
`browser-results/`; preliminary failing screenshots/traces were preserved separately
as `browser-results-attempt1/` and `browser-mobile-focused-attempt1/`.

All **16 initial scenarios passed in 9.3 minutes**. Four additional real map-pick
and explanation-scroll scenarios passed in **2.8 minutes**, one per viewport.
They focus each endpoint field, pick actual map points, obtain real routes, and
open/close all three explanations, including off-screen mobile cards. Screenshots
remain in `browser-interaction-results/`. Tablet/mobile screenshots were inspected:
the raster map and joined colored route are visible, with controls fitting the
viewport and route details reachable by scrolling. No design overhaul was made.
This is Chromium viewport validation, not Safari/Firefox,
a physical touchscreen, screen-reader certification or an accessibility audit.

## Routing regression

Routing-engine source is **byte-identical to the Phase 2C1 starting overlay**.
Vehicle access, directed/parallel edge selection, speed conversions, objectives,
ETA arithmetic, cache schema 8, atomic persistence, revision matching and immutable
request snapshots were preserved. Data's Phase 2D changes add explicit
geocoding and bound tower-list retention; graph/score publication behavior is unchanged.

Focused coverage included vehicle legality, fastest travel time, speed fallback,
parallel edges, no-route responses, concurrent loads/requests, graph/score revisions,
cache invalidation, and time transitions. Browser route switching validates the
same real central Bengaluru pair across all four profiles and modes. Comparisons
do not mix city/corridor score generations or infer road legality from a good UI.
The previous three-pair 36-route experiment was not needlessly repeated because
route-selection code/weights were unchanged; enabling actual model scores can
change estimated connectivity and its preferred route, as intended.

An independent GraphML audit of **58 captured successful browser responses**, covering
all **12 vehicle/mode combinations**, computed `sum(length_m × 3.6 / speed_kph) / 60`
from the selected edge IDs, road speed tags/fallbacks and vehicle caps, without
calling routing cost functions. Every ETA matched at the API's one-decimal precision;
every adjacent signal-edge join was within 0.01 m and every graph identity matched.
City and corridor score revisions were retained separately and no mixed-generation
score comparison was made. Evidence: `browser-route-audit.json` and four
`browser-evidence-*.json` files. Six repeated car/fastest requests also returned
200, 2.9 minutes, and identical graph/city/corridor identities.

## Tests

Backend commands were run from the repository root with
`PYTHONDONTWRITEBYTECODE=1` and `TMPDIR` pointing to the ignored runtime `tmp` directory.

| Command | Actual result |
| --- | --- |
| `rtk proxy .venv/bin/python -m pytest -q tests/test_prediction_runtime.py tests/test_prediction_revisions.py` | 23 passed during implementation |
| `rtk proxy .venv/bin/python -m pytest -q tests/test_local_launcher.py tests/test_data_resource_limits.py tests/test_data_concurrency.py tests/test_data_revisions.py` | 39 passed, 28 deprecation warnings, 1.88 s |
| `rtk proxy .venv/bin/python -m pytest -q` | **225 passed, 116 deprecation warnings, 4.13 s** |
| `rtk proxy env UV_CACHE_DIR=.cache/uv UV_NO_CONFIG=1 uv pip check --python .venv/bin/python` | 50 distributions compatible |
| `rtk proxy docker compose --env-file /dev/null config --no-interpolate --no-env-resolution --quiet` | Passed, exit 0 |

Frontend commands were run from `services/visualization`, with
`NPM_CONFIG_USERCONFIG=/dev/null` and `NPM_CONFIG_GLOBALCONFIG` pointing to an ignored
absent file. Browser environment prerequisites are listed above.

| Command | Actual result |
| --- | --- |
| `rtk proxy npm run test -- --run` | **36 passed, 4 files, 2.14 s** |
| `rtk proxy npm run typecheck` | Passed, exit 0 |
| `rtk proxy npm run lint` | Passed, exit 0 |
| `rtk proxy npm run build` | Passed, 2,171 modules, 432 ms |
| `rtk proxy npm run test:e2e` (initial four scenarios) | **16 passed**, 9.3 min |
| `rtk proxy npm run test:e2e -- --grep 'map-picked' --reporter=list --output=../../.cache/phase-2d/browser-interaction-results` | **4 passed**, 2.8 min |
| `rtk proxy npm run test:e2e -- --project=desktop --grep 'real routes,' --reporter=list --output=../../.cache/phase-2d/browser-final-results` | **1 post-restart recheck passed**, 1.9 min |

The full Python count increased from 189 by 36 regressions; no tests were removed.
The last full run followed the cache/restart fixes. An earlier 219-test checkpoint
was superseded when those concrete defects required additional tests.
Python warnings concern existing FastAPI `on_event` deprecation, not failures.
The build contains JS 580.86 kB (177.25 kB gzip), CSS 115.47 kB (22.73 kB gzip);
the existing >500 kB bundle warning remains. No dotenv resolution, image build,
container startup, global package installation or CI execution occurred.
`git diff --check` passed, including a separate whitespace check for new untracked
Phase 2D files. Six unrelated line-ending files and six unchanged C1-only files
matched their recorded byte hashes; four read-only source data files and the
snapshot model remained unchanged. The model input/runtime copies match its hash.
Evidence: `final-integrity.json`. Nothing is staged, HEAD remains `cb7b454`, and
runtime/browser/model artifacts are ignored.

Earlier frontend failures were invalid test fixtures under the
stricter parser and accessible-name assertions; no meaningful cases were deleted.
Preliminary browser failures exposed the actual basemap/CORS defects and source
reload/startup races, all retained as evidence rather than reported as successful.

## Resource usage

Complete CPU runtime is sampled once per second using psutil, with no telemetry
service or external telemetry added. The stable four-service run was sampled for
**1,200 samples / 20 minutes**, including actual route and browser requests:

| Service | Initial idle RSS (MiB) | Sampled request/browser peak (MiB) | After browser use (MiB) |
| --- | ---: | ---: | ---: |
| Prediction | 246 | 246 | 246 |
| Data | 2,215 | 2,359 | 2,360 |
| Routing | 2,110 | 2,663 | 2,640 |
| Vite | 228 | 281 | 265 |

These are process RSS observations, not hard limits or shared-page-adjusted totals;
the later steady stack totals roughly **5.4 GiB** excluding browser/tool processes.
Six repeated compatible car/fastest requests took 0.63–1.65 s: prediction/data/routing
RSS stayed at about 246/2,360/2,640 MiB, with Vite changing less than 1 MiB. This
short probe did not show continued growth; it is not a long-duration leak proof.
Evidence: `resource-summary.json`, `resource-samples.jsonl`,
`repeated-route-resources.json`. The verified sampler exited and is not left running.
An earlier Vite session reached 885 MiB through many config/source reloads; the
clean session figures above are the representative runtime measurement.
After the final retention/restart fixes, idle RSS was approximately **249 / 2,216 /
2,126 / 234 MiB** (prediction/data/routing/Vite), and after the real desktop workflow
approximately **249 / 2,272 / 2,485 / 281 MiB**. `final-restart-idle.json` and
`final-readiness.json` record those separate observations.

Straightforward duplication was removed from prediction: serving does not load
tower training arrays, retrain automatically, reload the model per request, or
spawn GPU workers. One model instance and bounded native threads were observed.
Existing route/tile caches and the new geocoder cache are bounded. The corridor
tower-list cache also now has entry, record and expiry limits; the regression checks
prove eviction does not truncate a current response or alter unknown provenance.
Data and routing
still retain separate graphs and score/weight structures; changing that ownership
would exceed this phase. Advisory RAM limits are still exceeded. These observations
do not establish capacity on the future four-core/12-GB deployment target.

## Remaining limitations

- **Data quality:** 122,409 legacy Bengaluru tower records have unknown provider,
  observation dates and RF calibration. Heuristic/model scores are not measured
  coverage; 0% provider-backed share does not mean zero numerical estimates.
- **Map legality/topology:** the 71,618-node/227,047-edge driving graph lacks much
  vehicle, turn, barrier, speed and conditional metadata. Cycling links omitted
  by its import cannot be reconstructed. A successful route is not verified legal
  suitability, traffic ETA, RF continuity, or production autonomy readiness.
- **Model quality:** inference now runs, but its training/evaluation provenance and
  confidence cannot be recovered. A fresh clone needs a genuine compatible artifact.
- **External services:** place search showed intermittent bounded provider failures
  and later real recovery; basemap needs internet. Search coordinates and RF/road
  quality have no independent ground truth here. Offline map is not provided.
- **Resources:** graph-service RAM exceeds advisory limits; large initial/demo or
  repeated route computations can be slow. Single-process guarantees remain explicit.
- **Browser scope:** Chromium headless and representative viewports only; other
  engines, physical devices and detailed accessibility remain manual checks.
- **Runtime/build scope:** PowerShell mode was inspected but PowerShell is absent.
  Compose configuration passed; containers/images and gateway runtime were not run.
  No CI workflow exists here. No production readiness/deployment claim is made.

## Changed files

Phase 2D functional/runtime files:

- `README.md`, `requirements-test.txt`, `run-local.py`, `run-local.ps1`.
- `gateway/nginx.conf` (API route source only).
- `services/data-service/{main.py,geocoding.py,Dockerfile}`.
- `services/prediction-service/{main.py,requirements.txt,requirements-gpu.txt,Dockerfile}`.
- `services/visualization/app/{App.tsx,lib/api.ts}`.
- `services/visualization/app/components/{MapView.tsx,RouteCard.tsx,ConnectivitySlider.tsx,Legend.tsx}`.
- `services/visualization/{package.json,package-lock.json,vite.config.ts,vitest.config.ts,tsconfig.json,eslint.config.mjs,playwright.config.ts}`.

Phase 2D tests: `tests/{test_prediction_runtime.py,test_prediction_revisions.py,test_local_launcher.py,test_geocoding.py,test_data_resource_limits.py}`,
`services/visualization/tests/{App.test.tsx,api.test.ts}`, and
`services/visualization/e2e/product.spec.ts`.

Documentation: `docs/api-contract.md`, this report, and the local-run README additions.
Phase 2C1 changes remain present, including its report and local-runtime tests;
unchanged C1-only files are not Phase 2D functional edits. The six line-ending-only
files remain unchanged: the three data scripts, Header, CitySelector and index.css.
No generated cache, model, graph, browser, library, log or screenshot is staged.

## Manual checklist

Before authorizing Phase 2E:

- Open localhost:5173 in your usual browser; check card readability, scrolling,
  endpoint picking and vehicle/mode selection at your actual screen size.
- Review representative real map routes and detours with local knowledge;
  independently check road/truck/cycling legality and metadata gaps.
- Confirm unknown signal/model provenance remains visible; obtain actual provider
  and model-evaluation evidence before asserting measured coverage or confidence.
- Check public place search on your network; verify returned named-place locations
  against local knowledge and keep coordinate/map fallback available.
- Review model artifact ownership/feature schema and fresh-clone setup; retain a
  compatible trusted model with reproducible training/evaluation records.
- Review memory/latency on constrained CPU hardware and production release scope.
- Review only the Phase 2D/C1 functional diff when committing manually; preserve
  unrelated line endings and keep runtime artifacts ignored.

The next phase is **Phase 2E — Production Release**. It was not started.
