# API contract

## Production gateway (Phase 2E)

The production image serves the compiled SPA and relative `/api` requests from
one origin. Only `127.0.0.1:8080` is published by default; backend ports are
internal. Gateway `/healthz` indicates liveness, while its container health check
requires prediction, data and routing `/api/ready/*` responses to succeed.
The frontend remains available during warmup. Upstream connection/timeout failures
return JSON HTTP 503 with a short retry hint; backend HTTP 202/loading and
revision errors retain their documented semantics.

The proxy allowlist covers this application's endpoints, not arbitrary service
paths. Unknown `/api/*` paths return 404. Bodies, including public prediction
batches, are limited to 1 MiB; the large internal data-to-prediction batch uses
the service network directly. Proxy connect/read timeouts are 3/90 seconds.
Production CORS defaults to no cross-origin
access; optional `CORS_ORIGINS` must name explicit HTTP origins. Forwarded
client headers are replaced at the gateway and are not trusted by backend Uvicorn.

Route coordinates must contain exactly two finite latitude/longitude values
within [-90, 90] and [-180, 180]. Invalid points return 422 before loading or
snapping to a road. Valid geographic coordinates outside the graph's region
still use the existing nearest-node behavior; this is not evidence of coverage
or legal access outside the supplied map.

Production requires checksum-validated immutable graph/tower/model inputs,
disables ingestion and training, and retains one process per Python service.
Graph publication is writable only by data; routing mounts it read-only.
Unknown tower/model provenance remains unknown.

This document defines the Phase 1 HTTP contract used by the authoritative frontend in
`services/visualization`. Public browser requests use the `/api` prefix through the
gateway. Service-to-service requests use the same paths without `/api` on the target
service.

The field names and lowercase enum values below are the stable machine contract.
Human-readable labels such as `OpenCellID` belong in presentation code and must not be
used for branching.

## Common conventions

- JSON request coordinates are `[latitude, longitude]`.
- GeoJSON coordinates are `[longitude, latitude]`, as required by GeoJSON.
- Connectivity scores are numbers from `0.0` through `1.0`.
- Percentage fields are numbers from `0.0` through `100.0`.
- Unknown or unavailable provenance is explicit; it is never silently relabeled as ML.
- Additive response fields are backward compatible. Removing or renaming a field or
  enum value requires a versioned migration.

## Provenance vocabulary

`source`, `signal_source`, `provenance_source`, and values in `edge_sources` use one of:

| Value | Meaning |
| --- | --- |
| `opencellid` | Every represented observation is backed by OpenCellID tower data. |
| `trai` | Every represented observation is backed by the configured local TRAI-derived source. |
| `ml_synthetic` | Values are model-derived or synthetic and contain no real tower observation. |
| `hybrid` | The result includes both real observations and model/synthetic fallback values. |
| `unknown` | Provenance is absent or cannot be established. |

When all scored edges are real but combine multiple real providers, the aggregate is
`unknown` unless a more specific mixed-real vocabulary is introduced. Per-edge values
remain authoritative. `hybrid` is reserved for a real-data plus ML/synthetic mix.

Readers may accept these temporary aliases while old clients and cached payloads are
migrated. Writers must emit only the canonical lowercase value.

| Accepted alias | Canonical value |
| --- | --- |
| `OpenCellID`, `OpenCelliD`, `open cell id`, `open_cell_id` | `opencellid` |
| `TRAI`, `TRAI India` | `trai` |
| `ML_synthetic`, `ML estimate`, `ml`, `synthetic` | `ml_synthetic` |
| `Hybrid`, `mixed`, `mixed_source`, `opencellid+ml` | `hybrid` |
| missing or unrecognized value | `unknown` |

The `OpenCelliD` spelling is a compatibility alias only.

## Route request

`POST /api/route`

```json
{
  "city": "bangalore",
  "origin": [12.9716, 77.5946],
  "destination": [12.9948, 77.6699],
  "mode": "balanced",
  "vehicle": "bike"
}
```

- `mode`: `fastest`, `balanced`, or `connected`.
- `vehicle`: `scooter`, `bike`, `car`, or `truck`. Bicycle and scooter are distinct
  values and must not be collapsed by clients or services.

Phase 2B1 interprets `bike` as a ridden bicycle, `scooter` as a motor scooter in
the OSM `motorcycle` category, `car` as `motorcar`, and `truck` as `hgv`. It does
not infer a stand-up scooter, moped, delivery exemption, or truck dimensions.

`fastest` minimizes the sum of estimated travel seconds for the selected vehicle
on permitted, represented directed edges. Connectivity and risk affect its
reported metrics but never its route-selection cost. `balanced` and `connected`
retain their existing penalty formulas, using the same vehicle travel times and
access filtering. Low connectivity remains a cost penalty, not an access ban.

Travel time is `length_metres * 3.6 / speed_kph`. A valid edge `speed_kph` is used
as an estimate, constrained by parseable posted limits and the planning ceilings
below. Without a valid estimate, a parseable posted limit is used; otherwise a
documented road-class fallback applies. Cached graph `travel_time` is recalculated
so a car-specific or stale value cannot become another vehicle's ETA.

| Vehicle | Planning speed ceiling (km/h) |
| --- | ---: |
| `bike` | 18 |
| `scooter` | 45 |
| `car` | 120 |
| `truck` | 80 |

These are model assumptions, not verified Bengaluru speeds or statutory limits.
Bare numeric speeds mean km/h; `km/h`, `kmh`, `kph`, `mph`, and `knots` are
recognized. Zero, negative, boolean, nonfinite, or unparseable speeds are invalid.
Aggregated/list values use the lowest parseable positive speed. Road fallbacks
in km/h are motorway 90, trunk 70, primary 50, secondary 40, tertiary 30,
residential 20, construction 15, and unknown/other 25; `_link` roads inherit the
parent class. Vehicle ceilings and represented posted limits still constrain
these values. Invalid/missing edge lengths exclude the edge rather than inventing
a travel distance. Construction roads are excluded by the access policy.

Access checks use the most specific represented vehicle permission before
`motor_vehicle` (for motorized modes), `vehicle`, and `access`. Explicit private,
prohibited, purpose-limited, or unsupported permissions are excluded when the
request cannot establish eligibility. Directional rules require reliable OSM-way
orientation. The router uses only existing graph directions, including for bicycle
one-way exemptions; it never creates a missing reverse edge. Retained conditional
rules, dimensions, barriers, and ambiguous direction metadata are handled
conservatively as described in [the Phase 2B1 report](phase-2b1-routing.md).

The graph is still sourced as a driving network. Missing cycling topology,
discarded historical tags, turn restrictions, and local regulatory defaults are
not established by this API. A successful route is not a claim of complete legal
or physical suitability on the real Bengaluru map.

Time-dependent Bangalore risk rules use India Standard Time. Precomputed routing
weights and route-cache keys are separated into day/night buckets so a cached route
cannot carry the previous bucket's risk costs across the boundary.

Each calculation captures one graph, city-score/provenance version, vehicle weight
set, and Bangalore day/night bucket. A calculation already in progress finishes
using that snapshot even if scores or the time bucket change; the next calculation
captures the current snapshot. Corridor overrides and their risk explanations use
the captured bucket too. Concurrent equivalent calculations share their in-flight
result, and equivalent corridor requests share tower fetching and scoring.

### Graph and score compatibility

The data service is the sole publisher of shared GraphML. Every publication embeds
a new opaque `graph_revision` inside the same atomically replaced file. Reloading
that file preserves its identity. City names, node/edge counts, and filesystem
timestamps are not revision identities; routing uses file stats only to detect a
replacement cheaply. Published graphs are immutable.

City score responses carry `graph_revision` and a separate opaque `score_revision`.
The latter changes when score values, provenance, or associated metadata change,
even if topology and `updated_at` stay unchanged. Revisions are compared for exact
equality, not sorted by wall-clock time. Prediction requests carry the graph
revision and the response must echo it before data accepts the result. The
prediction endpoint still accepts standalone requests without a revision, but
those responses cannot supply verified city scores.

Route responses identify their captured `graph_revision`, city `score_revision`,
and `corridor_score_revision` (null when no compatible corridor response was
available). Score refresh publishes copied graph/weight/provenance state only if
the target graph and expected previous score generation are still current. A late
reply cannot update a replacement graph or overwrite a later score generation.

Route-cache schema 8 accounts for graph and city-score identities, corridor-score
identity, endpoints, vehicle, mode, and the captured day/night bucket. Corridor
scores are checked before cache lookup because observations can change without a
city-score update. Incompatible or unavailable corridor responses retain the
request's compatible city scores; these fallback results are not cached and
rejected overrides never contribute real-data coverage. City-score refresh is
periodic (60 seconds), so compatibility does not imply immediate observation of
every newer score publication.

This protocol assumes one process per service. Process-local locks and atomic file
replacement do not provide coordination for multiple publisher workers/replicas.

### Ready response

HTTP 200 returns:

```json
{
  "mode": "balanced",
  "vehicle": "bike",
  "graph_revision": "graph-example",
  "score_revision": "city-scores-example",
  "corridor_score_revision": "corridor-scores-example",
  "path_geojson": {
    "type": "LineString",
    "coordinates": [[77.5946, 12.9716], [77.6699, 12.9948]]
  },
  "segments": [],
  "signal_segments": [
    {
      "segment_id": "segment-1",
      "coordinates": [[12.9716, 77.5946], [12.9948, 77.6699]],
      "score": 0.72,
      "risk": "low",
      "provenance_source": "opencellid"
    }
  ],
  "total_time_min": 18.4,
  "avg_connectivity": 0.72,
  "route_signal_percent": 72.0,
  "signal_source": "hybrid",
  "tower_count": 42,
  "real_data_coverage_percent": 65.0,
  "good_signal_percent": 70.0,
  "explanation": {
    "summary": "Balanced travel time and connectivity",
    "factors": [],
    "score_breakdown": {"connectivity": 0.72, "speed": 0.8, "risk": 0.1}
  }
}
```

The three percentage fields are intentionally different:

- `route_signal_percent` is the aggregate connectivity score for the selected route,
  expressed as a percentage. During Phase 1 it is equivalent to
  `avg_connectivity * 100`.
- `real_data_coverage_percent` is the percentage of scored route edges with an
  established `opencellid` or `trai` source. Legacy tower records with no source
  evidence remain `unknown` and contribute zero to this percentage, even when used
  to calculate a numerical estimate. ML-filled edges also contribute zero.
- `good_signal_percent` is the percentage of scored route edges whose connectivity
  score is at least `0.6`, regardless of provenance.

`signal_source` is the aggregate provenance. It is `hybrid` when the route mixes
known real and ML/synthetic edges, and `unknown` if any selected edge has unknown
provenance. Each `signal_segments` entry carries its own
`provenance_source`, so clients do not need to infer per-edge provenance from the
aggregate value.

The same selected parallel edge supplies route cost, ETA, geometry, and
connectivity/provenance. Equal-cost parallel edges use the same stable insertion
order tie-break throughout. `total_time_min` sums unrounded selected-vehicle edge
seconds and rounds the total to one decimal minute. It estimates moving time only;
traffic, intersection waits, acceleration, gradients, and driving conditions are
not modeled. Each `signal_segments` geometry includes both endpoints, even at joins
where the aggregate `path_geojson` removes a duplicate coordinate.

For migration only, readers accept `coverage_percent` or `real_data_percent` as aliases
for `real_data_coverage_percent`. During Phase 1, services may emit those aliases in
addition to the authoritative canonical field; new consumers must ignore them. The historic
`coverage_percent` field on `/scores/source/{city}` meant signal quality in some builds;
it must not be copied into both canonical percentages.

### Loading and retry response

When the city graph is warming, `POST /api/route` returns HTTP 202, a `Retry-After`
header, and this body:

```http
HTTP/1.1 202 Accepted
Retry-After: 5
Content-Type: application/json

{"status":"loading","city":"bangalore","message":"Graph is loading","retry_after":5}
```

`Retry-After` is authoritative and may be delta-seconds or an HTTP date. `retry_after`
is the JSON delta-seconds fallback for clients that cannot read the header. Clients
must wait at least one second and retry the same idempotent route calculation request.

During Phase 1, clients also recognize the previous HTTP 503 payload only when it has
`status: "loading"`, `code: "graph_loading"`, or the exact legacy graph-loading
message. Other 503 responses are terminal service errors and must not be retried as a
warm-up response. Servers must emit the HTTP 202 contract after migration.

Phase 2A keeps this response throughout bounded server retries, including backoff.
Data and routing graph loaders allow three attempts for transient I/O/source
failures, with waits of 5 and 10 seconds. A missing shared GraphML publication is
handled separately by routing: it requests data-service preload once, then waits
for publication for at most 10 minutes, polling at 5-second intervals. This covers
cold data-service warm-up without issuing repeated preload or download requests.
These are retry/wait budgets, not a deadline on a graph parse or score calculation.
Readiness remains HTTP 503 until a complete state is available.

An exhausted budget or a nontransient failure produces the terminal HTTP 503 below.
Ordinary route requests do not reset that budget. An explicit
`POST /preload/{city}` on the affected service starts a fresh bounded cycle; a
request during an active preload reuses that work. A replaced shared graph or
expired in-memory graph also enters the HTTP 202 loading flow on the next route.

Phase 2B2 treats absent graph metadata and a successfully returned but absent or
mismatched city-score revision as transient compatibility failures within the same
three-attempt budget (5 and 10 seconds of backoff). They do not start unlimited
retry cycles. Routing checks graph replacement again before publishing a ready
snapshot. A normal city-score transport/parse failure retains the existing
degraded behavior: a freshly loaded graph gets a uniform `0.5` synthetic base with
`score_revision: "unavailable"`; embedded GraphML coverage is discarded. A failed
periodic refresh retains the last compatible snapshot and makes no immediate retry.

Only data may migrate a legacy GraphML without revision metadata: it atomically
republishes the graph with an identity before using it. Routing stays read-only.
Legacy or mismatched real-score files are ignored rather than relabeled as current
coverage; an accepted persisted score file must contain graph/score identities,
scores, and metadata together in one envelope. Separate legacy sidecars cannot
prove compatibility. Route-cache entries from schemas before 8 are discarded;
schema 8 also invalidates older results that counted unknown tower sources as real
coverage.

### Error response

Disconnected endpoints, no permitted directed path, or endpoints snapped to the
same node return terminal HTTP 422 with the existing no-route payload:

```json
{"detail":"No route found. The selected points may be in disconnected areas. Try points closer to main roads."}
```

This response has no `Retry-After` header. The server does not reverse a path or
retry unweighted routing to bypass restrictions or missing/invalid edge weights.
Unexpected pathfinding failures remain server errors rather than being disguised
as a successful fallback route.

Validation errors use HTTP 422. Unsupported cities use HTTP 404. A graph that failed
to load or another unavailable dependency uses HTTP 503 with a non-loading code:

```json
{"status":"error","code":"graph_unavailable","message":"Graph unavailable"}
```

## Corridor scoring

`POST /api/corridor-scores` requires `city`, `graph_revision`, `score_revision`
(the expected city score generation), route endpoints, and an `edge_coords`
object. Admission verifies both revisions against the current city state before
fetching/scoring. Missing required fields return HTTP 422; nonempty revision
mismatches return HTTP 409. There is no automatic mismatch retry on this endpoint.
Its response contains:

```json
{
  "scores": {"segment-1": 0.72},
  "graph_revision": "graph-example",
  "base_score_revision": "city-scores-example",
  "score_revision": "corridor-scores-example",
  "edge_sources": {
    "segment-1": "opencellid",
    "segment-2": "ml_synthetic"
  },
  "source": "hybrid",
  "real_data_source": "opencellid",
  "tower_count": 42,
  "real_data_coverage_percent": 50.0,
  "good_signal_percent": 100.0,
  "bbox": {"min_lat": 0, "min_lon": 0, "max_lat": 0, "max_lon": 0}
}
```

Here `base_score_revision` echoes the admitted city score generation, and
`score_revision` is a deterministic digest of the corridor result and its
identities. Equivalent requests include these identities in their shared-work
key. A request admitted before replacement may finish with its old identities;
only a route holding that compatible snapshot may use it.

Internal `POST /corridor-feedback/{city}` requires `graph_revision`,
`base_score_revision`, corridor `score_revision`, and `scores`; routing also sends
per-edge `edge_sources`.
Feedback is applied under the city lock only while the graph and base score
generation still match; otherwise it returns HTTP 409. A rejected late feedback
does not alter the completed route or trigger a retry. Repeated feedback after a
material city-score update is likewise rejected as stale.

`scores` contains real-data overrides only. `edge_sources` contains an entry for every
requested edge, including uncovered edges marked `ml_synthetic`. The routing engine
retains its existing city-wide score and per-edge provenance for those uncovered
edges; when that base value is estimated, its provenance remains `ml_synthetic`. The
data service must not assign the real-data source of a different edge to the whole
corridor.

On this endpoint, `good_signal_percent` is the share of returned tower-derived overrides
whose score is at least `0.6`. The routing response recomputes its own
`good_signal_percent` across the complete selected path after ML fallback is applied.
`real_data_source` identifies the real provider when it is known. Entries in `scores`
may also be estimates from local records with `unknown` provenance; those entries
are not counted as real-data coverage. Numeric signal quality is not evidence of
provider identity or calibrated coverage.

`GET /api/corridor-towers` returns tower records, `source`, `tower_count`/`count`,
`real_data_coverage_percent`, and the queried bounding box. Empty results are valid and
may still name a real provider when fresh covered tiles authoritatively contain zero
towers; otherwise their provenance is `unknown`.

## City score and cache status

- `GET /api/cities`
- `GET /api/city-context/{city}`
- `GET /api/hotspots/{city}`
- `GET /api/scores/{city}`
- `GET /api/scores/source/{city}`
- `GET /api/cache-status`
- `POST /api/preload/{city}`

`/scores/source/{city}` reports `source`, `tower_count`,
`real_data_coverage_percent`, `good_signal_percent`, `dead_zone_percent`, and
`last_updated`, `graph_revision`, and `score_revision`. `GET /api/scores/{city}`
returns both revisions and additionally reports an `edge_sources` entry
for every returned score; it is the authoritative city-wide per-edge provenance used
when a later corridor query has no override for that edge. `/cache-status` reports
fresh tile ingestion progress separately from fresh real-data coverage; cache
completeness is not a signal-quality metric.

For local validation, `LOCAL_DATA_ONLY=1` disables graph downloads, external tower
requests, credential/dotenv loading, and the background ingestion worker. Existing
local CSV data is queried on demand and retains `LOCAL_TOWER_PROVENANCE` (default
`unknown`); missing local data cannot trigger an external fallback. A missing graph
uses the existing bounded loading/retry behavior. Configure all writable graph,
tower, score, and route-cache paths to a separate working directory. This flag does
not disable the local prediction-service call or authorize prediction model training.

## Prediction and product request handling

The direct service `/predict` accepts `city`, up to 250,000
`segments`, optional `graph_revision`, and optional integer `hour_of_day` (0–23).
Each segment has a unique nonempty `id`, finite latitude/longitude within geographic
bounds, nonnegative finite length in metres, and a highway class. Default hour is
India Standard Time, independent of host timezone. Its seven model inputs are
highway code, latitude, longitude, hour, night flag, city-centre terrain proxy, and
length. An empty batch is valid when the model is ready.

Results include scores clipped to [0,1], the caller's graph revision,
`data_source`, and nullable `confidence`. A legacy bare model reports unknown
training source and null confidence; historical assumed confidence is not exposed
as a calibrated metric. Predictions always remain estimated edge provenance.
Readiness requires successful artifact loading, seven features, and a finite probe.
Missing/corrupt/incompatible models keep liveness available and return readiness
503 and inference 503. Invalid inputs/duplicate IDs return 422; malformed or failed
inference returns a safe 503 detail. Requests do not trigger repeated model loads.
Restore a compatible artifact and restart for recovery.

CPU is the default (`PREDICTION_DEVICE=cpu`, `MODEL_THREADS=2`), with one shared model
and serialized inference. Automatic training is disabled by default. The existing
training path requires the separate, explicit `ALLOW_MODEL_TRAINING=1`; it is not
part of local product startup. Available tower files never cause serving to
retrain/relabel a model. The default manifest uses pinned `xgboost-cpu==3.2.0`,
without CUDA/NCCL dependencies. Optional GPU packaging remains separate.

`GET /api/geocode?q=...` is an explicit, bounded Bengaluru place search through the
data service. Query length is 3–200 characters; coordinates return in `[lat, lon]`
order. Nominatim calls are serialized and spaced at least one second apart, with
a 10-second provider timeout and a 128-entry, 30-minute cache. Missing places return
404; provider/parse failures return a safe 503 suggesting map/coordinate entry.
There are no automatic reverse requests, bulk searches, or geocoding jobs. The
local-only flag disables graph/tower ingestion, while explicit user place search
and browser basemap requests may still access their public providers.

The frontend bounds each route HTTP/body read to 90 seconds and warming retries
to ten minutes, respecting `Retry-After` without shortening it. Input/vehicle
changes abort pending transport and invalidate older response generations. Edited
endpoint text immediately clears previous routes. Explicit retry starts a new
bounded user attempt. Other API reads have 30-second deadlines; prediction readiness
uses five seconds and place search uses fifteen seconds, allowing the provider's
ten-second failure response to reach the user. Malformed successful route geometry/ETA/connectivity is rejected
instead of displayed as an empty zero-valued route. Prediction availability is
shown separately; retained/neutral estimates are never proof that inference ran.

## Gateway health routes

The gateway exposes service-specific, read-only health responses:

- `GET /api/health/data`
- `GET /api/health/routing`
- `GET /api/health/prediction`

It also exposes readiness responses used by Compose dependency gates:

- `GET /api/ready/data`
- `GET /api/ready/routing`
- `GET /api/ready/prediction`

Data and routing readiness is represented by `graph_ready`; prediction readiness is
represented by `model_ready`. The `/ready` HTTP status is authoritative: 200 is ready
and 503 is not ready, while the booleans explain the state in the response body. A
service may be live while still warming and therefore not ready to receive dependent
traffic.

The telemetry service is not exposed here until it is included in the authoritative
Compose runtime.
