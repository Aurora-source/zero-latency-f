import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchRoute,
  geocodeLocation,
  formatRouteForUI,
  isRouteLoadingResponse,
  type RouteRequestPayload,
} from "../app/lib/api";

const payload: RouteRequestPayload = {
  city: "bangalore",
  origin: [12.9716, 77.5946],
  destination: [12.9948, 77.6699],
  strategy: "connected",
  vehicle: "scooter",
};

function jsonResponse(body: unknown, init: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("allows the geocoder timeout response to preserve its map fallback message", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockImplementation((_url, init) => new Promise((resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    window.setTimeout(() => resolve(jsonResponse({ detail: "Place search unavailable. Enter latitude, longitude or pick the map." }, { status: 503 })), 10_250);
  })));
  const response = expect(geocodeLocation("MG Road Bengaluru")).rejects.toThrow("pick the map");
  await vi.advanceTimersByTimeAsync(10_250);
  await response;
});

describe("fetchRoute", () => {
  it.each([
    {},
    { path_geojson: { type: "LineString", coordinates: [] }, total_time_min: 0, avg_connectivity: 0 },
    { path_geojson: { type: "LineString", coordinates: [[77.59, 91], [77.6, 12.98]] }, total_time_min: 1, avg_connectivity: 0.5 },
    { path_geojson: { type: "LineString", coordinates: [[77.59, 12.97], [77.6, 12.98]] }, total_time_min: null, avg_connectivity: 0.5 },
  ])("rejects malformed success payloads", async (body) => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(body, { status: 200 })));
    await expect(fetchRoute(payload)).rejects.toThrow("invalid route");
  });

  it("bounds a hung route request and aborts the transport", async () => {
    vi.useFakeTimers();
    let aborted = false;
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => { aborted = true; reject(new DOMException("Aborted", "AbortError")); });
    })));
    const response = expect(fetchRoute(payload)).rejects.toThrow("timed out");
    await vi.advanceTimersByTimeAsync(90_000);
    await response;
    expect(aborted).toBe(true);
  });

  it("does not expose a proxy HTML error", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(new Response("<html>internal proxy traceback</html>", { status: 502 })));
    await expect(fetchRoute(payload)).rejects.toThrow("Route request failed");
  });

  it("honors Retry-After delta seconds for a 202 loading response", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        {
          status: "loading",
          message: "Graph is loading",
          retry_after: 30,
        },
        {
          status: 202,
          headers: { "Retry-After": "4" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchRoute(payload);

    expect(isRouteLoadingResponse(result)).toBe(true);
    expect(result).toEqual({
      status: "loading",
      strategy: "connected",
      message: "Graph is loading",
      retryAfter: 4,
    });
  });

  it("accepts an HTTP-date Retry-After for the legacy loading response", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-04T12:00:00Z"));
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        {
          status: "loading",
          code: "graph_loading",
          message: "Graph is still loading",
        },
        {
          status: 503,
          headers: {
            "Retry-After": new Date("2026-09-04T12:00:05Z").toUTCString(),
          },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchRoute(payload);

    expect(isRouteLoadingResponse(result)).toBe(true);
    expect(result).toMatchObject({ retryAfter: 5, strategy: "connected" });
  });

  it.each([
    { header: "0", body: 30, expected: 1 },
    { header: "Fri, 04 Sep 2026 11:59:59 GMT", body: 30, expected: 1 },
    { header: "invalid", body: 2.2, expected: 3 },
    { header: "-1", body: 4, expected: 4 },
    { header: undefined, body: -1, expected: 10 },
    { header: undefined, body: undefined, expected: 10 },
  ])("uses a safe delay for header=$header and body=$body", async ({ header, body, expected }) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-04T12:00:00Z"));
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        { status: "loading", retry_after: body },
        { status: 202, headers: header === undefined ? {} : { "Retry-After": header } },
      ),
    ));

    await expect(fetchRoute(payload)).resolves.toMatchObject({
      status: "loading",
      retryAfter: expected,
    });
  });

  it.each(["fastest", "balanced", "connected"] as const)(
    "sends mode=%s and preserves a mixed-provenance response",
    async (strategy) => {
      const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse(
          {
            mode: strategy,
            vehicle: "scooter",
            path_geojson: {
              type: "LineString",
              coordinates: [
                [77.5946, 12.9716],
                [77.6699, 12.9948],
              ],
            },
            segments: [],
            signal_segments: [
              {
                segment_id: "real-edge",
                coordinates: [
                  [12.9716, 77.5946],
                  [12.98, 77.62],
                ],
                score: 0.85,
                risk: "low",
                provenance_source: "opencellid",
              },
              {
                segment_id: "estimated-edge",
                coordinates: [
                  [12.98, 77.62],
                  [12.9948, 77.6699],
                ],
                score: 0.45,
                risk: "medium",
                provenance_source: "ml_synthetic",
              },
            ],
            total_time_min: 17.25,
            avg_connectivity: 0.65,
            route_signal_percent: 65,
            signal_source: "hybrid",
            tower_count: 8,
            real_data_coverage_percent: 50,
            good_signal_percent: 75,
          },
          { status: 200 },
        ),
      );
      vi.stubGlobal("fetch", fetchMock);

      const result = await fetchRoute({ ...payload, strategy });

      expect(isRouteLoadingResponse(result)).toBe(false);
      if (isRouteLoadingResponse(result)) throw new Error("Expected a completed route");

      const [, request] = fetchMock.mock.calls[0];
      expect(JSON.parse(String(request?.body))).toEqual({
        city: "bangalore",
        origin: payload.origin,
        destination: payload.destination,
        mode: strategy,
        vehicle: "scooter",
      });
      expect(result).toMatchObject({
        strategy,
        vehicle: "scooter",
        coordinates: [
          [12.9716, 77.5946],
          [12.9948, 77.6699],
        ],
        provenanceSource: "hybrid",
        signalSource: "Hybrid",
        realDataCoveragePercent: 50,
        goodSignalPercent: 75,
      });
      expect(result.signalSegments.map((segment) => segment.provenanceSource)).toEqual([
        "opencellid",
        "ml_synthetic",
      ]);
      expect(formatRouteForUI(result, "#10b981").signalDataLabel).toBe(
        "Hybrid real and estimated data (8 towers in corridor)",
      );
    },
  );

  it.each(["bike", "scooter", "car", "truck"] as const)(
    "keeps vehicle=%s distinct in the request and response",
    async (vehicle) => {
      const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse({ vehicle, total_time_min: 10, avg_connectivity: 0.5, path_geojson: { type: "LineString", coordinates: [[77.59, 12.97], [77.60, 12.98]] } }, { status: 200 }),
      );
      vi.stubGlobal("fetch", fetchMock);

      await expect(fetchRoute({ ...payload, vehicle })).resolves.toMatchObject({ vehicle });
      const [, request] = fetchMock.mock.calls[0];
      expect(JSON.parse(String(request?.body))).toMatchObject({ vehicle });
    },
  );

  it("keeps unrecognized provenance visibly unknown", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        {
          path_geojson: { type: "LineString", coordinates: [[77.59, 12.97], [77.60, 12.98]] },
          signal_source: "unrecognized-provider",
          total_time_min: 0,
          avg_connectivity: 0,
          tower_count: 0,
          real_data_coverage_percent: 0,
          good_signal_percent: 0,
        },
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchRoute(payload);

    if (isRouteLoadingResponse(result)) throw new Error("Expected a completed route");
    const formatted = formatRouteForUI(result, "#10b981");
    expect(formatted.provenanceSource).toBe("unknown");
    expect(formatted.signalDataLabel).toBe("Unknown signal provenance");
    expect(formatted.warning).toBe("Signal data provenance is unavailable");
  });

  it("does not retry an unrelated 503 service failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        jsonResponse(
          {
            status: "error",
            code: "dependency_unavailable",
            message: "Prediction dependency unavailable",
          },
          { status: 503 },
        ),
      ),
    );

    await expect(fetchRoute(payload)).rejects.toThrow("Prediction dependency unavailable");
  });
});
