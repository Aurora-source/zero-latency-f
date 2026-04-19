import type { Hotspot } from "./supabase";

const API_BASE = "/api";

export type Strategy = "fastest" | "balanced" | "connected";
export type Vehicle = "scooter" | "bike" | "car" | "truck";
export type RiskLevel = "low" | "medium" | "high";

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

export interface RouteResponse {
  strategy: Strategy;
  vehicle: Vehicle;
  etaMinutes: number;
  connectivity: number;
  coordinates: [number, number][];
  segments: RouteSegment[];
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
  explanation: RouteExplanation;
}

export interface RouteRequestPayload {
  city: string;
  origin: [number, number];
  destination: [number, number];
  strategy: Strategy;
  vehicle: Vehicle;
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

export async function preloadCity(city: string): Promise<void> {
  const res = await fetch(`${API_BASE}/preload/${city}`, { method: "POST" });
  if (!res.ok) {
    throw new Error(await readError(res));
  }
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

  return {
    strategy: payload.strategy,
    vehicle: (data.vehicle ?? payload.vehicle) as Vehicle,
    etaMinutes: data.total_time_min ?? 0,
    connectivity: data.avg_connectivity ?? 0,
    coordinates,
    segments: data.segments ?? [],
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
      route.strategy === "fastest" && (route.connectivity ?? 0) < 0.5
        ? "Low network coverage on some segments"
        : undefined,
    coordinates: route.coordinates,
    segments: route.segments,
    explanation: route.explanation,
  };
}

export async function fetchHotspotsFromBackend(): Promise<Hotspot[]> {
  return [];
}
