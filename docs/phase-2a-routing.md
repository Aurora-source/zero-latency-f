# Phase 2A: routing concurrency, cache consistency, and recovery

Scope: locally implemented after checkpoint `58477a7`; no deployment or next-phase
work. Existing travel-time costs, four vehicle profiles, and provenance fields are
preserved.

## Failure paths and fixes

- Score refresh used to mutate the shared graph before publishing matching vehicle
  weights. A route could read old weights with new provenance and then cache its
  response under a newer score timestamp. Refresh now prepares a replacement graph
  and all vehicle arrays, then publishes them together. Each route holds one
  snapshot through pathfinding, corridor overrides, explanations, and caching.
- Day/night recomputation and score refresh used separate publication paths.
  Both now use the state's writer lock, and route admission captures the current
  India Standard Time bucket under that lock. Published graph/array objects are
  read-only by convention; per-route corridor costs use private arrays.
- Equivalent concurrent routes share one in-flight calculation. Data-service
  corridor tower work and scoring each coalesce equivalent requests. Cancellation
  of a corridor waiter leaves shared work available to the remaining waiters.
  The ingestion worker reserves each queued or active tile through fetching and
  its score-update callback, preventing requeue of the same unfinished ingestion.
  Completion, failure, and stop paths release the reservation for later retries.
  City loading remains protected by a city lock, and data publishes its state only
  after initial coverage hydration and prediction filling finish.
- Data-service score endpoints copy values, update time, and provenance together
  under the same city lock used by score writers.
- Route-cache writers now serialize snapshot capture and publication, write and
  fsync a temporary sibling file, and atomically replace the destination. Failed
  persistence leaves the previous file intact and does not fail a computed route.
  Cache reads/writes return/store independent response objects.
- Cache schema 5 keys include the time bucket and a stable digest of shared graph
  publication metadata, score timestamp, per-edge values, and provenance. An old
  in-flight route cannot replace a current generation's entry. Restart reuse is
  allowed when the same graph publication and scores remain available. Replacing
  the graph or changing scores/provenance invalidates reuse; injected graphs without
  a file identity conservatively get a fresh identity.
- Transient preload failures now have bounded retries and preserve the existing
  HTTP 202 / `Retry-After: 5` contract throughout retry waits. Missing shared graph
  publication has a separate bounded warm-up wait. See the exact behavior in
  [the API contract](api-contract.md#loading-and-retry-response).

## File ownership

The data-service process is the sole publisher of
`GRAPH_CACHE_DIR/<city>.graphml`. It uses a temporary sibling and atomic replacement;
routing only reads the published file and never downloads or rewrites it. Routing
rejects a publication that changes during loading and notices later replacements
at readiness/route admission and score refresh. Local development must point both
services' `GRAPH_CACHE_DIR` at the same directory; Compose already does so.

The routing-engine process owns `ROUTE_CACHE_PATH`. Locks and in-flight registries
coordinate threads/tasks within one service process. This matches the current
one-process-per-service runtime; multiple writer workers or replicas sharing these
paths are not supported by this change. Atomic replacement protects readers from
partial files, but is not a cross-process merge protocol.

## Validation and practical limits

Regression fixtures use small synthetic graphs, temporary files, mocked network
and score dependencies, and controlled concurrency. No real datasets, models, or
credentials are needed. The two existing persistence tests now patch the actual
function globals so their cache files stay in temporary directories.

Validation commands (existing dependencies, CPU execution):

```sh
rtk proxy env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_routing_concurrency.py tests/test_data_concurrency.py
rtk proxy env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
rtk proxy docker compose --env-file /dev/null config --no-interpolate --no-env-resolution --quiet
rtk git diff --check
```

Results on 2026-09-05: focused routing regressions **20 passed**, focused data and
ingestion regressions **13 passed**, and the complete Python suite **80 passed in
2.91 seconds** with 44 existing FastAPI lifecycle deprecation warnings. Compose
configuration validation (without dotenv loading) and `git diff --check` passed.
No frontend files were changed for this phase, so frontend checks were not run.
The six pre-existing line-ending-only modifications were preserved; no staging,
commit, container startup, or deployment was performed.

Remaining limits:

- Rebuilding all vehicle weights while holding the writer lock can delay admission
  of new routes. Copying a scored graph temporarily increases memory use while old
  requests retain their snapshots. Production CPU/memory sizing remains unmeasured.
- Coalescing covers equivalent requests, not every partially overlapping corridor.
  A corridor result can remain cached for its existing ten-minute TTL; this phase
  does not introduce tower-source revisions or broader coverage-quality changes.
- Shared-file revision checks detect publication changes, but graph and score HTTP
  payloads do not yet carry a common cross-service revision identifier. A stronger
  distributed graph/score handshake remains future work.
- Retry counts and publication waiting are bounded; third-party graph parsing,
  graph size, and CPU work do not yet have an end-to-end warm-up deadline. Terminal
  failures require an explicit preload cycle after the dependency is repaired.
- Cache replacement is atomic; full power-loss durability and cross-process writer
  coordination are not claimed. Hard process termination may leave a temporary
  sibling file that is never treated as a valid cache.
- Live service health, real-data route quality, optional GPU concurrency, and
  production resource behavior require separately authorized runtime validation.
  Existing FastAPI lifecycle deprecation warnings remain.
