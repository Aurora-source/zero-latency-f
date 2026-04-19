import type { Hotspot } from "./supabase";

const API_BASE = "/api";

export type Strategy = "fastest" | "balanced" | "connected";
export type Vehicle = "scooter" | "bike" | "car" | "truck";
export type RiskLevel = "low" | "medium" | "high";
export type RouteSignalSource = "OpenCellID" | "TRAI" | "ML estimate";

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
}

export interface RouteResponse {
  strategy: Strategy;
  vehicle: Vehicle;
  etaMinutes: number;
  connectivity: number;
  coordinates: [number, number][];
  segments: RouteSegment[];
  signalSegments: RouteSignalSegment[];
  signalSource: RouteSignalSource;
  towerCount: number;
  coveragePercent: number;
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
  towerCount: number;
  coveragePercent: number;
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
  bbox: {
    min_lat: number;
    min_lon: number;
    max_lat: number;
    max_lon: number;
  };
}

export interface CorridorScoreResponse {
  scores: Record<string, number>;
  source: "OpenCellID" | "ML estimate";
  tower_count: number;
  bbox: {
    min_lat: number;
    min_lon: number;
    max_lat: number;
    max_lon: number;
  };
  coverage_percent?: number;
}

export async function fetchCities(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/cities`);
  if (!res.ok) throw new Error("Failed to fetch cities");
  return res.json();
}

export interface CityContext {
  center: [number, number];
  origin: [number, number];
  destination: [number, number];
}

export interface ScoreSourceInfo {
  city: string;
  source: "TRAI" | "OpenCellID" | "ML_synthetic";
  tower_count: number;
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
  coverage_percent: number;
  real_coverage_tiles: number;
  real_coverage_percent: number;
  ingestion_running: boolean;
}

export async function fetchCityContext(city: string): Promise<CityContext> {
  const res = await fetch(`${API_BASE}/city-context/${city}`);
  if (!res.ok) throw new Error("Failed to fetch city context");
  const data = await res.json();
  return {
    center: [data.center[0], data.center[1]],
    origin: [data.origin[0], data.origin[1]],
    destination: [data.destination[0], data.destination[1]],
  };
}

export async function fetchScoreSource(city: string): Promise<ScoreSourceInfo> {
  const res = await fetch(`${API_BASE}/scores/source/${city}`);
  if (!res.ok) {
    throw new Error("Failed to fetch score source");
  }
  const data = (await res.json()) as ScoreSourceInfo;
  const normalized = normalizeSignalSource(data.source);
  return {
    ...data,
    source:
      normalized === "OpenCellID"
        ? "OpenCellID"
        : normalized === "TRAI"
          ? "TRAI"
          : "ML_synthetic",
  };
}

export async function fetchCoverageStatus(): Promise<CoverageStatusInfo> {
  const res = await fetch(`${API_BASE}/cache-status`);
  if (!res.ok) {
    throw new Error("Failed to fetch coverage status");
  }
  return res.json();
}

export async function preloadCity(city: string): Promise<void> {
  const res = await fetch(`${API_BASE}/preload/${city}`, { method: "POST" });
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

  const res = await fetch(url.toString());
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

  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error(await readError(res));
  }

  return res.json();
}

export async function fetchSignalCoverage(payload: {
  origin: [number, number];
  destination: [number, number];
  edgeCoords: Record<string, [number, number]>;
  paddingKm?: number;
}): Promise<CorridorScoreResponse> {
  const res = await fetch(`${API_BASE}/corridor-scores`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      origin: payload.origin,
      destination: payload.destination,
      edge_coords: payload.edgeCoords,
      padding_km: payload.paddingKm ?? 3,
    }),
  });

  if (!res.ok) {
    throw new Error(await readError(res));
  }

  return res.json();
}

export async function geocodeLocation(query: string): Promise<[number, number]> {
  const url = new URL("https://nominatim.openstreetmap.org/search");
  url.searchParams.set("q", query);
  url.searchParams.set("format", "json");
  url.searchParams.set("limit", "1");

  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error("Failed to search location");
  }

  const results = (await res.json()) as Array<{ lat: string; lon: string }>;
  if (!results.length) {
    throw new Error("Location not found");
  }

  const lat = Number(results[0].lat);
  const lon = Number(results[0].lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    throw new Error("Location not found");
  }

  return [lat, lon];
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

async function readError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
    if (typeof data?.message === "string") return data.message;
  } catch {
    const text = await res.text();
    if (text) return text;
  }
  return "Route request failed";
}

function formatSignalSourceLabel(source: string, towerCount: number): string {
  const normalizedSource = normalizeSignalSource(source);
  if (normalizedSource === "OpenCellID") {
    return `OpenCellID (${towerCount} towers in corridor)`;
  }
  if (normalizedSource === "TRAI") {
    return `TRAI India (${towerCount} towers in corridor)`;
  }
  return "ML estimate";
}

function normalizeSignalSource(source: unknown): RouteSignalSource {
  if (!source) {
    return "ML estimate";
  }

  const value = String(source).trim().toLowerCase();

  if (value.includes("opencell")) {
    return "OpenCellID";
  }
  if (value.includes("real")) {
    return "OpenCellID";
  }
  if (value === "trai" || value === "trai india") {
    return "TRAI";
  }
  if (value.includes("ml") || value.includes("synthetic")) {
    return "ML estimate";
  }
  return "ML estimate";
}

function shouldWarnForMlFallback(source: RouteSignalSource) {
  return source === "ML estimate";
}

export function isRouteLoadingResponse(
  value: RouteResponse | RouteLoadingResponse,
): value is RouteLoadingResponse {
  return "status" in value && value.status === "loading";
}

export async function fetchRoute(
  payload: RouteRequestPayload,
): Promise<RouteResponse | RouteLoadingResponse> {
  const res = await fetch(`${API_BASE}/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      city: payload.city,
      origin: payload.origin,
      destination: payload.destination,
      mode: payload.strategy,
      vehicle: payload.vehicle,
    }),
  });

  if (res.status === 202) {
    const data = await res.json();
    return {
      status: "loading",
      strategy: payload.strategy,
      message: data.message ?? "Graph loading, please wait...",
      retryAfter: Number(data.retry_after ?? 10),
    };
  }

  if (!res.ok) {
    throw new Error(await readError(res));
  }

  const data = await res.json();
  const coordinates: [number, number][] =
    data.path_geojson?.coordinates?.map(([lon, lat]: [number, number]) => [
      lat,
      lon,
    ]) ?? [];

  console.log("route coverage:", Number(data.coverage_percent ?? data.real_data_percent ?? 0));
  console.log("route source:", data.signal_source ?? data.source ?? "ML estimate");

  return {
    strategy: payload.strategy,
    vehicle: (data.vehicle ?? payload.vehicle) as Vehicle,
    etaMinutes: data.total_time_min ?? 0,
    connectivity: data.avg_connectivity ?? 0,
    coordinates,
    segments: data.segments ?? [],
    signalSegments:
      data.signal_segments?.map((segment: RouteSignalSegment) => ({
        ...segment,
        coordinates: segment.coordinates ?? [],
      })) ?? [],
    signalSource: normalizeSignalSource(data.signal_source ?? data.source),
    towerCount: Number(data.tower_count ?? 0),
    coveragePercent: Number(data.coverage_percent ?? data.real_data_percent ?? 0),
    explanation: data.explanation ?? {
      summary: "No explanation available",
      factors: [],
      score_breakdown: { connectivity: 0, speed: 0, risk: 0 },
    },
  };
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
      shouldWarnForMlFallback(route.signalSource)
        ? "Signal data unavailable - using ML estimate"
        : route.strategy === "fastest" && (route.connectivity ?? 0) < 0.5
          ? "Low network coverage on some segments"
          : undefined,
    coordinates: route.coordinates,
    segments: route.segments,
    signalSegments: route.signalSegments,
    signalSource: route.signalSource,
    towerCount: route.towerCount,
    coveragePercent: route.coveragePercent,
    signalDataLabel: formatSignalSourceLabel(route.signalSource, route.towerCount),
    explanation: route.explanation,
  };
}
