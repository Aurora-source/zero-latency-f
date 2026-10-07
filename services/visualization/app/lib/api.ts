import type { Hotspot } from "./supabase";

const API_BASE = "/api";
export const ROUTE_TIMEOUT_MS = 90_000;

// Include response-body reads in the deadline and propagate input cancellation.
async function boundedFetch(url: string, init: RequestInit = {}, timeoutMs = 30_000): Promise<Response> {
  const controller = new AbortController();
  const cancel = () => controller.abort(init.signal?.reason);
  if (init.signal?.aborted) cancel();
  init.signal?.addEventListener("abort", cancel, { once: true });
  let timedOut = false;
  const timer = window.setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    const body = await response.arrayBuffer();
    return new Response(body, { status: response.status, statusText: response.statusText, headers: response.headers });
  } catch (error) {
    if (timedOut) throw new Error("The request timed out. Try again when the services are ready.");
    if (init.signal?.aborted) throw error;
    throw new Error("Cannot reach the local services. Check they are running, then retry.");
  } finally {
    window.clearTimeout(timer);
    init.signal?.removeEventListener("abort", cancel);
  }
}

export type Strategy = "fastest" | "balanced" | "connected";
export type Vehicle = "scooter" | "bike" | "car" | "truck";
export type RiskLevel = "low" | "medium" | "high";
export type ProvenanceSource =
  | "opencellid"
  | "trai"
  | "ml_synthetic"
  | "hybrid"
  | "unknown";
export type RouteSignalSource =
  | "OpenCellID"
  | "TRAI"
  | "ML estimate"
  | "Hybrid"
  | "Unknown";

export interface RouteExplanationFactor {
  factor: string;
  impact: "positive" | "negative";
  detail: string;
}

export interface RouteExplanation {
  summary: string;
  factors: RouteExplanationFactor[];
  score_breakdown: {
    connectivity: number;
    speed: number;
    risk: number;
  };
  tiers?: Record<string, number>;
  riskiest_segments?: Array<{
    name: string;
    risk: RiskLevel;
    detail: string;
  }>;
}

export interface RouteSegment {
  lat: number;
  lon: number;
  risk: RiskLevel;
}

export interface RouteSignalSegment {
  segment_id?: string;
  coordinates: [number, number][];
  score: number;
  risk: RiskLevel;
  provenanceSource?: ProvenanceSource;
}

export interface RouteResponse {
  graphRevision?: string;
  scoreRevision?: string;
  corridorScoreRevision?: string | null;
  strategy: Strategy;
  vehicle: Vehicle;
  etaMinutes: number;
  connectivity: number;
  coordinates: [number, number][];
  segments: RouteSegment[];
  signalSegments: RouteSignalSegment[];
  signalSource: RouteSignalSource;
  provenanceSource: ProvenanceSource;
  towerCount: number;
  routeSignalPercent: number;
  realDataCoveragePercent: number;
  goodSignalPercent: number;
  explanation: RouteExplanation;
}

export interface RouteLoadingResponse {
  status: "loading";
  strategy: Strategy;
  message: string;
  retryAfter: number;
}

export interface FormattedRoute {
  id: number;
  strategy: Strategy;
  vehicle: Vehicle;
  label: string;
  time: string;
  distance: string;
  connectivity: number;
  color: string;
  warning?: string;
  coordinates: [number, number][];
  segments: RouteSegment[];
  signalSegments: RouteSignalSegment[];
  signalSource: RouteSignalSource;
  provenanceSource: ProvenanceSource;
  towerCount: number;
  routeSignalPercent: number;
  realDataCoveragePercent: number;
  goodSignalPercent: number;
  signalDataLabel: string;
  explanation: RouteExplanation;
}

export interface RouteRequestPayload {
  city: string;
  origin: [number, number];
  destination: [number, number];
  strategy: Strategy;
  vehicle: Vehicle;
}

export interface ViewportBounds {
  minLat: number;
  minLon: number;
  maxLat: number;
  maxLon: number;
  zoom: number;
}

export interface CorridorTower {
  lat: number;
  lon: number;
  radio: string;
  range: number;
}

export interface CorridorTowerResponse {
  towers: CorridorTower[];
  count: number;
  tower_count: number;
  source: ProvenanceSource;
  real_data_coverage_percent: number;
  bbox: {
    min_lat: number;
    min_lon: number;
    max_lat: number;
    max_lon: number;
  };
}

export interface CorridorScoreResponse {
  scores: Record<string, number>;
  edge_sources: Record<string, ProvenanceSource>;
  source: ProvenanceSource;
  tower_count: number;
  real_data_coverage_percent: number;
  good_signal_percent: number;
  bbox: {
    min_lat: number;
    min_lon: number;
    max_lat: number;
    max_lon: number;
  };
}

export async function fetchCities(): Promise<string[]> {
  const res = await boundedFetch(`${API_BASE}/cities`);
  if (!res.ok) throw new Error("Failed to fetch cities");
  const data: unknown = await res.json();
  if (!Array.isArray(data) || !data.every((city) => typeof city === "string")) throw new Error("The city response is invalid. Retry after checking the data service.");
  return data;
}

export interface CityContext {
  center: [number, number];
  origin: [number, number];
  destination: [number, number];
}

export interface ScoreSourceInfo {
  city: string;
  /** Compatibility display value for the current UI. Prefer provenanceSource. */
  source: "TRAI" | "OpenCelliD" | "ML_synthetic" | "Hybrid" | "Unknown";
  provenanceSource: ProvenanceSource;
  tower_count: number;
  real_data_coverage_percent: number;
  good_signal_percent: number;
  /** Legacy field whose historical meaning varied by endpoint. */
  coverage_percent: number;
  dead_zone_percent: number;
  last_updated: string;
}

export interface CoverageStatusInfo {
  city: string;
  total_tiles: number;
  cached_tiles: number;
  remaining_tiles: number;
  percent_complete: number;
  real_data_coverage_percent: number;
  ingestion_running: boolean;
}

export async function fetchPredictionReady(): Promise<boolean> {
  const response = await boundedFetch(`${API_BASE}/ready/prediction`, {}, 5_000);
  if (!response.ok) return false;
  const data = await response.json();
  return data.model_ready === true && data.status === "ready";
}

export async function fetchCityContext(city: string): Promise<CityContext> {
  const res = await boundedFetch(`${API_BASE}/city-context/${city}`);
  if (!res.ok) throw new Error("Failed to fetch city context");
  const data = await res.json();
  if (![data.center, data.origin, data.destination].every(validCoordinates)) throw new Error("The city coordinates are invalid.");
  return {
    center: [data.center[0], data.center[1]],
    origin: [data.origin[0], data.origin[1]],
    destination: [data.destination[0], data.destination[1]],
  };
}

export async function fetchScoreSource(city: string): Promise<ScoreSourceInfo> {
  const res = await boundedFetch(`${API_BASE}/scores/source/${city}`);
  if (!res.ok) {
    throw new Error("Failed to fetch score source");
  }
  const data = await res.json();
  const provenanceSource = normalizeProvenanceSource(
    data.provenance_source ?? data.source,
  );
  const goodSignalPercent = asPercent(
    data.good_signal_percent ?? data.coverage_percent,
  );
  return {
    ...data,
    source: scoreSourceCompatibilityLabel(provenanceSource),
    provenanceSource,
    tower_count: asNumber(data.tower_count),
    real_data_coverage_percent: asPercent(
      data.real_data_coverage_percent ?? data.real_coverage_percent,
    ),
    good_signal_percent: goodSignalPercent,
    coverage_percent: asPercent(data.coverage_percent ?? goodSignalPercent),
    dead_zone_percent: asPercent(data.dead_zone_percent),
  };
}

export async function fetchCoverageStatus(): Promise<CoverageStatusInfo> {
  const res = await boundedFetch(`${API_BASE}/cache-status`);
  if (!res.ok) {
    throw new Error("Failed to fetch coverage status");
  }
  const data = await res.json();
  return {
    city: String(data.city ?? ""),
    total_tiles: asNumber(data.total_tiles),
    cached_tiles: asNumber(data.cached_tiles),
    remaining_tiles: asNumber(data.remaining_tiles),
    percent_complete: asPercent(data.percent_complete),
    real_data_coverage_percent: asPercent(
      data.real_data_coverage_percent ?? data.real_coverage_percent,
    ),
    ingestion_running: Boolean(data.ingestion_running),
  };
}

export async function preloadCity(city: string): Promise<void> {
  const res = await boundedFetch(`${API_BASE}/preload/${city}`, { method: "POST" });
  if (!res.ok) {
    throw new Error(await readError(res));
  }
}

export async function fetchHotspotsForViewport(
  city: string,
  viewport: ViewportBounds,
): Promise<Hotspot[]> {
  const url = new URL(`${window.location.origin}${API_BASE}/hotspots/${city}`);
  url.searchParams.set("min_lat", String(viewport.minLat));
  url.searchParams.set("min_lon", String(viewport.minLon));
  url.searchParams.set("max_lat", String(viewport.maxLat));
  url.searchParams.set("max_lon", String(viewport.maxLon));
  url.searchParams.set("zoom", String(viewport.zoom));

  const res = await boundedFetch(url.toString());
  if (!res.ok) {
    throw new Error(await readError(res));
  }

  const data = await res.json();
  return Array.isArray(data?.hotspots) ? (data.hotspots as Hotspot[]) : [];
}

export async function fetchTowerData(params: {
  origin: [number, number];
  destination: [number, number];
  paddingKm?: number;
}): Promise<CorridorTowerResponse> {
  const url = new URL(`${window.location.origin}${API_BASE}/corridor-towers`);
  url.searchParams.set("origin_lat", String(params.origin[0]));
  url.searchParams.set("origin_lon", String(params.origin[1]));
  url.searchParams.set("dest_lat", String(params.destination[0]));
  url.searchParams.set("dest_lon", String(params.destination[1]));
  url.searchParams.set("padding_km", String(params.paddingKm ?? 3));

  const res = await boundedFetch(url.toString());
  if (!res.ok) {
    throw new Error(await readError(res));
  }

  const data = await res.json();
  return {
    ...data,
    towers: Array.isArray(data.towers) ? data.towers : [],
    count: asNumber(data.count),
    tower_count: asNumber(data.tower_count ?? data.count),
    source: normalizeProvenanceSource(data.provenance_source ?? data.source),
    real_data_coverage_percent: asPercent(
      data.real_data_coverage_percent ?? data.coverage_percent,
    ),
  };
}

export async function fetchSignalCoverage(payload: {
  city: string;
  graphRevision: string;
  scoreRevision: string;
  origin: [number, number];
  destination: [number, number];
  edgeCoords: Record<string, [number, number]>;
  paddingKm?: number;
}): Promise<CorridorScoreResponse> {
  const res = await boundedFetch(`${API_BASE}/corridor-scores`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      city: payload.city,
      graph_revision: payload.graphRevision,
      score_revision: payload.scoreRevision,
      origin: payload.origin,
      destination: payload.destination,
      edge_coords: payload.edgeCoords,
      padding_km: payload.paddingKm ?? 3,
    }),
  });

  if (!res.ok) {
    throw new Error(await readError(res));
  }

  const data = await res.json();
  const scores = Object.fromEntries(
    Object.entries(asObject(data.scores)).map(([segmentId, score]) => [
      segmentId,
      Math.min(1, Math.max(0, asNumber(score))),
    ]),
  );
  const provenanceSource = normalizeProvenanceSource(
    data.provenance_source ?? data.source,
  );
  const rawEdgeSources = asObject(data.edge_sources);
  const edgeIds = [
    ...new Set([
      ...Object.keys(payload.edgeCoords),
      ...Object.keys(rawEdgeSources),
      ...Object.keys(scores),
    ]),
  ];
  const edgeSources = Object.fromEntries(
    edgeIds.map((segmentId) => [
      segmentId,
      !(segmentId in scores)
        ? "ml_synthetic"
        : segmentId in rawEdgeSources
          ? normalizeProvenanceSource(rawEdgeSources[segmentId])
          : provenanceSource === "hybrid"
            ? "unknown"
            : provenanceSource,
    ]),
  ) as Record<string, ProvenanceSource>;
  return {
    ...data,
    scores,
    edge_sources: edgeSources,
    source: provenanceSource,
    tower_count: asNumber(data.tower_count),
    real_data_coverage_percent: asPercent(
      data.real_data_coverage_percent ?? data.coverage_percent,
    ),
    good_signal_percent: asPercent(data.good_signal_percent),
  };
}

export async function geocodeLocation(query: string, signal?: AbortSignal): Promise<[number, number]> {
  const url = new URL(`${window.location.origin}${API_BASE}/geocode`);
  url.searchParams.set("q", query);

  // Allow the provider's 10-second timeout and serialized-request spacing to
  // return the useful map/coordinate fallback before the browser deadline.
  const res = await boundedFetch(url.toString(), { signal }, 15_000);
  if (!res.ok) {
    throw new Error(await readError(res));
  }

  const data = await res.json();
  if (!validCoordinates(data?.coordinates)) throw new Error("Place search returned invalid coordinates. Pick the map instead.");
  return data.coordinates;
}

function haversine(a: [number, number], b: [number, number]): number {
  const radius = 6_371_000;
  const dLat = ((b[0] - a[0]) * Math.PI) / 180;
  const dLon = ((b[1] - a[1]) * Math.PI) / 180;
  const lat1 = (a[0] * Math.PI) / 180;
  const lat2 = (b[0] * Math.PI) / 180;
  const term =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return radius * 2 * Math.atan2(Math.sqrt(term), Math.sqrt(1 - term));
}

function routeDistance(coords: [number, number][]): number {
  let meters = 0;
  for (let index = 0; index < coords.length - 1; index += 1) {
    meters += haversine(coords[index], coords[index + 1]);
  }
  return meters;
}

type JsonObject = Record<string, unknown>;

function asObject(value: unknown): JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
}

function asNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function asPercent(value: unknown): number {
  return Math.min(100, Math.max(0, asNumber(value)));
}

async function readResponseValue(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function responseMessage(value: unknown): string | null {
  if (typeof value === "string") return null;
  const data = asObject(value);
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return "Check the coordinates, vehicle and routing mode, then try again.";
  if (typeof data.message === "string") return data.message;
  return null;
}

async function readError(res: Response): Promise<string> {
  return responseMessage(await readResponseValue(res)) ?? "Route request failed";
}

export function normalizeProvenanceSource(source: unknown): ProvenanceSource {
  const value = String(source ?? "").trim().toLowerCase();

  if (
    value === "opencellid" ||
    value === "open cell id" ||
    value === "open_cell_id"
  ) {
    return "opencellid";
  }
  if (value === "trai" || value === "trai india") {
    return "trai";
  }
  if (
    value === "ml" ||
    value === "ml estimate" ||
    value === "ml_synthetic" ||
    value === "synthetic"
  ) {
    return "ml_synthetic";
  }
  if (
    value === "hybrid" ||
    value === "mixed" ||
    value === "mixed_source" ||
    value === "opencellid+ml"
  ) {
    return "hybrid";
  }
  return "unknown";
}

function displaySignalSource(source: ProvenanceSource): RouteSignalSource {
  if (source === "opencellid") return "OpenCellID";
  if (source === "trai") return "TRAI";
  if (source === "ml_synthetic") return "ML estimate";
  if (source === "hybrid") return "Hybrid";
  return "Unknown";
}

function scoreSourceCompatibilityLabel(
  source: ProvenanceSource,
): ScoreSourceInfo["source"] {
  if (source === "opencellid") return "OpenCelliD";
  if (source === "trai") return "TRAI";
  if (source === "ml_synthetic") return "ML_synthetic";
  if (source === "hybrid") return "Hybrid";
  return "Unknown";
}

function formatSignalSourceLabel(source: ProvenanceSource, towerCount: number): string {
  if (source === "opencellid") {
    return `OpenCellID (${towerCount} towers in corridor)`;
  }
  if (source === "trai") {
    return `TRAI India (${towerCount} towers in corridor)`;
  }
  if (source === "hybrid") {
    return `Hybrid real and estimated data (${towerCount} towers in corridor)`;
  }
  if (source === "unknown") {
    return "Unknown signal provenance";
  }
  return "Model or fallback estimate";
}

function retryAfterSeconds(res: Response, data: JsonObject): number {
  const header = res.headers.get("Retry-After")?.trim();
  if (header) {
    const deltaSeconds = Number(header);
    if (Number.isFinite(deltaSeconds)) {
      if (deltaSeconds >= 0) return Math.max(1, Math.ceil(deltaSeconds));
    } else {
      const retryAt = Date.parse(header);
      if (Number.isFinite(retryAt)) {
        return Math.max(1, Math.ceil((retryAt - Date.now()) / 1000));
      }
    }
  }

  const bodyValue = asNumber(data.retry_after ?? data.retryAfter, 10);
  return bodyValue >= 0 ? Math.max(1, Math.ceil(bodyValue)) : 10;
}

function isTemporaryLoadingResponse(status: number, data: JsonObject): boolean {
  if (status === 202) return true;
  if (status !== 503) return false;

  const state = String(data.status ?? "").trim().toLowerCase();
  const code = String(data.code ?? "").trim().toLowerCase();
  const message = responseMessage(data)?.trim().toLowerCase() ?? "";
  return (
    state === "loading" ||
    code === "graph_loading" ||
    message === "graph not loaded" ||
    message === "graph is still loading" ||
    message === "graph is loading" ||
    message === "graph loading" ||
    message === "graph loading, please wait..."
  );
}

export function isRouteLoadingResponse(
  value: RouteResponse | RouteLoadingResponse,
): value is RouteLoadingResponse {
  return "status" in value && value.status === "loading";
}

export async function fetchRoute(
  payload: RouteRequestPayload,
  signal?: AbortSignal,
): Promise<RouteResponse | RouteLoadingResponse> {
  const res = await boundedFetch(`${API_BASE}/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      city: payload.city,
      origin: payload.origin,
      destination: payload.destination,
      mode: payload.strategy,
      vehicle: payload.vehicle,
    }),
    signal,
  }, ROUTE_TIMEOUT_MS);
  const responseValue = await readResponseValue(res);
  const data = asObject(responseValue);

  if (isTemporaryLoadingResponse(res.status, data)) {
    return {
      status: "loading",
      strategy: payload.strategy,
      message:
        responseMessage(data) ?? "Graph loading, please wait...",
      retryAfter: retryAfterSeconds(res, data),
    };
  }

  if (!res.ok) {
    throw new Error(responseMessage(responseValue) ?? "Route request failed");
  }

  const pathGeoJson = asObject(data.path_geojson);
  if (pathGeoJson.type !== "LineString" || !Array.isArray(pathGeoJson.coordinates) || pathGeoJson.coordinates.length < 2 ||
      !pathGeoJson.coordinates.every((point) => Array.isArray(point) && validCoordinates([point[1], point[0]])) ||
      typeof data.total_time_min !== "number" || !Number.isFinite(data.total_time_min) || data.total_time_min < 0 ||
      typeof data.avg_connectivity !== "number" || !Number.isFinite(data.avg_connectivity) || data.avg_connectivity < 0 || data.avg_connectivity > 1 ||
      (data.vehicle !== undefined && data.vehicle !== payload.vehicle) || (data.mode !== undefined && data.mode !== payload.strategy)) {
    throw new Error("The routing service returned an invalid route. Please retry.");
  }
  const coordinates: [number, number][] =
    Array.isArray(pathGeoJson.coordinates)
      ? pathGeoJson.coordinates.flatMap((coordinate) => {
          if (!Array.isArray(coordinate) || coordinate.length < 2) return [];
          const lon = Number(coordinate[0]);
          const lat = Number(coordinate[1]);
          return Number.isFinite(lat) && Number.isFinite(lon)
            ? ([[lat, lon]] as [number, number][])
            : [];
        })
      : [];
  const provenanceSource = normalizeProvenanceSource(
    data.provenance_source ?? data.signal_source ?? data.source,
  );
  const routeEdgeSources = asObject(data.edge_sources);
  if (Array.isArray(data.signal_segments) && !data.signal_segments.every((rawSegment) => {
    const segment = asObject(rawSegment);
    return Array.isArray(segment.coordinates) && segment.coordinates.length >= 2 && segment.coordinates.every(validCoordinates) &&
      typeof segment.score === "number" && Number.isFinite(segment.score) && segment.score >= 0 && segment.score <= 1;
  })) throw new Error("The routing service returned invalid signal geometry. Please retry.");
  const signalSegments = Array.isArray(data.signal_segments)
    ? data.signal_segments.map((rawSegment) => {
        const segment = asObject(rawSegment);
        const segmentId = String(segment.segment_id ?? "");
        return {
          ...segment,
          coordinates: Array.isArray(segment.coordinates) ? segment.coordinates : [],
          provenanceSource: normalizeProvenanceSource(
            segment.provenance_source ??
              segment.provenanceSource ??
              segment.source ??
              routeEdgeSources[segmentId] ??
              "unknown",
          ),
        } as RouteSignalSegment;
      })
    : [];

  return {
    graphRevision: typeof data.graph_revision === "string" ? data.graph_revision : undefined,
    scoreRevision: typeof data.score_revision === "string" ? data.score_revision : undefined,
    corridorScoreRevision: typeof data.corridor_score_revision === "string" ? data.corridor_score_revision : null,
    strategy: payload.strategy,
    vehicle: (data.vehicle ?? payload.vehicle) as Vehicle,
    etaMinutes: asNumber(data.total_time_min),
    connectivity: asNumber(data.avg_connectivity),
    coordinates,
    segments: Array.isArray(data.segments) ? (data.segments as RouteSegment[]) : [],
    signalSegments,
    signalSource: displaySignalSource(provenanceSource),
    provenanceSource,
    towerCount: asNumber(data.tower_count),
    routeSignalPercent: asPercent(
      data.route_signal_percent ?? asNumber(data.avg_connectivity) * 100,
    ),
    realDataCoveragePercent: asPercent(
      data.real_data_coverage_percent ?? data.coverage_percent ?? data.real_data_percent,
    ),
    goodSignalPercent: asPercent(data.good_signal_percent),
    explanation:
      validExplanation(data.explanation) ? data.explanation : {
        summary: "No explanation available",
        factors: [],
        score_breakdown: { connectivity: 0, speed: 0, risk: 0 },
      },
  };
}

function validCoordinates(value: unknown): value is [number, number] {
  return Array.isArray(value) && value.length === 2 && value.every((item) => typeof item === "number" && Number.isFinite(item)) && Math.abs(value[0]) <= 90 && Math.abs(value[1]) <= 180;
}

function validExplanation(value: unknown): value is RouteExplanation {
  const data = asObject(value);
  const breakdown = asObject(data.score_breakdown);
  return typeof data.summary === "string" && Array.isArray(data.factors) &&
    data.factors.every((factor) => { const entry = asObject(factor); return typeof entry.factor === "string" && typeof entry.detail === "string" && ["positive", "negative"].includes(String(entry.impact)); }) &&
    [breakdown.connectivity, breakdown.speed, breakdown.risk].every((score) => typeof score === "number" && Number.isFinite(score));
}

export function formatRouteForUI(route: RouteResponse, color: string): FormattedRoute {
  const distanceKm = routeDistance(route.coordinates) / 1000;
  return {
    id: route.strategy === "connected" ? 0 : route.strategy === "balanced" ? 1 : 2,
    strategy: route.strategy,
    vehicle: route.vehicle,
    label:
      route.strategy === "connected"
        ? "Most Connected"
        : route.strategy === "balanced"
          ? "Balanced"
          : "Fastest",
    time: `${route.etaMinutes.toFixed(1)} min`,
    distance: `${distanceKm.toFixed(1)} km`,
    connectivity: route.connectivity ?? 0,
    color,
    warning:
      route.provenanceSource === "ml_synthetic"
        ? "Estimated signal; measured coverage is unavailable"
        : route.provenanceSource === "unknown"
          ? "Signal data provenance is unavailable"
          : route.strategy === "fastest" && (route.connectivity ?? 0) < 0.5
            ? "Low network coverage on some segments"
            : undefined,
    coordinates: route.coordinates,
    segments: route.segments,
    signalSegments: route.signalSegments,
    signalSource: route.signalSource,
    provenanceSource: route.provenanceSource,
    towerCount: route.towerCount,
    routeSignalPercent: route.routeSignalPercent,
    realDataCoveragePercent: route.realDataCoveragePercent,
    goodSignalPercent: route.goodSignalPercent,
    signalDataLabel: formatSignalSourceLabel(route.provenanceSource, route.towerCount),
    explanation: route.explanation,
  };
}
