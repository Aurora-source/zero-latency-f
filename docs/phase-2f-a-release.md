# Phase 2F-A — GitHub Release and Deployment Bundle

Validated on 2026-10-06 in the development WSL environment. This phase prepares
an immutable source/image release and a separate private runtime-artifact bundle.
No Ubuntu server, remote host, DNS, tunnel, firewall, or public application
deployment was accessed or changed.

## Scope

The C1–E product was audited, its legitimate project changes were committed,
and version 0.1.0 was selected because the repository had no previous tags or
GitHub releases. The source bundle contains deployable software and public
documentation. The private bundle carries the existing GraphML, tower CSV, and
XGBoost model needed by the runtime. The private bundle is excluded from GitHub.

The final release commit SHA, image IDs, archive checksums, and release asset
checksums are recorded in the accompanying release-manifest.json and SHA256SUMS
assets. The annotated v0.1.0 tag identifies that exact commit.

## Starting state and audit

The baseline was Phase 2E at cb7b454, following the completed Phase 2C1 and 2D
reports. At the start of the release audit, the only uncommitted repository
changes were the six previously identified CRLF/LF-only files:

- services/data-service/scripts/clip_bangalore.py
- services/data-service/scripts/convert_southern.py
- services/data-service/scripts/nah.py
- services/visualization/app/components/CitySelector.tsx
- services/visualization/app/components/Header.tsx
- services/visualization/styles/index.css

Each was verified to differ only by line endings and was excluded from release
staging. No broad normalization or reset was run. The accumulated C1–E overlay
contained 64 tracked functional, test, and documentation files (8,839
insertions, 665 deletions) against cb7b454. Its contents match the changed-file
inventories in the C1, D, and E reports; no unexplained or generated artifact
was found. The three accumulated C1–E release-preparation commits present at
the start of this final release audit were:

- 612931d — production-ready C1–E project changes, release README, deployment
  guide, and public runtime-artifact manifest.
- 335f161 — private runtime-bundle checksum documentation.
- 83fb02b — artifact permission and mount guidance.

The branch is codex/project-completion. The public GitHub repository is
Aurora-source/zero-latency-f. Its default branch main was fetched and confirmed
to be an ancestor of this branch; no remote codex/project-completion branch,
tag, or release existed. No secrets, dotenv files, tokens, keys, or credentials
were read or included. Prospective tracked files were scanned before release.

The source changes are itemized in docs/phase-2c1-runtime.md,
docs/phase-2d-product-completion.md, and docs/phase-2e-production-release.md.
The additional Phase 2F-A tracked files are README.md, DEPLOYMENT.md,
deployment-artifacts-manifest.json, and this report. Public bundles and image
archives are generated under the ignored .cache/phase-2f-a directory.

## Production architecture

The validated topology is:

    browser
      → loopback-bound Nginx gateway (host port 8080; 18080 for rehearsal)
      → compiled React frontend and same-origin API proxies
      → internal Compose network
      → prediction service → data service → routing engine

Only the gateway is published to the host, and it binds to 127.0.0.1. Backend
ports remain private on the Compose network. The frontend is the compiled
production build served by Nginx; Vite is not used in this topology.

Data is the sole writer of the shared graph-publication volume. Routing mounts
that volume read-only. Immutable graph/tower/model inputs are mounted read-only
from ARTIFACT_DIR. Named volumes hold graph publication, generated tower and
score state, prediction runtime state, and the persistent route cache.

## Container and release changes

The production Compose setup uses four CPU-oriented images, internal networking,
health-aware startup ordering, bounded workers/threads, restart policy,
read-only root filesystems, dropped Linux capabilities, non-root application
users, bounded temporary space, and rotating stdout/stderr logs. The backend
resource ceilings total 9 GiB and four CPU cores. The release CI workflow is
.github/workflows/ci.yml; scripts/release-check.sh runs local backend,
frontend, Compose, and whitespace gates.

Docker Desktop reported Engine 29.7.2 and Compose 5.5.0. All images were built
from the final tagged source tree. Observed Docker image sizes:

| Image | Size |
| --- | ---: |
| zero-latency-data | 222,591,691 bytes (212.3 MiB) |
| zero-latency-routing | 172,063,514 bytes (164.0 MiB) |
| zero-latency-prediction | 169,488,220 bytes (161.5 MiB) |
| zero-latency-gateway | 29,637,533 bytes (28.3 MiB) |

The release uses version and exact Git-SHA tags. The public release includes an
optional gzip-compressed Docker image archive when it remains under GitHub's
asset-size limit. The archive contains software images only, never the private
runtime artifacts.

## Production frontend and gateway

Nginx serves the compiled SPA, provides application-path fallback, and proxies
only the documented same-origin API paths. The smoke test returned 200 for the
gateway root and /inspect-route, compiled assets loaded, and the SPA path
survived reload. Gateway readiness checks all three backend readiness paths.
Health/readiness and route requests were exercised through the gateway, not by
using the Vite development server.

The 24 production-browser scenarios passed through the gateway, six each at
1440×900, 1280×720, 768×1024, and 390×844. They cover map load and tiles,
coordinate and map-picked endpoints, real routes, all four vehicles and
applicable modes, route cards/ETA/distance/connectivity/provenance, heatmap,
repeated requests, input changes, invalid/unreachable input, backend and
prediction failures, retry/recovery, loading state, SPA refresh, and responsive
layout. The suite reported no failed assertions, browser page errors, or
unexplained failed network requests. Screenshots and traces remain in ignored
local validation output.

The tests used the installed Chromium and existing frontend node_modules as
test tooling. The application, compiled assets, APIs, model inference, and
routing all came from the container stack built from the extracted release
source and artifacts.

## Configuration

config/production.example is a credential-free configuration example.
ARTIFACT_DIR is required and must point to the extracted private artifacts
directory; RELEASE_TAG selects the image tag; GATEWAY_PORT controls the
loopback gateway port; CORS_ORIGINS is optional and should stay empty for the
same-origin production flow. No machine-specific path is compiled into source
or the frontend bundle. There are no runtime secrets in the example file.

Startup rejects missing or checksum-invalid required artifacts. The release
expects:

- bangalore.graphml
- bangalore_towers.csv
- connectivity_model.pkl

The container model path is /artifacts/connectivity_model.pkl and the data
service reads the graph and tower CSV from /artifacts. Host paths are supplied
by ARTIFACT_DIR rather than embedded in images.

## Runtime artifact inventory and persistence

The exact previously validated artifacts were found under the ignored
.cache/phase-2e/artifacts directory. Their hashes match the Phase 2E validation
record. They were copied byte-for-byte, validated, and packaged without
modifying their sources.

| Artifact | Size | SHA-256 | Format and consumer |
| --- | ---: | --- | --- |
| bangalore.graphml | 130,110,773 bytes | ca0c638be582c38a3aeacfc7f6afca7b183f9cec30b42ba6ea08c2abd3fe8ca9 | Directed simplified GraphML, 71,618 nodes and 227,047 edges, EPSG:4326; OSMnx 2.0.2; data service publishes it, routing reads the publication. |
| bangalore_towers.csv | 6,293,112 bytes | 9a4647602dfa52bad14c98cb68021e06901399ace26f2c651f78ea44e3a218bc | UTF-8 CSV, 122,409 rows, schema lat/lon/mcc/mnc/lac/cellid/radio/range; data service ingestion. |
| connectivity_model.pkl | 672,086 bytes | b701d3988b7b4dcba4360baccc8db84d9ead8d3953067eb505af2c4d0878ef7c | Genuine pickled XGBRegressor with seven inputs and 140 boosting rounds, XGBoost 3.2.0; prediction service loads it on CPU. |

All three are mandatory for the supported local Bengaluru runtime. The graph
metadata records creation date 2026-04-18 and OSMnx version 2.0.2, but its exact
OSM query and retrieval receipt are missing. ODbL attribution/redistribution
review is incomplete. Tower provider, observation dates, acquisition, bounds
query, and source license are unknown. Model training dataset, date, evaluation,
calibration, confidence, origin, and license are unknown. For those reasons all
three are excluded from public assets and included only in the requested private
local transfer bundle. Their hashes establish byte integrity, not provenance,
authenticity, legality, or model quality. The pickle must be treated as trusted
input.

The private archive is
.cache/phase-2f-a/zero-latency-f-0.1.0-private-runtime.tar.gz, 13,752,679 bytes,
SHA-256 1d476e87c08af8786857f53598b24b5dd7be19ac894bc58d518309a8ff96348b.
Its archive mode is 0600. It contains manifest.json,
README-RUNTIME-ARTIFACTS.md, SHA256SUMS, and the three files under artifacts/.
Internal checksums and extracted byte comparisons passed; the runtime
entrypoint artifact validator accepted the extracted files.

Other runtime state is generated: the data service writes graph publication
and SQLite/index/score state; routing writes a compatibility-keyed route cache;
prediction may write bounded runtime/cache state. These are kept in separate
named volumes rather than the immutable artifact source. The full-stack
stop/start retained four named volumes, and the routing cache remained present
with 85 entries after restart.

No other mandatory source dataset, database, model, lookup table, or generated
index was discovered. Telemetry is not part of the production Compose
topology. No new dataset or model was downloaded or generated.

## Health, readiness, and recovery

Compose starts prediction before data and data before routing using health
conditions. The gateway is healthy only after prediction, data, and routing
readiness respond successfully. During cold start, application root/liveness
remained available while backend readiness returned 503; once the graph and
compatible score snapshot loaded, gateway readiness returned 200.

The fresh extracted-source/private-artifact stack passed readiness, production
smoke, and browser checks. Production smoke verified gateway/SPA, all backend
readiness routes, genuine CPU prediction, a real route, and invalid-coordinate
rejection.

The smoke route used 12.9750564233, 77.5903035618 → 12.9798218, 77.6009173.
Its GeoJSON geometry measured approximately 2.005 km by summing consecutive
WGS84 haversine distances; the response ETA was 2.9 minutes, average estimated
connectivity 0.85, and geometry contained 84 positions. Graph revision was
4e762aa11553433fadcfe493666fc841. The response marked provenance unknown and
provider-backed coverage 0.0%; 7,664 nearby tower records do not mean verified
provider coverage. Prediction returned finite CPU inference and the same graph
revision.

Recovery checks used real requests after health returned:

| Operation | Time to all services healthy | Result after recovery |
| --- | ---: | --- |
| Full stack stop/start, preserving volumes | 193 s | Prediction and route smoke passed. |
| Prediction container restart | 8 s | Inference and route smoke passed. |
| Data container restart | 61 s | Inference and route smoke passed. |
| Routing container restart | 121 s | Inference and route smoke passed. |

All routes retained graph revision 4e762aa11553433fadcfe493666fc841 and prediction
reported that revision. Score/corridor revisions changed during restart and
refresh. One response temporarily used the previous compatible city-score
revision while data had already published a newer same-graph score revision;
after routing restarted, its route response used the new revision. These
responses expose their revisions and retain graph compatibility; they must not
be compared as if they used identical scores. This reproduces the documented
score-refresh lag. The output continued to label source/provenance as unknown
or model/synthetic, with zero provider-backed coverage.

One initial container recreation encountered a Docker Desktop WSL bind-mount
bridge path that had disappeared under /run/desktop. Docker reported the exact
missing generated mount directory in the container create error. Recreating
only the isolated rehearsal containers restored the bridge and all subsequent
clean-room checks passed. No Docker Desktop engine restart was used, so unrelated
local projects were not deliberately interrupted.

## CI and security review

The repository workflow covers Python tests, frontend tests/typecheck/lint/build,
Compose validation, and container build checks without requiring private runtime
artifacts. actionlint and shell syntax validation passed locally. GitHub Actions
results for the release branch are reported separately after push.

The public bundle is produced from committed Git tree contents and excludes
.git, .venv, node_modules, .cache, logs, screenshots, private runtime data, and
credentials. Its contents were scanned before publication. The production
Compose topology publishes only the loopback gateway and does not grant backend
ports publicly. Container controls include non-root services, read-only source
mounts/root filesystems, dropped capabilities, no-new-privileges, body limits,
explicit same-origin CORS behavior, and bounded log rotation.

Phase 2E pip-audit and npm audit found zero known application dependency
vulnerabilities. Trivy found zero Python-package findings and zero gateway-image
findings; Debian base images retained the OS findings detailed in
docs/phase-2e-production-release.md. They were not suppressed. Recheck OS
security updates and dependency/image scans before public operation.

## Resource usage

The current container observations match Phase 2E's resource profile. During
browser traffic, data used about 2.34 GiB and routing about 2.22 GiB; prediction
used about 308 MiB and gateway about 8 MiB. The summed sample was approximately
4.87 GiB, with routing near one CPU core during route traffic. After traffic,
one sample was about 2.05 GiB data, 2.02 GiB routing, 145 MiB prediction, and
5 MiB gateway. These are Docker container memory observations, not host RSS.
Phase 2E measured about 4.41 GiB idle and a 4.61 GiB simultaneous peak; Compose
hard ceilings total 9 GiB. Graph duplication remains the main cost. This does
not prove suitability for the eventual server or its other workloads.

The routing logs also show OSMnx falling back to its nearest-node search when
optional scikit-learn is not installed in that image. Routes still succeeded;
the fallback and score-refresh messages are operational noise/performance risks
to monitor, not evidence of better routing quality. No worker/cache redesign was
made.

## Browser validation

The production browser run was Playwright on installed Chromium 145.0.7632.6
against the compiled gateway at 127.0.0.1:18080. All 24 scenarios passed in
18.7 minutes with one worker: six scenarios each on desktop 1440×900, laptop
1280×720, tablet 768×1024, and mobile 390×844. Screenshots were written under
the ignored clean-room output directory. The suite exercises the real frontend
and services. Controlled proxy failures are limited to UI failure-path
assertions; successful inference and routes use the actual containers.

The browser tests checked no horizontal overflow, map sizing, visible route
cards and ETA, mode/vehicle switching, map-selected endpoints, heatmap tile
requests/toggles, loading/errors/retry, stale-result clearing, invalid/no-route
handling, SPA refresh, same-origin APIs, immutable production assets, and
unknown provenance labels. Their assertions for console/page errors and
unexplained failed requests passed. Basemap tiles loaded through the internet
provider during the run.

## Tests and checks

The final local release gate was scripts/release-check.sh:

| Check | Result |
| --- | --- |
| .venv/bin/python -m pytest -q | 251 passed, 12 subtests passed, 116 existing FastAPI lifecycle deprecation warnings. |
| npm run test -- --run | 36 passed in 4 files. |
| npm run typecheck | Passed. |
| npm run lint | Passed with zero lint warnings. |
| npm run build | Passed; MapView is a separate 225.39 kB chunk, no large-chunk warning. |
| docker compose --env-file /dev/null config --quiet | Passed. |
| git diff --check | Passed; the six line-ending-only files remain unnormalized. |
| actionlint .github/workflows/ci.yml; bash -n scripts/release-check.sh | Passed locally. |
| Production gateway browser suite | 24/24 passed over four viewport projects. |
| Artifact validation and internal SHA256SUMS | Passed; extracted bytes matched the copied validated files. |
| Production smoke after cold start and each restart | Passed; CPU inference and route each returned 200. |

Phase 2E's independent routing audit remains the routing regression evidence:
36 compatible endpoint/vehicle/mode combinations passed, 108 route responses
were independently checked, and 641 selected graph edges had matching
ETA arithmetic and continuous joined geometry. The Phase 2F-A clean-room smoke
also confirmed real routing and prediction on the same graph revision. These
tests do not establish calibrated ETAs or verified real-road legality.

## Data and map limitations

No artifact was missing: the exact Phase 2E-validated graph, tower CSV, and model
were found and copied. No fresh acquisition was attempted because the tower
source/license and model rights are unknown, while the existing exact graph was
preferable to regenerating a potentially route-changing OSM snapshot. No
credential was accessed for OpenCellID or another provider. The repository has
no documented reproducible training procedure or dataset from which to create
a substitute model.

The routing GraphML is not a visual basemap. The frontend still requires
internet access to its configured raster tile provider and for optional
geocoding. No public OSM raster tiles were bulk-downloaded. Local graph/tower/
model inputs support routing and estimated connectivity offline, but not
offline map imagery. Tower/model provenance and license, sparse road access
metadata, uncalibrated RF/traffic estimates, suspicious connected-mode
detours, score-refresh lag, Chromium-only browser automation, and server
capacity remain limitations. Passing synthetic, container, and browser checks
must not be represented as real-map route-quality certification.

## Public and private release assets

The public deployment archive is zero-latency-f-0.1.0-deploy.tar.gz. It is
generated from the exact v0.1.0 commit and excludes the private data/model
artifacts. Public release assets are the deployment archive,
release-manifest.json, deployment-artifacts-manifest.json, SHA256SUMS, and the
optional software-only image archive. Each public checksum is verified locally
and the downloaded deployment archive is checked against its published SHA-256.

The private archive is
zero-latency-f-0.1.0-private-runtime.tar.gz. Its SHA-256 is
1d476e87c08af8786857f53598b24b5dd7be19ac894bc58d518309a8ff96348b and it must
not be uploaded as a release asset. The operator must manually transfer that
file to Ubuntu for Phase 2F-B, verify its archive hash, and then verify its
internal SHA256SUMS before mounting its artifacts read-only.

The release manifest records the exact commit, source/image identifiers, bundle
hashes, private artifact hashes, version, architecture, host port, Docker
assumptions, and release-check summary. The public
deployment-artifacts-manifest.json lists mandatory private artifact names,
hashes, sizes, target paths, and provenance/redistribution status without
embedding their bytes.

## Changed files

Phase 2F-A project files:

- README.md — local and production-like run instructions, artifacts, and
  versioned private-bundle identity.
- DEPLOYMENT.md — verified-bundle transfer, prerequisites, configuration,
  health/smoke, lifecycle, rollback, and limitations.
- deployment-artifacts-manifest.json — public expected-artifact inventory.
- docs/phase-2f-a-release.md — this release audit and validation record.

Release tarballs, manifests generated with the final commit SHA, checksums,
browser evidence, and Docker image archive live only under ignored
.cache/phase-2f-a. The six pre-existing line-ending-only changes are not part
of the release commit.

## Manual checklist before Phase 2F-B

1. Manually transfer only zero-latency-f-0.1.0-private-runtime.tar.gz to the
   Ubuntu server; verify its stated SHA-256 and its internal SHA256SUMS there.
2. Verify available server RAM, disk, CPU quota, and existing workload headroom
   before startup. Local measurements do not prove the 12 GB host has enough
   free memory.
3. Keep artifacts private, set the server ARTIFACT_DIR and file permissions,
   and use a new version-scoped Compose project with matching named volumes.
4. Confirm that the graph/model/tower redistribution and use rights are
   acceptable to the operator; their provenance/license uncertainty remains.
5. Check public basemap/geocoder internet behavior and inspect local routes for
   suspicious detours. Do not advertise measured coverage or calibrated ETA.
6. Back up matching graph-publication, score, and route-cache volumes before
   upgrades. Roll back only with matching image, source-artifact, and volume
   revisions.
7. Keep the gateway on loopback until public ingress, TLS, abuse controls,
   monitoring, and backup plans receive their separate Phase 2F-B review.

No remote server was accessed. Phase 2F-B is not started here.
