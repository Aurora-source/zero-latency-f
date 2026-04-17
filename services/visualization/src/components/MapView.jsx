import { useEffect, useRef } from "react";
import {
  GeoJSON,
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
  ZoomControl,
  useMap,
} from "react-leaflet";

const ROUTE_STYLES = {
  fastest: { color: "#1976D2" },
  connected: { color: "#388E3C" },
  balanced: { color: "#7B1FA2" },
};

function segmentColor(score) {
  if (score < 0.3) {
    return "#E53935";
  }
  if (score <= 0.6) {
    return "#FB8C00";
  }
  return "#43A047";
}

function MapUpdater({ center }) {
  const map = useMap();

  useEffect(() => {
    map.setView(center, 12, { animate: true });
  }, [center, map]);

  return null;
}

function RoutePolyline({ mode, route, selected }) {
  const routeRef = useRef(null);

  useEffect(() => {
    if (selected) {
      routeRef.current?.bringToFront();
    }
  }, [selected, route]);

  if (!route?.path_geojson?.coordinates?.length) {
    return null;
  }

  const positions = route.path_geojson.coordinates.map(([lon, lat]) => [lat, lon]);

  return (
    <Polyline
      ref={routeRef}
      positions={positions}
      pathOptions={{
        color: ROUTE_STYLES[mode].color,
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
  center,
  origin,
  destination,
  segments,
  routes,
  selectedMode,
}) {
  return (
    <div className="relative h-[62vh] min-h-[560px] w-full lg:h-full">
      <MapContainer
        center={center}
        zoom={12}
        scrollWheelZoom
        zoomControl={false}
        preferCanvas
        className="h-full w-full"
      >
        <ZoomControl position="topright" />
        <MapUpdater center={center} />
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          attribution="&copy; OpenStreetMap contributors &copy; CARTO"
        />

        {segments ? (
          <GeoJSON
            key={city}
            data={segments}
            style={(feature) => ({
              color: segmentColor(feature?.properties?.connectivity_score ?? 0),
              weight: 2,
              opacity: 0.7,
            })}
          />
        ) : null}

        {Object.entries(routes).map(([mode, route]) => (
          <RoutePolyline
            key={mode}
            mode={mode}
            route={route}
            selected={selectedMode === mode}
          />
        ))}

        <Marker position={origin}>
          <Popup>Origin</Popup>
        </Marker>
        <Marker position={destination}>
          <Popup>Destination</Popup>
        </Marker>
      </MapContainer>

      <div className="pointer-events-none absolute left-4 top-4 z-[1000] rounded-2xl border border-white/60 bg-slate-900/80 px-4 py-3 text-white shadow-lg backdrop-blur">
        <p className="font-mono text-[11px] uppercase tracking-[0.28em] text-slate-300">
          Active View
        </p>
        <p className="mt-1 text-lg font-semibold capitalize">{city}</p>
        <p className="mt-1 text-sm text-slate-300">
          Seeded connectivity scores with three route overlays.
        </p>
      </div>

      <div className="pointer-events-none absolute bottom-4 left-4 z-[1000] rounded-2xl border border-white/60 bg-white/90 p-4 shadow-lg backdrop-blur">
        <p className="font-mono text-[11px] uppercase tracking-[0.28em] text-slate-500">
          Signal Legend
        </p>
        <div className="mt-3 space-y-2 text-sm text-slate-700">
          <div className="flex items-center gap-3">
            <span className="h-3 w-3 rounded-full bg-[#E53935]" />
            <span>Dead Zone</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="h-3 w-3 rounded-full bg-[#FB8C00]" />
            <span>Weak Signal</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="h-3 w-3 rounded-full bg-[#43A047]" />
            <span>Good Signal</span>
          </div>
        </div>
      </div>
    </div>
  );
}
