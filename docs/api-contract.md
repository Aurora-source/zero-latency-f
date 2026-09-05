# API contract

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

### Ready response

HTTP 200 returns:

```json
{
  "mode": "balanced",
  "vehicle": "bike",
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
- `real_data_coverage_percent` is the percentage of scored route edges whose value is
  backed by a real tower observation. The provider may be `unknown` when the data is
  known to be observed but its provider cannot be established. An ML-filled edge is
  not real coverage.
- `good_signal_percent` is the percentage of scored route edges whose connectivity
  score is at least `0.6`, regardless of provenance.

`signal_source` is the aggregate provenance. It is `hybrid` whenever the route mixes
real and estimated edges. Each `signal_segments` entry carries its own
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

`POST /api/corridor-scores` accepts the route endpoints plus an `edge_coords` object.
Its response contains:

```json
{
  "scores": {"segment-1": 0.72},
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

`scores` contains real-data overrides only. `edge_sources` contains an entry for every
requested edge, including uncovered edges marked `ml_synthetic`. The routing engine
retains its existing city-wide score and per-edge provenance for those uncovered
edges; when that base value is estimated, its provenance remains `ml_synthetic`. The
data service must not assign the real-data source of a different edge to the whole
corridor.

On this endpoint, `good_signal_percent` is the share of returned real-data overrides
whose score is at least `0.6`. The routing response recomputes its own
`good_signal_percent` across the complete selected path after ML fallback is applied.
`real_data_source` identifies the real provider when it is known; it may be `unknown`
without changing the fact that entries in `scores` are real-data overrides.

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
`last_updated`. `GET /api/scores/{city}` additionally reports an `edge_sources` entry
for every returned score; it is the authoritative city-wide per-edge provenance used
when a later corridor query has no override for that edge. `/cache-status` reports
fresh tile ingestion progress separately from fresh real-data coverage; cache
completeness is not a signal-quality metric.

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
