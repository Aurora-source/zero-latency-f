import axios from "axios";

export const API = axios.create({
  baseURL: "https://api.rikon-karmakar.quest",
  timeout: 20000,
});

export type RouteMode = "fastest" | "balanced" | "connected";
export type VehicleType = "scooter" | "bike" | "car" | "truck";

export interface CacheStatusResponse {
  status?: string;
  total_tiles?: number;
  cached_tiles?: number;
  remaining_tiles?: number;
  percent_complete?: number;
  coverage_percent?: number;
  real_coverage_percent?: number;
  tile_count?: number;
  ingestion_running?: boolean;
}

export interface RouteRequestPayload {
  city: string;
  origin: [number, number];
  destination: [number, number];
  mode: RouteMode;
  vehicle: VehicleType;
}

export interface RouteResponse {
  coordinates?: [number, number][];
  total_time_min?: number;
  avg_connectivity?: number;
  signal_source?: string;
  tower_count?: number;
  coverage_percent?: number;
  explanation?: {
    summary?: string;
  };
}

export interface CorridorScoresPayload {
  origin: [number, number];
  destination: [number, number];
  edge_coords: Record<string, [number, number]>;
  padding_km?: number;
}

export interface CorridorScoresResponse {
  scores: Record<string, number>;
  source?: string;
  tower_count?: number;
  coverage_percent?: number;
}

export interface PredictSegmentPayload {
  id: string;
  highway: string;
  lat: number;
  lon: number;
  length: number;
}

export interface PredictRequestPayload {
  city: string;
  segments: PredictSegmentPayload[];
}

export interface PredictResponse {
  scores: Record<string, number>;
  data_source?: string;
  confidence?: number;
}

export const DEFAULT_ROUTE_REQUEST: RouteRequestPayload = {
  city: "bangalore",
  origin: [12.9716, 77.5946],
  destination: [12.9948, 77.6699],
  mode: "balanced",
  vehicle: "car",
};

export const DEFAULT_PREDICTION_REQUEST: PredictRequestPayload = {
  city: "bangalore",
  segments: [
    {
      id: "dashboard-current",
      highway: "primary",
      lat: 12.9716,
      lon: 77.5946,
      length: 180,
    },
  ],
};

async function callApi<T>(endpoint: string, request: () => Promise<{ data: T }>): Promise<T> {
  console.log("Calling API:", endpoint);
  try {
    const response = await request();
    return response.data;
  } catch (error) {
    console.error("API ERROR:", error);
    throw error;
  }
}

export async function fetchCacheStatus(): Promise<CacheStatusResponse> {
  return callApi("/cache-status", () => API.get<CacheStatusResponse>("/cache-status"));
}

export async function fetchRoute(
  payload: RouteRequestPayload,
): Promise<RouteResponse> {
  return callApi("/route", () => API.post<RouteResponse>("/route", payload));
}

export async function fetchCorridorScores(
  payload: CorridorScoresPayload,
): Promise<CorridorScoresResponse> {
  return callApi(
    "/corridor-scores",
    () => API.post<CorridorScoresResponse>("/corridor-scores", payload),
  );
}

export async function fetchPrediction(
  payload: PredictRequestPayload,
): Promise<PredictResponse> {
  return callApi("/predict", () => API.post<PredictResponse>("/predict", payload));
}
