import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet.vectorgrid/dist/Leaflet.VectorGrid.bundled.js";
import {
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import type { Hotspot } from "../lib/supabase";

type Coordinates = [number, number];
type LocationTarget = "origin" | "destination";

interface MapViewRequest {
  center: Coordinates;
  zoom?: number;
  behavior?: "fly" | "set";
}

const DEFAULT_CENTER: Coordinates = [20.5937, 78.9629];
const MAP_VIEWPORT_OFFSET = 0;
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

    map.flyTo(viewRequest.center, zoom, { animate: true, duration: 0.8 });
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

function VectorTileOverlay({ city }: { city: string | null }) {
  const map = useMap();
  const layerRef = useRef<L.Layer | null>(null);

  useEffect(() => {
    if (!city) return undefined;

    const vectorLayer = (L as any).vectorGrid.protobuf(
      `/api/tiles/${city}/{z}/{x}/{y}.mvt`,
      {
        rendererFactory: L.canvas.tile,
        interactive: false,
        minZoom: 10,
        maxZoom: 15,
        maxNativeZoom: 15,
        vectorTileLayerStyles: {
          roads: (properties: any, zoom: number) => {
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

    vectorLayer.addTo(map);
    layerRef.current = vectorLayer;

    return () => {
      if (!layerRef.current) return;

      map.removeLayer(layerRef.current);
      layerRef.current = null;
    };
  }, [city, map]);

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
  }, [selected]);

  if (!coordinates.length) return null;

  return (
    <Polyline
      ref={routeRef}
      positions={coordinates}
      pathOptions={{
        color: ROUTE_STYLES[mode]?.color ?? "#8b5cf6",
        weight: selected ? 8 : 5,
        opacity: selected ? 0.95 : 0.72,
        lineCap: "round",
        lineJoin: "round",
      }}
    />
  );
}

export default function MapView({
  city,
  cityLabel,
  origin,
  destination,
  routes,
  selectedRoute,
  showHeatmap,
  darkMode,
  hotspots,
  activeViewSubtitle,
  placementTarget,
  viewRequest,
  onCoordinatePick,
}: {
  city: string | null;
  cityLabel?: string;
  origin?: Coordinates;
  destination?: Coordinates;
  routes: any[];
  selectedRoute: number;
  showHeatmap: boolean;
  darkMode: boolean;
  hotspots: Hotspot[];
  activeViewSubtitle?: string;
  placementTarget: LocationTarget;
  viewRequest?: MapViewRequest | null;
  onCoordinatePick?: (target: LocationTarget, coordinates: Coordinates) => void;
}) {
  const activeCenter = viewRequest?.center ?? DEFAULT_CENTER;

  return (
    <div
      className="relative h-full w-full"
      style={{ height: `calc(100vh - ${MAP_VIEWPORT_OFFSET}px)` }}
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
        <MapClickHandler
          placementTarget={placementTarget}
          onCoordinatePick={onCoordinatePick}
        />
        <TileLayer
          url={
            darkMode
              ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
              : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          }
          attribution="&copy; OpenStreetMap contributors"
          keepBuffer={2}
        />

        {city ? <VectorTileOverlay city={city} /> : null}

        {routes.map((route) => (
          <RoutePolyline
            key={route.id}
            mode={route.id === 0 ? "connected" : route.id === 1 ? "balanced" : "fastest"}
            coordinates={route.coordinates ?? []}
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
            <Marker
              key={hotspot.id}
              position={[hotspot.lat, hotspot.lon]}
              opacity={0}
            >
              <Popup>
                {hotspot.name} - {hotspot.signal_strength}
              </Popup>
            </Marker>
          ))}
      </MapContainer>
    </div>
  );
}