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

Time-dependent Bangalore risk rules use India Standard Time. Precomputed routing
weights and route-cache keys are separated into day/night buckets so a cached route
cannot carry the previous bucket's risk costs across the boundary.

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

### Error response

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
