# Phase 2E — Production Release

## Scope

Prepare and validate a CPU-only, production-style release locally. No server,
DNS, tunnel, public port, TLS, firewall, Git publication, or deployment was used.
Phase 2F has not started. Measurements below describe this checkout and Docker
Desktop, not the eventual 4-core/12-GB Ubuntu server.

Status: **complete for the locally validated production release**, with the
data/model, distribution-security and final-server limitations below.

## Starting state

[Phase 2D](phase-2d-product-completion.md) is the product baseline; see also
[Phase 2C1](phase-2c1-runtime.md) and the [API contract](api-contract.md).
HEAD is `cb7b454` on `codex/project-completion`. Existing C1/D work and six unrelated
line-ending changes were preserved. Baseline tests were 225 Python, 36 frontend,
20 browser scenarios and one restart recheck. Containers and the production
gateway had not been validated, and CI was absent.

The available model performs genuine seven-feature XGBoost CPU inference.
Tower provider/date, model training/evaluation/confidence, RF calibration, and
complete road restrictions remain unknown. Production packaging does not improve
those facts.

## Production architecture

```text
Browser -> 127.0.0.1:8080 -> Nginx:8080
                            |- compiled React frontend / SPA / assets
                            |- /api/route, /api/preload -> routing-engine:8002
                            |- data / tiles / geocode -> data-service:8001
                            |- /api/predict -> prediction-service:8003
Routing -> data-service -> prediction-service
Data -> graph publication volume (sole writer)
Routing -> same graph publication volume (read-only)
```

`docker-compose.yml` is the single authoritative production topology. There is
no Vite process or development source bind mount. Only the gateway has a host
port, bound to loopback. Services use an isolated application bridge and service
DNS. Outbound connectivity remains available for optional Nominatim geocoding;
browser basemap tiles also need internet. Telemetry is not required or included.

## Container changes

- Pin Python 3.11.16, Node 22.23.2 and Nginx 1.30.5 base images by digest. Install
  hashed, fully pinned Python locks and `npm ci` from the npm lock.
- Use root build contexts with a root `.dockerignore` excluding credentials,
  dotenv, datasets, models, caches, environments, dependencies, and build outputs.
  Backend images copy only their runtime source and bootstrap.
- Python runs as UID/GID 10001; Nginx runs as its packaged `nginx` user. Runtime
  root filesystems are read-only, capabilities are dropped, privilege escalation
  is disabled, `/tmp` is bounded, and `init` handles child reaping/signals.
- Keep one Python worker and one Nginx worker. The shared-state and revision
  guarantees depend on one process per Python service. Do not increase workers.
  Multiple replicas of these stateful services are also unsupported.
- Remove pip/setuptools from runtime images after installation. Apply available
  OS security updates at build time. OS repositories are intentionally not frozen:
  pinned application dependencies do not imply bit-identical future OS layers.
- Build gates check real dependency exports, nonempty/compilable Python source,
  credential-free service imports, nonempty frontend output and `nginx -t`.

Docker Desktop initially lacked usable WSL integration, and later disappeared
during builds. An interrupted cached data-image layer contained zero-byte source
and middleware files. The source checkout was intact. A targeted data-service
`--no-cache` rebuild repaired it; the new gates detect this failure. No global
Docker cache/image/volume pruning or unrelated-project shutdown was performed.
After WSL integration was restored, the normal production read-only bind mount
worked. An earlier ignored artifact-volume workaround is not required by the
release configuration.

## Production frontend

The multi-stage frontend image builds with Vite and serves only compiled output
with Nginx. Requests use relative `/api` paths; no developer hostname or public
domain is baked into the bundle. SPA deep paths fall back to `index.html`.
Missing assets return 404. HTML is revalidated; hashed assets are immutable for
one year, and text/JS/CSS/JSON responses support gzip.
An actual JavaScript asset returned `Content-Encoding: gzip`, the correct content
type/cache policy and all three security headers in the final gateway probe.

Lazy-load the map with a visible loading state. The previous 580.86-kB JS entry
is now **356.54 kB (112.31 kB gzip)** plus a **225.39-kB map chunk (65.93 kB gzip)**.
CSS is **115.47 kB (22.73 kB gzip)**. This removes the >500-kB chunk warning but
does not eliminate the total map dependency payload. Existing identity, controls,
request cancellation, stale-response guards and uncertainty labels remain.

## Gateway

The gateway uses an explicit API allowlist, Docker DNS with a 10-second refresh,
and variable upstream resolution so replacing a backend container does not
require restarting Nginx. Development test-route and memory endpoints are not
proxied. Backend 202/503 loading contracts remain intact. Upstream connection or
timeout failures become a concise JSON 503 with `Retry-After: 2`.

Connect timeout is 3 seconds, upstream read timeout 90 seconds, send timeout
30 seconds, client-body timeout 15 seconds and public request body limit 1 MiB.
The large city prediction batch goes directly between internal services rather
than through that public body limit. Overwrite forwarding headers and disable
Uvicorn trust of proxy headers. Set nosniff, frame denial and referrer policy;
merge header inheritance so nested asset/cache/error locations retain them.

## Configuration

Use [config/production.example](../config/production.example), explicitly via
`docker compose --env-file ...`; the release does not open dotenv files.

| Variable | Classification | Meaning |
| --- | --- | --- |
| `ARTIFACT_DIR` | Required operator input | Prepared trusted read-only directory; must exist |
| `GATEWAY_PORT` | Optional | Loopback host port, default 8080 |
| `RELEASE_TAG` | Optional | Local image tag, default `local` |
| `CORS_ORIGINS` | Optional | Empty for same-origin; otherwise explicit HTTP(S) origins without paths/wildcards |
| `APP_ENV`, `LOCAL_DATA_ONLY`, `ALLOW_MODEL_TRAINING`, `PREDICTION_DEVICE` | Production policy | `production`, `1`, `0`, `cpu`, checked by bootstrap |
| `SUPPORTED_CITIES`, `DEFAULT_CITY` | Production policy | Bengaluru only (`bangalore`) |
| Service URLs | Production policy | Container service names; host-local/credential-bearing URLs rejected |
| Artifact/cache/database paths | Production policy | Container-relative `/artifacts` and `/runtime`; declared in Compose |
| Worker/native thread and memory settings | Production policy | Explicit below; changing workers is unsupported |
| OpenCellID credentials, GPU extras, Vite overrides | Development only | Not passed into this release |
| Secrets | None required | No real tokens, passwords, host credentials or private URLs included |

## Artifacts and persistence

Run `scripts/prepare-artifacts.py` with existing trusted inputs and a **new** output
directory. It copies inputs without mutation and writes a schema-1 SHA-256
manifest. Bootstrap validates all three files before importing application code.
Hashes detect accidental changes, not authenticity. Pickle is executable: never
accept an untrusted model or trust a checksum supplied by an untrusted source.

Validated inputs were the C1 working Bengaluru GraphML, C1 legacy unknown tower
CSV and D's genuine model copy. They contain 71,618 nodes, 227,047 edges and
122,409 tower records; the model has seven features and 140 boosting rounds.

| Read-only input | SHA-256 |
| --- | --- |
| `bangalore.graphml` | `ca0c638be582c38a3aeacfc7f6afca7b183f9cec30b42ba6ea08c2abd3fe8ca9` |
| `bangalore_towers.csv` | `9a4647602dfa52bad14c98cb68021e06901399ace26f2c651f78ea44e3a218bc` |
| `connectivity_model.pkl` | `b701d3988b7b4dcba4360baccc8db84d9ead8d3953067eb505af2c4d0878ef7c` |

Data alone seeds `graph-publication` atomically and records the source graph hash.
The published graph can acquire revision metadata without invalidating its input
receipt. Restart preserves that publication. Changed/unknown input receipts
require a new release project/volume; never overwrite an old publication silently.
The validated graph revision is `4e762aa11553433fadcfe493666fc841`. Score updates
have separate revisions and invalidate route generations.

`data-runtime` holds the SQLite tower database, scores and bounded caches;
`routing-runtime` holds the atomic route cache; `prediction-runtime` provides
isolated writable state without modifying the model. Logs go to stdout/stderr
and Docker rotates 3 × 10 MiB per container. Temporary storage is 128 MiB per
container. Source models/towers/graphs are never baked into images. Existing
legacy tower fields cannot recover provider, observation date or RF calibration.

## Health/readiness

`/healthz` is gateway liveness. `/api/ready/{prediction,data,routing}` reports each
service's actual readiness. Prediction requires a compatible loaded model; data
and routing require their graph/publication state. Compose orders prediction,
data, then routing by readiness. Gateway starts independently so the compiled
frontend is available during warmup; its own Docker health check requires all
three services ready. Loading remains 202 with bounded retries; missing or
incompatible input is explicit, never relabelled as current real coverage.

## CI

[.github/workflows/ci.yml](../.github/workflows/ci.yml) adds:

- Python 3.11, hashed test dependency installation, full pytest and diff checks.
- Node 22.23.2, clean npm install, unit/type/lint/build checks.
- A four-image build matrix (maximum two simultaneous builds), with Compose
  validation. Builds require no private model or large production data.

Actions use stable major references, read-only repository permissions, dependency
caching and cancellation of superseded runs. Local actionlint 1.7.12 passes.
No workflow has been pushed or run on GitHub. Actual production inference/browser
checks require trusted artifacts and remain separate local release gates.

`./scripts/release-check.sh` runs the static/unit/build/config gates using existing
project environments. It never installs packages globally, changes system
packages, commits, tags, publishes or deploys.

## Security review

FastAPI/Starlette and urllib3 updates remove known application dependency issues;
npm fixes update three transitive lock entries without major package upgrades.
Final pip-audit and npm audit report **zero known vulnerabilities**. Final Trivy
0.75.0 scans report zero Python-package findings and zero gateway-image findings.
The Python Debian images retain distribution findings: data/routing each have
2 critical, 53 high, 107 medium, 100 low and 2 unknown; prediction has 2 critical,
53 high, 109 medium, 101 low and 2 unknown. These are retained, not suppressed.

The critical zlib MiniZip finding is explicitly ignored by
[Debian's tracker](https://security-tracker.debian.org/tracker/CVE-2023-45853)
because affected MiniZip code is not built into the Bookworm zlib binary.
`pyminizip` is absent. The critical
[SQLite issue](https://security-tracker.debian.org/tracker/CVE-2025-7458)
requires arbitrary attacker SQL; reviewed runtime queries use fixed SQL with
bound input values and expose no SQL execution API. Debian has no Bookworm fix
for that issue. These facts reduce relevant exposure; they are not a claim that
all remaining OS vulnerabilities are harmless. Review distribution updates and
the saved package-level scans again before public operation.

Unprivileged users, dropped capabilities, no-new-privileges, immutable source
mounts and root filesystems, internal-only backend ports, body/method limits,
explicit CORS and bounded logs are enforced. No credentials were read, copied
into images or emitted into a frontend build. Public TLS/access controls, abuse
rate policy, trusted artifact transfer and backups are operator concerns for
Phase 2F. There is no new authentication or telemetry system in this phase.

## Resource measurements

Docker `stats --no-stream` samples are recorded every approximately five seconds
(command cost plus a three-second pause) in ignored JSONL. During the 108-request
matrix, latency was **1.981–31.591 s**, median **12.858 s**, approximate p95
**23.964 s**, with twelve concurrent requests per batch. Browser traffic overlapped
part of that experiment. These are deliberately constrained containers, not a
clean single-request benchmark or a final-server capacity claim. Final idle/peak
figures follow. Docker Desktop had 16 GiB available during this validation.

| Service | Idle memory | Sampled peak memory | Sampled peak CPU |
| --- | --- | --- | --- |
| Prediction | Approximately 144–148 MiB | 501.1 MiB | 49.64% |
| Data | Approximately 2.11 GiB | 2.308 GiB | 125.46% |
| Routing | Approximately 2.16 GiB | 2.168 GiB | 121.31% |
| Gateway | Approximately 6–7 MiB | 11.57 MiB | 4.86% |

337 samples covered route/browser traffic and recovery. Simultaneous observed
stack peak was **4,721.14 MiB (4.61 GiB)**; idle was approximately **4.41 GiB**,
with each Python service around 0.1% CPU at one idle observation. A later data
sample reached 15% during periodic score serving. Docker CPU
100% means one core, not the whole host. These Docker memory figures are not
process RSS or total Docker VM memory. Native inference's full-city batch explains
the prediction peak above its idle model footprint; only one model is loaded.
There were no OOM kills or automatic restart loops in the final containers.
Routing temporarily used a core for post-traffic score/profile work, then settled.

One cache-status inspection using a 10-second client deadline timed out during
concurrent browser traffic; its idle retry returned in 0.021 seconds. Retain this
tail-latency limitation. The gateway and frontend have bounded timeouts rather
than a promise of immediate responses. No architecture rewrite was attempted.

| Service | Hard RAM limit | CPU quota | Process/thread policy |
| --- | --- | --- | --- |
| Prediction | 768 MiB | 0.5 core | One model/worker; native model threads 2 |
| Data | 4 GiB | 1.25 cores | One worker; OpenBLAS 1, OMP 2 |
| Routing | 4 GiB | 2 cores | One worker; route executor 2, OpenBLAS 1 |
| Gateway | 256 MiB | 0.25 core | One Nginx worker |

Quotas total four CPU cores; hard RAM ceilings total 9 GiB, excluding Docker,
kernel, filesystem cache and other host workloads. Graph duplication remains a
known several-GiB cost. Resource limits do not prove suitability for a 12-GB
server. Real final-server measurements are a Phase 2F prerequisite.

## Production browser validation

Installed Chromium **145.0.7632.6** ran against `http://127.0.0.1:8080`, using the
existing Playwright framework. No Vite server or browser installation was used.
**24/24 scenarios passed** in 17.3 minutes, with no skips/retries/flaky results,
at **1440×900, 1280×720, 768×1024 and 390×844**. They cover:

- Real routes for all four vehicles and all three applicable modes; cards,
  ETA/distance, provenance/provider-backed labels, continuous route display.
- Coordinate and map-picked endpoints, changed inputs, repeated requests,
  invalid input/no route, recovery, loading and clear stale results.
- Real heatmap requests/toggles, basemap tiles, light/dark controls, scrolling
  explanations, responsive overflow and map size.
- Explicit backend/prediction errors and retry paths; injected UI failures are
  labelled tests, not substitutes for successful application functionality.
- Compiled assets/content types/immutable caching, SPA deep-link reload,
  readiness and real CPU inference. Normal workflow console/network checks passed.

After final gateway changes and restarts, **4/4 additional production checks
passed** in 2.6 minutes at the same viewports: security header inheritance,
unexposed diagnostic APIs, forbidden methods, nonpermissive CORS, 413 body limit,
and clear geocoder-failure presentation that removes old route cards. A separate
**actual routing-container outage browser check passed**: real 503, stale-card
removal after changing vehicle, Retry recovery, three bike cards and page reload,
with no page errors. Its routing restart took 60.266 seconds. Screenshots, JSON
responses and reports remain ignored, including eight normal workflow screenshots
and two real-outage/recovery screenshots.

The real Nominatim path returned `12.9755264, 77.6067902` for “MG Road Bengaluru”
through the gateway in 0.738 seconds on this run. This observation is not an
availability guarantee. Coordinates/map selection continue to work independently
of that external provider.

## Restart/recovery validation

All lifecycle checks passed with real gateway requests after readiness, not just
container “running” status. Final-image startup/recreation took **102.923 seconds**.

| Operation | Ready wait | Real request after recovery |
| --- | --- | --- |
| Prediction stop/start | 6.136 s | CPU inference 200 and route 200 |
| Data stop/start | 35.651 s | Source metadata 200, inference 200, route 200 |
| Routing stop/start | 63.645 s | Compatible new score revision, route 200 |
| Prediction replace at different IP | 6.745 s | Gateway inference 200 and route 200 |
| Entire stack stop/start | 95.535 s | All ready, inference 200 and route 200 |

For each stopped backend, its gateway API returned a concise 503 while `/` and
gateway liveness remained 200. Stop operations completed in 0.759–1.106 seconds;
whole-stack stop took 1.929 seconds. The DNS replacement deliberately occupied
prediction's old `172.19.0.3` address with a temporary isolated test container so
the replacement received `.6`; Nginx resolved it without restarting. That helper
was removed. The normal topology uses no static-IP configuration.

Graph identity and source receipt survived every reload. The route cache survived
as schema 8 (92 entries / 3,690,629 bytes before whole-stack restart, 98 entries /
3,973,464 bytes after further requests); compatibility checks still govern reuse,
so persistence does not mean stale scores become valid. SQLite retained 868 tile
definitions and the local source remained 122,409 unknown-provenance towers.
There are zero provider-backed cached tiles. Temporary data-score lag after data
restart retained a compatible older labelled snapshot; routing restart adopted
the new revision. Final gateway smoke inference and invalid-input/route checks
also passed. No deliberately broken containers remain.

Completed controlled artifact checks: missing model and changed checksum exit 1
with a clear bootstrap message. A hash-valid negative fixture that is not a model
starts its process but returns 503 readiness and 503 inference, with training
disabled. All three negative containers were removed. A separate gateway test
project failed clearly on occupied port 8080 and was removed without disturbing
the real stack. Runtime write probes confirmed immutable source/model access and
read-only shared graph access from routing; only data can write that publication.

The 3-pair × 4-vehicle × 3-mode matrix was repeated through the gateway because
invalid coordinate validation and production thread quotas changed. All **36
combinations succeeded**; bounded refresh reruns generated **108 responses**.
Independent streaming GraphML calculations audited **641 selected edges**: all
108 displayed ETAs matched length/speed/vehicle-cap arithmetic and all 108 joined
geometries were continuous. This audit imports no routing helpers. Selected edges
use numeric km/h posted speeds (including aggregated minimum limits) or documented
road-class planning speeds. Every selected edge exists in the immutable graph.

Choose attempt 3 for each pair when comparing modes: each selected batch shares
graph, city-score and corridor identities internally. P1's twelve routes use a
compatible corridor revision; P2/P3's twenty-four use compatible city scores with
a null corridor revision after rejected newer feedback. Earlier mixed-generation
attempts are not compared. One P2 connected car/truck route was **38.254 km** for a
**6.0631-km** straight-line separation (52.4-minute moving-time estimate); this is
a suspicious estimated-signal detour, not evidence of desirable real-world routing.
Core objectives, access checks and snapshot code were not rewritten to hide it.

## Tests

With existing project environments and task-local Docker config, the actual
release gate was `./scripts/release-check.sh`. It ran:

| Command/check | Result |
| --- | --- |
| `.venv/bin/python -m pytest -q` | **251 passed**, 12 subtests passed, 116 deprecation warnings |
| `npm run test -- --run` | **36 passed**, 4 files |
| `npm run typecheck` | Pass |
| `npm run lint` | Pass, zero lint warnings |
| `npm run build` | Pass, no >500-kB chunk warning |
| `docker compose --env-file /dev/null config --quiet` | Pass |
| `git diff --check` | Pass; existing CRLF notices remain, no normalization |
| `actionlint .github/workflows/ci.yml` / `bash -n scripts/release-check.sh` | Pass |
| `docker compose ... build` | All four production images pass |
| `scripts/production-smoke.py` | Startup and post-recovery real gateway checks pass |
| Playwright full / final release-only suite | **24 passed + 4 passed** |
| Real browser routing-outage/recovery script | **1 passed** |
| Independent GraphML audit | **108/108 ETA matches, 108/108 continuous geometries** |
| `pip-audit` / `npm audit` | Zero known application dependency vulnerabilities |
| Trivy image scans | Retained OS findings classified above; gateway/Python packages zero |

The increase from 225 to 251 Python tests is 16 release invariants plus 10 invalid
coordinate/boundary cases. No meaningful baseline tests were removed. Focused
bootstrap tests passed 16/16; focused production/vehicle tests previously passed
83, and prediction/concurrency/revision checks passed 83 plus 12 subtests during
implementation. Existing `on_event` deprecation warnings are maintenance work,
not a migration performed in this phase.

The first full gate inherited `LOCAL_DATA_ONLY=1`, which suppressed three mocked
ingestion test paths (248 passed, 3 failed). The script and CI now set a neutral
test environment explicitly, clear credential variables and use `/dev/null`
instead of dotenv; the corrected full gate passes. Production still requires
local-only data mode. A parallel image scan hit Trivy's shared-cache lock; its
sequential retry passed. These validation setup failures were not hidden.

Reproduce the actual production checks with trusted prepared inputs:

```bash
ARTIFACT_DIR="$PWD/.cache/phase-2e/artifacts" \
  docker compose --env-file /dev/null -p zlf-phase2e build
ARTIFACT_DIR="$PWD/.cache/phase-2e/artifacts" \
  docker compose --env-file /dev/null -p zlf-phase2e up -d --wait --wait-timeout 600
.venv/bin/python scripts/production-smoke.py --output .cache/phase-2e/smoke.json
cd services/visualization
E2E_RELEASE=1 E2E_BASE_URL=http://127.0.0.1:8080 \
  E2E_OUTPUT_DIR=../../.cache/phase-2e/browser-results \
  E2E_REPORT=../../.cache/phase-2e/browser-report.json npm run test:e2e
```

Installed WSL Chromium also requires the same `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE`,
`PLAYWRIGHT_BROWSERS_PATH`, `LD_LIBRARY_PATH` and `TMPDIR` listed in the D report;
these are validation-tool environment settings, not application dependencies.
In this run the Docker client used an empty task-local `DOCKER_CONFIG` and the
local `/var/run/docker.sock`; no credential store was accessed.

## Image sizes

All four final images built successfully, including dependency/source/service
import gates and Nginx syntax/static-output gates.

| Image (`:local`) | Docker-reported size | Runtime user |
| --- | --- | --- |
| `zero-latency-data` | 212.28 MiB | 10001:10001 |
| `zero-latency-routing` | 164.09 MiB | 10001:10001 |
| `zero-latency-prediction` | 161.64 MiB | 10001:10001 |
| `zero-latency-gateway` | 28.26 MiB | nginx |

These are Docker Engine 29's image `Size` values, not total build cache/storage
or the uncompressed sizes of writable volumes. Image IDs and scans are retained
in `.cache/phase-2e/image-sizes-final.json` and `image-audit-*-final.json`.

## Remaining limitations

- Unknown tower/model provenance, dates, evaluation and confidence; RF/signal and
  moving-time traffic assumptions are estimates. Zero provider-backed coverage
  stays distinct from strong estimated signal.
- Sparse access/direction/speed metadata and missing topology; no guarantee of
  real road legality or calibrated Bengaluru traffic ETAs.
- Connected-mode detours and temporary compatible city-score fallback while
  routing catches up with corridor feedback. Compare only compatible revisions.
- Valid global coordinates outside the graph still snap to its nearest node;
  this phase rejects invalid geographic values but adds no coverage geofence.
- Graph RAM duplication, optional external geocoder reliability, basemap internet
  dependency, Chromium-only automation and unexecuted PowerShell runtime.
- Debian distribution findings, unfrozen OS security-update repositories, and
  final-server capacity/public-operation checks.

## Changed files

Phase 2E functional files (existing C1/D modifications remain underneath):

- `.dockerignore`, `.github/workflows/ci.yml`, `docker-compose.yml`,
  `config/production.example`, `constraints.txt`, `requirements-test.{txt,lock}`.
- `runtime/entrypoint.py`, `scripts/{prepare-artifacts.py,production-smoke.py,release-check.sh}`.
- `gateway/{nginx.conf,nginx-main.conf}`; all three backend Dockerfiles and their
  `requirements.{txt,lock}`.
- `services/routing-engine/main.py`: bounded production executor threads and
  invalid coordinate rejection; path objectives/snapshots unchanged.
- `services/visualization/{Dockerfile,package-lock.json,playwright.config.ts}`,
  `app/App.tsx`, `e2e/release.spec.ts`.
- `tests/{test_production_release.py,test_feature_integrity.py,test_vehicle_routing.py}`.
- `README.md`, `docs/api-contract.md`, this report.

No Phase 2E functional changes to the six pre-existing line-ending-only files,
the C1/D reports, source datasets, original Windows project or laptop snapshot.
Generated artifacts, scans, screenshots, traces, logs and measurements are ignored
under `.cache/phase-2e`; Docker images/volumes are on the D:-backed Desktop disk.

## Manual checklist before Phase 2F

1. Review the actual diff, dependency locks, retained OS findings and artifact
   trust/provenance limitations before making manual commits.
2. Inspect screenshots/routes and suspicious detours. Do not infer legal roads
   or model accuracy from passing synthetic/container/browser checks.
3. Confirm available server RAM/disk alongside existing services; plan an isolated
   Compose project without interrupting them.
4. Define artifact transfer, volume backup/restore, public access/abuse policy,
   update policy and rollback to a preserved image tag plus matching volumes.
5. Re-run release gates and real artifact smoke checks after promotion.

## Deployment prerequisites for Phase 2F

An Ubuntu Docker Engine/Compose installation with adequate free CPU/RAM/disk;
trusted model/graph/tower inputs plus manifest; a reviewed immutable release image
tag; a new isolated Compose project; volume ownership/backups; an agreed future
public-entry/TLS configuration; and explicit deployment authorization. A rollback
must restore matching images, source inputs and saved runtime volumes together,
rather than silently reusing a graph volume from different inputs.

No Ubuntu host was accessed. At completion all four `zlf-phase2e` containers remain
healthy and running at **http://127.0.0.1:8080**. The earlier Python/Vite launcher
children were stopped using its ownership records; no dev services remain.
Task-owned browser/test/sampling processes have finished. Stop only this stack:

```bash
ARTIFACT_DIR="$PWD/.cache/phase-2e/artifacts" \
  docker compose --env-file /dev/null -p zlf-phase2e stop
```

The ignored `.cache/phase-2e/docker` wrapper provides the same command with this
run's empty Docker config and artifact path. Named runtime volumes and immutable
inputs remain for restart. An unused `zlf-phase2e-inputs` volume from the initial
WSL bind-mount workaround also remains; no unrelated volume was touched or removed.
