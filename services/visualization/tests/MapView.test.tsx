import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FormattedRoute } from "../app/lib/api";

const leafletProps = vi.hoisted(() => ({
  circleMarkers: [] as Array<Record<string, unknown>>,
  polylines: [] as Array<Record<string, unknown>>,
}));

vi.mock("leaflet", () => ({
  default: {
    canvas: { tile: vi.fn() },
    vectorGrid: {
      protobuf: vi.fn(() => ({
        addTo: vi.fn(),
        off: vi.fn(),
        on: vi.fn(),
      })),
    },
  },
}));

vi.mock("leaflet.vectorgrid/dist/Leaflet.VectorGrid.bundled.js", () => ({}));

vi.mock("react-leaflet", async () => {
  const React = await import("react");
  type MockProps = Record<string, unknown> & { children?: React.ReactNode };
  const map = {
    flyTo: vi.fn(),
    getBounds: () => ({
      getSouth: () => 12.9,
      getWest: () => 77.5,
      getNorth: () => 13,
      getEast: () => 77.7,
      toBBoxString: () => "77.5,12.9,77.7,13",
    }),
    getZoom: () => 12,
    invalidateSize: vi.fn(),
    removeLayer: vi.fn(),
    setView: vi.fn(),
  };
  const Container = ({ children }: MockProps) => <div>{children}</div>;
  const Polyline = React.forwardRef<unknown, MockProps>((props, _ref) => {
    leafletProps.polylines.push(props);
    return <div data-testid="polyline" />;
  });
  const CircleMarker = ({ children, ...props }: MockProps) => {
    leafletProps.circleMarkers.push(props);
    return <div data-testid="circle-marker">{children}</div>;
  };

  return {
    CircleMarker,
    MapContainer: Container,
    Marker: Container,
    Polyline,
    Popup: Container,
    TileLayer: () => null,
    useMap: () => map,
    useMapEvents: vi.fn(),
  };
});

import MapView from "../app/components/MapView";

function route(id: number, strategy: FormattedRoute["strategy"]): FormattedRoute {
  return {
    id,
    strategy,
    vehicle: "car",
    label: strategy,
    time: "10.0 min",
    distance: "2.0 km",
    connectivity: 0.7,
    color: "#000000",
    coordinates: [
      [12.9716, 77.5946],
      [12.9948, 77.6699],
    ],
    segments: [],
    signalSegments: [],
    signalSource: "Unknown",
    provenanceSource: "unknown",
    towerCount: 0,
    routeSignalPercent: 0,
    realDataCoveragePercent: 0,
    goodSignalPercent: 0,
    signalDataLabel: "Unknown signal provenance",
    explanation: {
      summary: "Test route",
      factors: [],
      score_breakdown: { connectivity: 0, speed: 0, risk: 0 },
    },
  };
}

beforeEach(() => {
  leafletProps.circleMarkers.length = 0;
  leafletProps.polylines.length = 0;
  vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1);
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
  vi.spyOn(console, "log").mockImplementation(() => undefined);
  vi.stubGlobal("SVGPathElement", class SVGPathElementStub {});
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MapView", () => {
  it("passes hotspot latitude/longitude and unclipped selected-route geometry to Leaflet", () => {
    render(
      <MapView
        city="bangalore"
        routes={[route(0, "connected"), route(2, "fastest")]}
        selectedRoute={2}
        showHeatmap
        darkMode={false}
        hotspots={[
          {
            id: "weak-spot",
            name: "Weak spot",
            lat: 12.9345,
            lon: 77.6123,
            signal_strength: "weak",
            radius_meters: 100,
            city: "bangalore",
          },
        ]}
        placementTarget="origin"
      />,
    );

    expect(leafletProps.circleMarkers.at(-1)).toMatchObject({
      center: [12.9345, 77.6123],
      radius: 10,
    });

    const selectedPolyline = [...leafletProps.polylines]
      .reverse()
      .find((props) =>
        (props.pathOptions as Record<string, unknown>).weight === 8,
      );
    expect(selectedPolyline).toMatchObject({
      positions: [
        [12.9716, 77.5946],
        [12.9948, 77.6699],
      ],
      noClip: true,
      smoothFactor: 0,
      pathOptions: expect.objectContaining({
        color: "#3b82f6",
        weight: 8,
        opacity: 0.95,
      }),
    });
  });
});
