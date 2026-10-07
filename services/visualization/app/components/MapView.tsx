import { memo, useEffect, useRef, useState } from "react";
import L from "leaflet";
import type {} from "leaflet.vectorgrid";
import "leaflet.vectorgrid/dist/Leaflet.VectorGrid.bundled.js";
import {
  CircleMarker,
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import type { FormattedRoute, ViewportBounds } from "../lib/api";
import type { Hotspot } from "../lib/supabase";

type Coordinates = [number, number];
type LocationTarget = "origin" | "destination";

interface MapViewRequest {
  center: Coordinates;
  zoom?: number;
  behavior?: "fly" | "set";
}

const DEFAULT_CENTER: Coordinates = [20.5937, 78.9629];
const ROUTE_STYLES: Record<string, { color: string }> = {
  fastest: { color: "#3b82f6" },
  balanced: { color: "#8b5cf6" },
  connected: { color: "#10b981" },
};

function MapUpdater({ viewRequest }: { viewRequest?: MapViewRequest | null }) {
  const map = useMap();

  useEffect(() => {
    if (!viewRequest) return;

    const zoom = viewRequest.zoom ?? map.getZoom();
    if (viewRequest.behavior === "set") {
      map.setView(viewRequest.center, zoom, { animate: true });
      return;
    }

    map.flyTo(viewRequest.center, zoom, {
      animate: true,
      duration: 1.5,
      easeLinearity: 0.25,
    });
  }, [viewRequest, map]);

  return null;
}

function MapResizer() {
  const map = useMap();

  useEffect(() => {
    const invalidate = () => map.invalidateSize();
    const frameId = window.requestAnimationFrame(invalidate);

    window.addEventListener("resize", invalidate);
    return () => {
      window.cancelAnimationFrame(frameId);
      window.removeEventListener("resize", invalidate);
    };
  }, [map]);

  return null;
}

function MapClickHandler({
  placementTarget,
  onCoordinatePick,
}: {
  placementTarget: LocationTarget;
  onCoordinatePick?: (target: LocationTarget, coordinates: Coordinates) => void;
}) {
  useMapEvents({
    click(event) {
      onCoordinatePick?.(placementTarget, [event.latlng.lat, event.latlng.lng]);
    },
  });

  return null;
}

function emitViewport(
  map: L.Map,
  onViewportChange?: (viewport: ViewportBounds) => void,
) {
  const bounds = map.getBounds();
  const viewport = {
    minLat: bounds.getSouth(),
    minLon: bounds.getWest(),
    maxLat: bounds.getNorth(),
    maxLon: bounds.getEast(),
    zoom: map.getZoom(),
  };
  console.log("[map] viewport:", bounds.toBBoxString());
  onViewportChange?.(viewport);
}

function MapViewportLogger({
  onViewportChange,
}: {
  onViewportChange?: (viewport: ViewportBounds) => void;
}) {
  const map = useMap();
  const timeoutRef = useRef<number | null>(null);

  useMapEvents({
    moveend(event) {
      if (timeoutRef.current !== null) {
        window.clearTimeout(timeoutRef.current);
      }
      timeoutRef.current = window.setTimeout(() => {
        emitViewport(event.target, onViewportChange);
      }, 100);
    },
  });

  useEffect(() => {
    emitViewport(map, onViewportChange);
    return () => {
      if (timeoutRef.current !== null) {
        window.clearTimeout(timeoutRef.current);
      }
    };
  }, [map, onViewportChange]);

  return null;
}

function VectorTileOverlay({
  city,
  enabled,
  onLoadingChange,
  onError,
}: {
  city: string | null;
  enabled: boolean;
  onLoadingChange?: (loading: boolean) => void;
  onError?: (message: string | null) => void;
}) {
  const map = useMap();
  const layerRef = useRef<L.Layer | null>(null);

  useEffect(() => {
    if (!city || !enabled) {
      onLoadingChange?.(false);
      onError?.(null);
      return undefined;
    }

    const vectorLayer = L.vectorGrid.protobuf(
      `/api/tiles/${city}/{z}/{x}/{y}.mvt`,
      {
        rendererFactory: L.canvas.tile,
        interactive: false,
        minZoom: 10,
        maxZoom: 16,
        maxNativeZoom: 16,
        vectorTileLayerStyles: {
          roads: (properties: { connectivity_score?: number; road_type?: string }, zoom: number) => {
            const score = Number(properties?.connectivity_score ?? 0.5);

            return {
              color: connectivityColor(score),
              weight: roadWeight(properties?.road_type ?? "unknown", zoom),
              opacity: 0.7,
              fill: false,
              stroke: true,
              lineCap: "round",
              lineJoin: "round",
            };
          },
        },
      },
    );

    onLoadingChange?.(true);
    onError?.(null);
    const stopLoading = () => onLoadingChange?.(false);
    const tileError = () => { stopLoading(); onError?.("Signal overlay unavailable. Check the data service and toggle heatmap to retry."); };
    const fallbackId = window.setTimeout(stopLoading, 1200);
    vectorLayer.on?.("load", stopLoading);
    vectorLayer.on?.("tileerror", tileError);
    vectorLayer.addTo(map);
    layerRef.current = vectorLayer;

    return () => {
      window.clearTimeout(fallbackId);
      vectorLayer.off?.("load", stopLoading);
      vectorLayer.off?.("tileerror", tileError);
      if (!layerRef.current) return;

      map.removeLayer(layerRef.current);
      layerRef.current = null;
      onLoadingChange?.(false);
    };
  }, [city, enabled, map, onLoadingChange, onError]);

  return null;
}

function roadWeight(roadType: string, zoom: number) {
  const zoomFactor = Math.max(0, zoom - 10) * 0.15;

  if (roadType === "motorway" || roadType === "trunk") {
    return 2.4 + zoomFactor;
  }
  if (roadType === "primary" || roadType === "secondary") {
    return 1.9 + zoomFactor;
  }
  return 1.3 + zoomFactor * 0.8;
}

function connectivityColor(score: number) {
  if (score > 0.7) return "#22c55e";
  if (score > 0.4) return "#f59e0b";
  return "#ef4444";
}

function RoutePolyline({
  mode,
  coordinates,
  selected,
}: {
  mode: string;
  coordinates: Coordinates[];
  selected: boolean;
}) {
  const routeRef = useRef<L.Polyline | null>(null);

  useEffect(() => {
    if (selected) {
      routeRef.current?.bringToFront();
    }
    const element = routeRef.current?.getElement?.();
    if (element instanceof SVGPathElement) {
      const pathLength = element.getTotalLength();
      element.style.setProperty("--route-length", `${pathLength}`);
      element.style.setProperty("--route-delay", "0ms");
    }
  }, [coordinates, selected]);

  if (!coordinates.length) return null;

  return (
    <Polyline
      ref={routeRef}
      positions={coordinates}
      noClip
      smoothFactor={0}
      pathOptions={{
        color: ROUTE_STYLES[mode]?.color ?? "#8b5cf6",
        weight: selected ? 8 : 5,
        opacity: selected ? 0.95 : 0.72,
        lineCap: "round",
        lineJoin: "round",
        className: `route-line ${selected ? "route-line-selected" : "route-line-idle"}`,
      }}
    />
  );
}

function RouteSignalSegment({
  routeId,
  segmentId,
  coordinates,
  score,
  delayMs,
}: {
  routeId: number;
  segmentId?: string;
  coordinates: Coordinates[];
  score: number;
  delayMs: number;
}) {
  const segmentRef = useRef<L.Polyline | null>(null);

  useEffect(() => {
    const element = segmentRef.current?.getElement?.();
    if (element instanceof SVGPathElement) {
      const pathLength = element.getTotalLength();
      element.style.setProperty("--route-length", `${pathLength}`);
      element.style.setProperty("--route-delay", `${delayMs}ms`);
    }
  }, [delayMs, coordinates]);

  return (
    <Polyline
      ref={segmentRef}
      key={`${routeId}-${segmentId ?? delayMs}`}
      positions={coordinates}
      noClip
      smoothFactor={0}
      pathOptions={{
        color: connectivityColor(score),
        weight: 7,
        opacity: 0.96,
        lineCap: "round",
        lineJoin: "round",
        className: "route-line route-line-signal",
      }}
    />
  );
}

function RouteSignalOverlay({
  route,
  selected,
}: {
  route: FormattedRoute;
  selected: boolean;
}) {
  if (!selected || !route.signalSegments.length) {
    return null;
  }

  return (
    <>
      {route.signalSegments.map((segment, index) => (
        <RouteSignalSegment
          key={`${route.id}-${segment.segment_id ?? index}`}
          routeId={route.id}
          segmentId={segment.segment_id}
          coordinates={segment.coordinates}
          score={segment.score}
          delayMs={index * 10}
        />
      ))}
    </>
  );
}

function MapViewComponent({
  city,
  origin,
  destination,
  routes,
  selectedRoute,
  showHeatmap,
  darkMode,
  hotspots,
  placementTarget,
  viewRequest,
  onCoordinatePick,
  onViewportChange,
}: {
  city: string | null;
  origin?: Coordinates;
  destination?: Coordinates;
  routes: FormattedRoute[];
  selectedRoute: number;
  showHeatmap: boolean;
  darkMode: boolean;
  hotspots: Hotspot[];
  placementTarget: LocationTarget;
  viewRequest?: MapViewRequest | null;
  onCoordinatePick?: (target: LocationTarget, coordinates: Coordinates) => void;
  onViewportChange?: (viewport: ViewportBounds) => void;
}) {
  const activeCenter = viewRequest?.center ?? DEFAULT_CENTER;
  const [heatmapLoading, setHeatmapLoading] = useState(false);
  const [heatmapError, setHeatmapError] = useState<string | null>(null);

  return (
    <div
      className="relative h-full w-full"
    >
      <MapContainer
        center={activeCenter}
        zoom={city ? 12 : 5}
        scrollWheelZoom
        zoomControl={false}
        preferCanvas
        className="h-full w-full"
        style={{
          filter: darkMode
            ? "brightness(0.85) contrast(1.1)"
            : "saturate(0.65) brightness(1.05)",
        }}
      >
        <MapResizer />
        <MapUpdater viewRequest={viewRequest} />
        <MapViewportLogger onViewportChange={onViewportChange} />
        <MapClickHandler
          placementTarget={placementTarget}
          onCoordinatePick={onCoordinatePick}
        />
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          keepBuffer={2}
        />

        {city ? (
          <VectorTileOverlay
            city={city}
            enabled={showHeatmap}
            onLoadingChange={setHeatmapLoading}
            onError={setHeatmapError}
          />
        ) : null}

        {routes.map((route) => (
          <RoutePolyline
            key={route.id}
            mode={route.id === 0 ? "connected" : route.id === 1 ? "balanced" : "fastest"}
            coordinates={route.coordinates ?? []}
            selected={selectedRoute === route.id}
          />
        ))}

        {routes.map((route) => (
          <RouteSignalOverlay
            key={`signal-${route.id}`}
            route={route}
            selected={selectedRoute === route.id}
          />
        ))}

        {origin ? (
          <Marker position={origin}>
            <Popup>Origin</Popup>
          </Marker>
        ) : null}

        {destination ? (
          <Marker position={destination}>
            <Popup>Destination</Popup>
          </Marker>
        ) : null}

        {showHeatmap &&
          hotspots.map((hotspot) => (
            <CircleMarker
              key={hotspot.id}
              center={[hotspot.lat, hotspot.lon]}
              radius={hotspot.signal_strength === "weak" ? 10 : 7}
              pathOptions={{
                color:
                  hotspot.signal_strength === "weak"
                    ? "#ef4444"
                    : hotspot.signal_strength === "medium"
                      ? "#f59e0b"
                      : "#22c55e",
                fillColor:
                  hotspot.signal_strength === "weak"
                    ? "#ef4444"
                    : hotspot.signal_strength === "medium"
                      ? "#f59e0b"
                      : "#22c55e",
                fillOpacity: 0.3,
                opacity: 0.9,
                weight: 2,
              }}
            >
              <Popup>
                {hotspot.name} - {hotspot.signal_strength}
              </Popup>
            </CircleMarker>
          ))}
      </MapContainer>

      {showHeatmap && heatmapLoading ? (
        <div className="pointer-events-none absolute bottom-28 right-4 z-[1000] rounded-full border border-white/20 bg-black/70 px-4 py-2 text-xs text-white shadow-lg backdrop-blur">
          Loading signal overlay...
        </div>
      ) : null}
      {showHeatmap && heatmapError ? <div role="status" className="pointer-events-none absolute right-4 top-72 z-[1000] max-w-xs rounded-xl bg-black/80 p-3 text-xs text-amber-200">{heatmapError}</div> : null}
    </div>
  );
}

const MapView = memo(MapViewComponent);
MapView.displayName = "MapView";

export default MapView;
