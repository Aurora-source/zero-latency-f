# Phase 2B2: cross-service graph/score revisions

Implemented after local checkpoint `0d6c5e9` on `codex/project-completion`.
This phase preserves the Phase 2A concurrency/loading guarantees and Phase 2B1
vehicle legality, travel-time objectives, edge selection, and provenance fields.

## Failure paths found before editing

- Shared GraphML had atomic replacement but no durable identity. Routing's file
  stat tuple detected replacement locally but could not identify the graph behind
  an HTTP score response or survive copying/reloading the same publication.
- Routing loaded GraphML and then fetched unversioned city scores. A publication
  between these operations could join graph B with scores for graph A, especially
  when segment IDs overlapped. A queued refresh also lacked a final current-state
  check before publishing its result.
- Corridor requests, their shared-work keys, responses, and tile feedback lacked
  graph/score identities. A completed route for an old graph could feed scores into
  the replacement graph. Corridor changes were invisible to route-cache lookup.
- Persisted real-score dictionaries and separate metadata sidecars were matched
  only by segment ID. Neither the sidecar nor city/count agreement proved that
  those observations belonged to the loaded graph.
- Prediction responses did not identify the input graph. Score timestamps mixed
  freshness with identity and could not safely order overlapping work or distinguish
  updates at the same clock value.

## Revision lifecycle

1. **Graph publication:** the data service assigns a new UUID string inside
   `graph.graph["graph_revision"]` for every publication, writes and fsyncs a
   temporary sibling GraphML, then atomically replaces the shared path. A copied
   graph being republished also receives a new identity. Only the publisher assigns
   it; city-state construction refuses unversioned graphs. Plain reload preserves
   the embedded identity. No graph hashing is performed on route requests.
2. **Legacy graph adoption:** data loads an unversioned cached GraphML and atomically
   republishes it with an identity before building scores. Routing never rewrites
   shared GraphML. Interrupted publication leaves the previous file, including its
   identity, intact. File stats remain a cheap routing replacement detector.
3. **City scores:** `CityState` has a separate UUID `score_revision`. A material
   score, provenance, or metadata change rotates it under the city lock. No-op
   updates retain it. New fallback states receive a new generation; an accepted
   persisted envelope can restore its score identity. These opaque strings are
   compared exactly, not ordered by `updated_at`.
4. **Exchanges:** `/scores/{city}` and `/scores/source/{city}` return both revisions
   with their locked score/provenance snapshot. Prediction requests carry the
   graph revision and must receive its exact echo. Prediction and coverage writers
   check their target state and expected score generation before applying work.
   A private replacement can hydrate before publication, while a detached former
   published state cannot accept late results.
5. **Routing publication:** routing validates the city-score graph revision before
   applying values, checks shared-file replacement again before becoming ready,
   and publishes compatible copied graph/vehicle-weight/provenance state together.
   A refresh checks the current state object, graph revision, and expected previous
   score revision under locks. Late work cannot replace a newer snapshot.
6. **Request lifetime:** each route keeps references to its captured graph, arrays,
   score identities, provenance, and day/night bucket. Later graph, score, or time
   publications do not change those objects. Responses expose `graph_revision`,
   city `score_revision`, and `corridor_score_revision` for inspection.

All writers/readers assume **one process per service**. Published graph objects are
immutable; topology changes go through the data-service publisher. This is not a
distributed transaction or coordination protocol for multiple workers/replicas.

## Corridor compatibility and route caching

`POST /corridor-scores` requires city, graph revision, and the expected city score
revision alongside coordinates. Admission compares a stable current identity pair
before fetching/scoring; the bounded pointer check avoids blocking the async event
loop behind a graph build. Its shared-work key includes both identities.

The response echoes `graph_revision` and `base_score_revision` and assigns a
deterministic `score_revision` digest to the corridor result, including values,
provenance, and metadata. An already admitted request may finish for its old graph
after replacement. Routing uses it only with the matching captured graph/base
score pair. An incompatible or absent identity discards all overrides and retains
the compatible city snapshot; it never promotes those discarded values to real
coverage.

Feedback carries the same graph/base/corridor identities. The data service checks
the current graph and base score generation and applies feedback under one city
lock. A late or repeated update after the base generation changes returns HTTP
409 without writing. The completed route remains valid for its own snapshot.

Route-cache schema **7** includes graph/city-score identity, corridor-score identity,
endpoints, mode, vehicle, and the captured time bucket. The existing TTL and atomic
JSON persistence remain. Routing obtains a compatible corridor revision before
cache lookup, so a new corridor observation invalidates path/metrics reuse even
without a city-score update. A corridor failure or mismatch bypasses cache reuse
and storage; the next request can recover immediately. Equivalent in-flight routes
and corridor work retain the Phase 2A deduplication behavior.

## Legacy and failure behavior

- A persisted real-score file is accepted only as one pickled mapping containing
  `graph_revision`, `score_revision`, `scores`, and `metadata`. The graph revision
  must match the current graph. Identities and metadata are read from this one
  envelope; separate old sidecars are not compatibility evidence. Legacy raw score
  dictionaries, missing identities, and mismatches are explicitly logged and
  skipped. Existing offline exporters have not been migrated or run in this phase.
- Ignoring a legacy score cache does not establish real coverage. Data can use its
  synthetic base, revision-bound predictions, or observations recomputed against
  current segments by the existing coverage code. No existing cache was relabeled
  or regenerated during this work.
- Routing treats missing graph identity and successfully returned city scores
  with missing/mismatched revision metadata as compatibility errors. Initial load
  uses the existing three attempts with 5/10-second backoff and remains HTTP 202
  loading during the cycle. Exhaustion gives terminal HTTP 503
  `graph_unavailable`; ordinary route requests do not reset the budget. Explicit
  preload can start a new bounded cycle. Missing shared files retain the separate
  ten-minute publication wait and one data-service preload request.
- Ordinary city-score transport/parse failure retains the existing degraded path:
  a new routing graph gets uniform `0.5` synthetic scores and local
  `score_revision="unavailable"`. GraphML score attributes are reset, not trusted
  as current coverage. Failed periodic refresh retains the previous compatible
  snapshot. There is no immediate retry loop inside score refresh or corridor
  scoring; normal city refresh remains once per 60 seconds.
- Corridor revision mismatch/empty identity returns HTTP 409; omitted required
  request fields return HTTP 422. Legacy unversioned corridor clients must update
  their request contract. The active frontend route flow needs no changes; its
  unused `fetchSignalCoverage` helper remains a legacy caller and would need these
  fields before being enabled.
- Standalone prediction clients may omit `graph_revision` and receive null back.
  Data-service prediction calls always supply and verify it.

## Validation

All tests use synthetic graphs, temporary GraphML/score/cache files, mocked HTTP
and tower dependencies, and the existing Python environment. Prediction tests
mock optional ML library imports and the predictor; no model or dataset is loaded.
ASGI contract tests use an in-memory transport without service startup.

Coverage includes matching/missing/mismatched identities; stale responses after
replacement; graph and provenance-only score updates; unchanged topology and clock
values; corridor updates invalidating cached paths; old in-flight snapshot
consistency; stale feedback rejection; identity persistence and legacy adoption;
interrupted publication; and bounded mismatch recovery/exhaustion. Existing
concurrency, atomic route-cache, time-transition, vehicle, ETA, and no-route
regressions remain enabled.

Focused commands during implementation:

```sh
rtk proxy env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_routing_concurrency.py tests/test_vehicle_routing.py tests/test_feature_integrity.py::RoutingModeTests
rtk proxy env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_data_revisions.py tests/test_data_concurrency.py tests/test_feature_integrity.py tests/test_routing_revisions.py tests/test_prediction_revisions.py
```

The original sandbox could not wake an asyncio event loop from a worker thread,
also reproduced with a minimal `asyncio.to_thread(lambda: 42)` call. The affected
focused runs were interrupted, then passed outside that sandbox. No tests were
disabled to hide the environment failure. The final run uses the updated execution
permissions.

Completion checks:

```sh
rtk proxy env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
rtk proxy docker compose --env-file /dev/null config --no-interpolate --no-env-resolution --quiet
rtk git diff --check
```

Results:

- Initial routing/concurrency/vehicle checks: **85 passed**.
- Combined revision and existing data/API checks during implementation:
  **95 passed**. Final focused publisher/data/default-contract checks:
  **40 passed** after the last API and publication changes.
- Complete Python suite, run once at completion: **172 passed in 2.22 seconds**,
  with 62 existing FastAPI lifecycle deprecation warnings. This includes **37 new
  revision tests** across data, routing, and prediction.
- `git diff --check` passed. The new report/test files were also checked for
  whitespace errors. The six pre-existing files have no diff when end-of-line
  whitespace is ignored.
- Compose configuration validation was **unavailable**: the Docker command is not
  available in this WSL distro. The attempted command disabled environment-file
  loading, interpolation, and service environment resolution; no containers ran.
- Frontend checks were skipped because this phase changed no frontend files.
  Live services, ML models, GPU execution, production resources, and real Bengaluru
  data were not validated.

## Changed files

- `services/data-service/main.py`: graph publication, city-score identities,
  legacy envelopes, guarded writers, corridor protocol, and feedback checks.
- `services/routing-engine/main.py`: compatibility checks, snapshot/cache
  identities, stale refresh rejection, and explicit corridor fallback.
- `services/prediction-service/main.py`: optional revision input and exact echo.
- `tests/test_data_revisions.py`: publisher, envelope, score, prediction, and
  corridor compatibility regressions.
- `tests/test_routing_revisions.py`: routing compatibility, cache, in-flight
  snapshots, and bounded recovery regressions.
- `tests/test_prediction_revisions.py`: mocked prediction HTTP contract.
- `tests/test_data_concurrency.py`, `tests/test_routing_concurrency.py`,
  `tests/test_feature_integrity.py`, `tests/test_vehicle_routing.py`: explicit
  revision fixtures and current cache/protocol expectations; existing correctness
  and concurrency assertions remain.
- `docs/api-contract.md` and `docs/phase-2b2-revisions.md`: API and lifecycle report.

The six pre-existing line-ending-only changes are preserved. No frontend source
changes, dependency installation, credentials/real-dataset access, model download,
container build/start, staging, commit, push, or deployment was performed.

## Remaining limitations

- Compatibility does not guarantee immediate freshness. City scores refresh on
  the existing 60-second interval. A publication gap can temporarily produce
  loading, a terminal bounded error, or a documented compatible fallback.
- Corridor validation still performs scoring before route-cache reuse, increasing
  work compared with a blind cache hit. Existing tower caching and concurrent-work
  deduplication limit duplication; no tower dataset/version infrastructure is added.
- UUIDs and response digests are compatibility identities, not authentication or
  proof against an external writer that tampers with a graph while preserving its
  metadata. Only the data-service publication path is supported. Power-loss
  durability, distributed writers, and end-to-end warm-up deadlines remain outside
  this phase.
- Strict feedback generation checks can discard otherwise useful independent
  corridor observations when another update wins. The periodic refresh/next query
  can recover; this phase does not merge stale observations automatically.
- Legacy score exporters need a separately reviewed update before their products
  can satisfy the new envelope contract. Actual dataset migration, graph quality,
  memory/performance under Bengaluru scale, tower freshness, model calibration,
  GPU/runtime behavior, and production resource limits were not validated.
- Phase 2B1 topology/metadata, turn-restriction, speed-assumption, and ETA limits
  still apply. Passing synthetic tests does not demonstrate good or legally
  complete routes on the real Bengaluru map.

Work stops at Phase 2B2.
