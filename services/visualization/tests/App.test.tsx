import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ProvenanceSource,
  RouteRequestPayload,
  RouteResponse,
  Strategy,
} from "../app/lib/api";

const apiMocks = vi.hoisted(() => ({
  fetchCities: vi.fn(),
  fetchCityContext: vi.fn(),
  fetchCoverageStatus: vi.fn(),
  fetchHotspotsForViewport: vi.fn(),
  fetchPredictionReady: vi.fn(),
  fetchRoute: vi.fn(),
  fetchScoreSource: vi.fn(),
  geocodeLocation: vi.fn(),
  preloadCity: vi.fn(),
}));

vi.mock("../app/components/MapView", () => ({
  default: () => <div data-testid="map-view">Map ready</div>,
}));

vi.mock("../app/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../app/lib/api")>();
  return {
    ...original,
    ...apiMocks,
  };
});

import App from "../app/App";

function routeFor(
  strategy: Strategy,
  vehicle: RouteRequestPayload["vehicle"],
  provenanceSource: ProvenanceSource,
): RouteResponse {
  const signalSource =
    provenanceSource === "hybrid"
      ? "Hybrid"
      : provenanceSource === "unknown"
        ? "Unknown"
        : provenanceSource === "ml_synthetic"
          ? "ML estimate"
          : provenanceSource === "trai"
            ? "TRAI"
            : "OpenCellID";

  return {
    strategy,
    vehicle,
    etaMinutes: strategy === "connected" ? 20 : strategy === "balanced" ? 18 : 15,
    connectivity: strategy === "connected" ? 0.85 : strategy === "balanced" ? 0.65 : 0.4,
    coordinates: [
      [12.9716, 77.5946],
      [12.9948, 77.6699],
    ],
    segments: [],
    signalSegments: [],
    signalSource,
    provenanceSource,
    towerCount: provenanceSource === "hybrid" ? 12 : 0,
    routeSignalPercent: strategy === "connected" ? 85 : 65,
    realDataCoveragePercent: provenanceSource === "hybrid" ? 50 : 0,
    goodSignalPercent: strategy === "connected" ? 75 : 50,
    explanation: {
      summary: `${strategy} route explanation`,
      factors: [],
      score_breakdown: { connectivity: 0.7, speed: 0.7, risk: 0.2 },
    },
  };
}

async function flushMicrotasks() {
  await act(async () => {
    for (let index = 0; index < 10; index += 1) {
      await Promise.resolve();
    }
  });
}

beforeEach(() => {
  apiMocks.fetchPredictionReady.mockResolvedValue(true);
  apiMocks.fetchCities.mockResolvedValue(["bangalore"]);
  apiMocks.fetchCityContext.mockResolvedValue({
    center: [12.9716, 77.5946],
    origin: [12.9716, 77.5946],
    destination: [12.9948, 77.6699],
  });
  apiMocks.fetchCoverageStatus.mockResolvedValue({
    city: "bangalore",
    total_tiles: 10,
    cached_tiles: 5,
    remaining_tiles: 5,
    percent_complete: 50,
    real_data_coverage_percent: 50,
    ingestion_running: false,
  });
  apiMocks.fetchHotspotsForViewport.mockResolvedValue([]);
  apiMocks.fetchScoreSource.mockResolvedValue({
    city: "bangalore",
    source: "Unknown",
    provenanceSource: "unknown",
    tower_count: 0,
    real_data_coverage_percent: 0,
    good_signal_percent: 50,
    coverage_percent: 50,
    dead_zone_percent: 0,
    last_updated: "",
  });
  apiMocks.fetchRoute.mockImplementation(async (request: RouteRequestPayload) =>
    routeFor(
      request.strategy,
      request.vehicle,
      request.strategy === "connected"
        ? "hybrid"
        : request.strategy === "balanced"
          ? "unknown"
          : "ml_synthetic",
    ),
  );
  apiMocks.geocodeLocation.mockResolvedValue([12.9716, 77.5946]);
  apiMocks.preloadCity.mockResolvedValue(undefined);
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockResolvedValue(
      new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }),
    ),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("ignores device location received after the user edits the origin", async () => {
    let finish!: PositionCallback;
    const original = Object.getOwnPropertyDescriptor(navigator, "geolocation");
    Object.defineProperty(navigator, "geolocation", { configurable: true, value: {
      getCurrentPosition: (success: PositionCallback) => { finish = success; },
    } });
    try {
      render(<App />);
      await waitFor(() => expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(3));
      fireEvent.click(screen.getByRole("button", { name: "Locate my origin" }));
      const origin = screen.getByRole("textbox", { name: "Origin" });
      fireEvent.change(origin, { target: { value: "12.98, 77.61" } });
      await act(async () => finish({ coords: { latitude: 13, longitude: 77.7 } } as GeolocationPosition));
      expect(origin).toHaveValue("12.98, 77.61");
      expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(3);
      expect(screen.getByText("Set origin and destination to load routes.")).toBeInTheDocument();
    } finally {
      if (original) Object.defineProperty(navigator, "geolocation", original);
      else Reflect.deleteProperty(navigator, "geolocation");
    }
  });

  it("does not let a late city context overwrite edited endpoints", async () => {
    let finish!: (context: { center: number[]; origin: number[]; destination: number[] }) => void;
    apiMocks.fetchCityContext.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    render(<App />);
    await waitFor(() => expect(apiMocks.fetchCityContext).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByRole("textbox", { name: "Origin" }), { target: { value: "12.98, 77.61" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm origin" }));
    await act(async () => finish({ center: [12.97, 77.59], origin: [12.97, 77.59], destination: [12.99, 77.62] }));
    await waitFor(() => expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(3));
    expect(apiMocks.fetchRoute.mock.calls[0][0].origin).toEqual([12.98, 77.61]);
  });
  it("clears routes on text edits and ignores a late previous response", async () => {
    const pending: Array<{ request: RouteRequestPayload; resolve: (route: RouteResponse) => void }> = [];
    apiMocks.fetchRoute.mockImplementation((request: RouteRequestPayload) => new Promise((resolve) => pending.push({ request, resolve })));
    render(<App />);
    await waitFor(() => expect(pending).toHaveLength(3));
    const oldSignal = apiMocks.fetchRoute.mock.calls[0][1] as AbortSignal;
    fireEvent.change(screen.getByRole("textbox", { name: "Destination" }), { target: { value: "12.98, 77.62" } });
    expect(oldSignal.aborted).toBe(true);
    expect(screen.getByText("Set origin and destination to load routes.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm destination" }));
    await waitFor(() => expect(pending).toHaveLength(6));
    await act(async () => { pending.slice(3).forEach(({ request, resolve }) => resolve({ ...routeFor(request.strategy, request.vehicle, "unknown"), etaMinutes: 7 })); });
    expect(screen.getAllByText("7.0 min")).toHaveLength(3);
    await act(async () => { pending.slice(0, 3).forEach(({ request, resolve }) => resolve(routeFor(request.strategy, request.vehicle, "hybrid"))); });
    expect(screen.getAllByText("7.0 min")).toHaveLength(3);
    expect(screen.queryByText("18.0 min")).not.toBeInTheDocument();
  });

  it("ignores a late location search after the user types a new endpoint", async () => {
    let finish!: (point: [number, number]) => void;
    apiMocks.geocodeLocation.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    render(<App />);
    await waitFor(() => expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(3));
    const destination = screen.getByRole("textbox", { name: "Destination" });
    fireEvent.change(destination, { target: { value: "Old search" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm destination" }));
    fireEvent.change(destination, { target: { value: "New search" } });
    await act(async () => finish([13, 77.7]));
    expect(destination).toHaveValue("New search");
    expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(3);
  });

  it("bounds pathological loading retries and offers retry", async () => {
    apiMocks.fetchRoute.mockImplementation(async (request: RouteRequestPayload) => ({ status: "loading", strategy: request.strategy, message: "Loading", retryAfter: 3600 }));
    render(<App />);
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(3);
    expect(screen.getAllByText(/taking too long/).length).toBeGreaterThan(0);
  });

  it("shows prediction failure while keeping available routes usable", async () => {
    apiMocks.fetchPredictionReady.mockRejectedValue(new Error("Offline"));
    render(<App />);
    expect(await screen.findByText(/Prediction unavailable/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Balanced route" })).toBeInTheDocument();
  });

  it("does not submit blank coordinate components", async () => {
    render(<App />);
    await waitFor(() => expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(3));
    fireEvent.change(screen.getByRole("textbox", { name: "Origin" }), { target: { value: ",77.59" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm origin" }));
    expect(await screen.findByText("Enter coordinates as latitude, longitude")).toBeInTheDocument();
    expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(3);
    expect(apiMocks.geocodeLocation).not.toHaveBeenCalled();
  });

  it("renders the route workflow and exposes unknown and mixed provenance", async () => {
    render(<App />);

    expect(screen.getByTestId("map-view")).toHaveTextContent("Map ready");
    await waitFor(() => expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(3));
    expect(
      apiMocks.fetchRoute.mock.calls.map(([request]) => request.strategy).sort(),
    ).toEqual(["balanced", "connected", "fastest"]);
    expect(apiMocks.fetchRoute).toHaveBeenCalledWith(
      expect.objectContaining({ strategy: "fastest", vehicle: "car" }),
      expect.any(AbortSignal),
    );

    expect(
      await screen.findByText(/Signal data: Unknown signal provenance/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Most Connected/i }));

    expect(
      await screen.findByText(/Signal data: Hybrid real and estimated data/),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/50% provider-backed · 75% good estimate/).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Fastest route" }));
    expect(await screen.findByText(/Signal data: Model or fallback estimate/)).toBeInTheDocument();
    expect(
      screen.getByText("Estimated signal; measured coverage is unavailable"),
    ).toBeInTheDocument();
  });

  it("waits for Retry-After before retrying a loading route", async () => {
    vi.useFakeTimers();
    let connectedCalls = 0;
    apiMocks.fetchRoute.mockImplementation(async (request: RouteRequestPayload) => {
      if (request.strategy === "connected" && connectedCalls++ === 0) {
        return {
          status: "loading" as const,
          strategy: "connected" as const,
          message: "Graph is loading",
          retryAfter: 2,
        };
      }
      return routeFor(request.strategy, request.vehicle, "hybrid");
    });

    render(<App />);
    await flushMicrotasks();

    expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(3);
    expect(screen.getByText(/Loading Bangalore road network/)).toBeInTheDocument();
    expect(connectedCalls).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_999);
    });
    expect(connectedCalls).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    await flushMicrotasks();
    expect(connectedCalls).toBe(2);
    expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(4);
    expect(screen.getByRole("button", { name: /Most Connected/i })).toBeInTheDocument();
  });

  it("does not retry a loading route after unmount", async () => {
    vi.useFakeTimers();
    apiMocks.fetchRoute.mockImplementation(async (request: RouteRequestPayload) => ({
      status: "loading" as const,
      strategy: request.strategy,
      message: "Graph is loading",
      retryAfter: 2,
    }));

    const { unmount } = render(<App />);
    await flushMicrotasks();
    expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(3);

    act(() => unmount());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });

    expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(3);
  });
});
