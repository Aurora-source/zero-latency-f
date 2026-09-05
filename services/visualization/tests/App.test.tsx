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
  it("renders the route workflow and exposes unknown and mixed provenance", async () => {
    render(<App />);

    expect(screen.getByTestId("map-view")).toHaveTextContent("Map ready");
    await waitFor(() => expect(apiMocks.fetchRoute).toHaveBeenCalledTimes(3));
    expect(
      apiMocks.fetchRoute.mock.calls.map(([request]) => request.strategy).sort(),
    ).toEqual(["balanced", "connected", "fastest"]);
    expect(apiMocks.fetchRoute).toHaveBeenCalledWith(
      expect.objectContaining({ strategy: "fastest", vehicle: "car" }),
    );

    expect(
      await screen.findByText(/Signal data: Unknown signal provenance/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Most Connected/i }));

    expect(
      await screen.findByText(/Signal data: Hybrid real and estimated data/),
    ).toBeInTheDocument();
    expect(screen.getByText(/50\.0% real · 75\.0% good signal/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Fastest/i }));
    expect(await screen.findByText(/Signal data: ML estimate/)).toBeInTheDocument();
    expect(
      screen.getByText("Signal data unavailable - using ML estimate"),
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
