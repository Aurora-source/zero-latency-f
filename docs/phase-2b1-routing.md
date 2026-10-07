# Phase 2B1: vehicle legality and travel time

Implemented after local checkpoint `db68867` on `codex/project-completion`.
Only synthetic graph validation is performed. These results do not demonstrate
good, legally complete, or physically suitable routes on the real Bengaluru map.

## Inspection findings and fixes

1. **Vehicle-independent time.** All vehicle arrays and ETA previously reused the
   same graph `travel_time`. The vehicle profiles only changed penalty factors.
   All travel seconds now come from one explicit vehicle speed policy and edge
   length. Stale imported `travel_time` is ignored. Fastest's cost is those seconds
   alone, including during corridor score overrides. Balanced/connected formulas
   are retained and consume the corrected seconds.
2. **Unchecked access.** Vehicle, access, and direction tags previously had no
   effect on edge eligibility. Preparation now excludes prohibited edges in every
   mode; corridor overrides cannot reopen them. Node access/barrier checks use
   the same vehicle classification. These arrays remain part of the Phase 2A
   published snapshot; requests never mutate the graph or shared weights.
3. **Topology removal and unsafe fallback.** Routing used to retain only the
   largest strongly connected component, discarding one-way branches and smaller
   components before snapping. It now retains the supplied directed topology.
   Weighted Dijkstra is the only pathfinder: reverse/unweighted/A* fallback paths
   were removed. A nontraversable edge is hidden from Dijkstra, not just assigned
   an infinite cost that could still appear in a returned path.
4. **Parallel-edge disagreement.** The response resolver accepted negative edge
   indexes and fell back to unconstrained time estimates for missing weights.
   Pathfinding and response assembly now share a selector requiring a nonnegative,
   in-range index and a finite positive weight. Selection, tie-breaking, ETA,
   geometry, and connectivity/provenance consequently use the same edge.
5. **Implicit speed imputation and invalid values.** Graph annotation used OSMnx
   city-wide imputation and clamped some invalid speeds, with incomplete unit
   handling. The router now retains raw speed evidence and explicitly parses it.
   GraphML readers retain malformed speed/time strings so the routing fallback
   policy can handle them instead of failing at deserialization. Invalid lengths
   exclude edges rather than substituting arbitrary metres.
6. **Dropped metadata.** The data service's default OSMnx useful-tag lists omitted
   vehicle-specific access and direction/speed tags. Future imports retain the
   supported tag families and keep simplification boundaries where these tags or
   road class differ. Existing graph files are not regenerated or enriched.
7. **Incomplete signal geometry.** Concatenating the whole path removed the join
   point from later signal segments too. Each per-edge signal geometry now keeps
   its complete endpoints; only the aggregate path deduplicates join points.

Route-cache schema **6** invalidates responses created with the previous cost and
legality semantics. Phase 2A generation identity, locking, request coalescing,
atomic persistence, graph publication ownership, and bounded loading recovery are
retained. Cross-service graph/score revision matching remains a separate follow-up.

## Supported policy and evidence

### Vehicle and speed assumptions

| API vehicle | Specific access/speed-limit key | Planning ceiling |
| --- | --- | ---: |
| `bike` | `bicycle` | 18 km/h |
| `scooter` | `motorcycle` | 45 km/h |
| `car` | `motorcar` | 120 km/h |
| `truck` | `hgv` | 80 km/h |

These are explicit planning assumptions defined in code, not measured speeds
or claims about local speed law. Scooter means a motor scooter, not a stand-up
electric scooter or an independently modeled moped. Truck has no supplied mass,
height, width, axle weight, cargo, or permit data.

Speed priority is valid `speed_kph`, otherwise a valid applicable `maxspeed`,
otherwise the road-class fallback. The result is constrained by the vehicle
ceiling and all applicable parseable generic/vehicle speed limits. Directional
limits take precedence over their nondirectional counterpart when direction is
known. Bare values and `km/h`, `kmh`, `kph` mean kilometres per hour; mph multiplies
by 1.609344 and knots by 1.852. Nonfinite/nonpositive/boolean/unparseable entries
are invalid; list and semicolon aggregates use the minimum valid entry. Ambiguous
directional limits and conditional limits are not silently ignored.

Fallback road speeds and the exact seconds/ETA rounding rule are recorded in
[the API contract](api-contract.md#route-request). For legacy aggregated road
classes without a usable speed, the slowest class fallback is used. A class
fallback estimates moving speed and is not a substitute for missing statutory
limits or representative traffic measurements.

### Access and direction

Specific access keys override broader ones: bicycle uses `bicycle`, `vehicle`,
`access`; motorized vehicles use their specific key, `motor_vehicle`, `vehicle`,
`access`. A directional value at a given specificity precedes its nondirectional
counterpart. Public permissions recognized here are `yes`, `permissive`,
`designated`, `official`, and `discouraged`. Values such as `no`, `private`,
`destination`, `delivery`, `customers`, `dismount`, `use_sidepath`, unknown values,
and contradictory aggregates are excluded when selected by that precedence.
More-specific permissions can override broader denials.

This follows the represented access hierarchy, with conservative handling for
eligibility the request does not supply. OSM documents access scope and
mode-specific overrides in [Key:access](https://wiki.openstreetmap.org/wiki/Key:access).
That source does not establish local legal defaults for missing tags.

Without an explicit mode permission, bicycles are excluded from motorway,
motorway_link, and `motorroad=yes` edges; motorized vehicles are excluded from
cycleway, footway, path, pedestrian, and bridleway edges. Steps, construction,
proposed, and abandoned roads are excluded. This is a conservative route policy,
not an exhaustive jurisdictional legal model. Generic absence of access tags on
other represented roads adds no restriction; it does not establish legal access.

The graph's directed adjacency is authoritative: missing reverse edges remain
missing. Available `oneway:<vehicle>` exceptions only filter existing edges.
OSM's [oneway conventions](https://wiki.openstreetmap.org/wiki/Key:oneway) define
direction relative to the original way, not node IDs or geometry ordering.
The installed OSMnx 2.0.2 code reverses `oneway=-1` paths, replaces the raw tag
with a boolean, and sets `reversed=False` on the resulting forward graph edge.
That boolean representation loses the original way orientation. Directional
access/speed or specific one-way restrictions that need this missing orientation
are excluded conservatively. Unambiguous two-way `reversed` metadata and retained
raw one-way orientation can be interpreted; no direction is guessed from geometry.

Applicable conditional rules are not evaluated. Where they would determine
access/direction/speed, the edge is excluded. Represented `maxweight`, `maxheight`,
`maxwidth`, `maxlength`, and `maxaxleload` constraints also exclude an edge/node
because vehicle dimensions are absent. A represented node barrier requires
explicit permission for that vehicle category. These exclusions can produce
false negatives and need real-data review; they are not evaluations of permits,
opening hours, clearance, barrier position, or complex conditions.

## Validation

All new tests use small synthetic directed multigraphs, synthetic OSM XML/GraphML
in temporary directories, mocked score dependencies, and the existing CPU Python
environment. Paths and seconds are asserted against independently calculated
distances/speeds, not values returned by the implementation itself. The HTTP
no-route case uses an in-memory ASGI transport and starts no service/container.

Focused commands during implementation:

```sh
rtk proxy env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_vehicle_routing.py
rtk proxy env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_routing_concurrency.py tests/test_feature_integrity.py::RoutingModeTests tests/test_feature_integrity.py::BangaloreDefaultTests tests/test_data_concurrency.py::DataConcurrencyTests::test_local_graph_is_not_ready_when_atomic_publication_fails
```

Completion checks:

```sh
rtk proxy env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
rtk proxy docker compose --env-file /dev/null config --no-interpolate --no-env-resolution --quiet
rtk git diff --check
```

Results:

- New vehicle-routing regressions: **55 passed**.
- Focused existing routing/concurrency/data checks: **44 passed**.
- Complete Python suite, run once at completion: **135 passed in 3.57 seconds**,
  with 52 FastAPI lifecycle deprecation warnings.
- Compose configuration validation passed with environment-file loading,
  interpolation, and service environment resolution disabled. No containers ran.
- `git diff --check` passed; new files were also checked for whitespace errors.
  The six pre-existing files have no diff when end-of-line whitespace is ignored.
- Frontend checks were skipped because no frontend files changed in this phase.

These results validate synthetic cases and existing regression coverage. They do
not demonstrate good routes on the real Bengaluru map; no real datasets, live
services, or GPU runtime were tested.

## Changed files

- `services/routing-engine/main.py`: vehicle seconds/access, safe weighted
  selection, directed topology preservation, geometry, and cache schema.
- `services/data-service/main.py`: retained routing metadata, simplification
  boundaries, and tolerant imported speed strings.
- `tests/test_vehicle_routing.py`: deterministic Phase 2B1 regressions.
- `tests/test_routing_concurrency.py`: synthetic ETA/path expectations updated for
  vehicle speed ceilings and graph-loader mock accepts dtype options. Existing
  concurrency assertions remain in place.
- `docs/api-contract.md`: objective, vehicle/speed assumptions, ETA, and no-route
  contract.
- `docs/phase-2b1-routing.md`: this report.

The six pre-existing line-ending-only modifications are preserved. No frontend
source changes, dependency installation, real dataset access, model download,
container startup/build, staging, commit, push, or deployment belongs to this phase.

## Limitations requiring real-data checks

- The authoritative importer still requests `network_type="drive"` with
  `retain_all=False`. Missing bicycle-only roads, contraflow bicycle directions,
  service/access roads filtered by the driving query, and excluded components
  cannot be restored by a runtime filter. No roads or reverse edges were invented.
- Existing GraphML may omit access/speed/direction evidence. Future useful-tag
  retention does not repair old imports. Old simplification can combine differing
  tags; filtering such ambiguity may reject usable routes. The existing 15-metre
  intersection-consolidation stage also needs real-map topology review.
- Turn-restriction relations, lane restrictions, complex conditional permissions,
  temporary closures, vehicle dimensions, and jurisdiction-specific defaults are
  not fully represented/evaluated. Motorcar/HGV tagging interpretation and the
  chosen scooter category require verification against the intended fleet and
  local tagging. See [OSM motorcar scope](https://wiki.openstreetmap.org/wiki/Key:motorcar)
  and [speed-tag conventions](https://wiki.openstreetmap.org/wiki/Key:maxspeed).
- Snapping still chooses the nearest node in the available base graph. It does
  not move an endpoint to another road to evade a restriction. Node snapping,
  geometry lengths, connectivity/provenance quality, and actual route suitability
  need approved real-data evaluation.
- ETA excludes traffic, intersection waits, gradients, acceleration, weather,
  vehicle load, and stop time. Planning ceilings and road fallbacks require
  calibration. A fastest result is fastest within these represented estimates,
  not a prediction of the quickest real Bengaluru journey.
- Phase 2A process-local coordination, graph-copy memory cost, and cross-service
  revision limitations remain. No GPU, live service, or production resource
  validation is claimed by these CPU synthetic tests.

Work stops at Phase 2B1.
