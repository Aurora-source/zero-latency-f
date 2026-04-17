import { MapContainer, TileLayer, Polyline, Circle, Marker, useMap } from 'react-leaflet';
import { useEffect, useState, memo, useRef } from 'react';
import L from 'leaflet';

interface Route {
  id: number;
  color: string;
  path: string;
}

interface MapViewProps {
  routes: Route[];
  selectedRoute: number;
  showHeatmap: boolean;
  darkMode: boolean;
  userLocation: [number, number] | null;
  destinationCoords?: [number, number] | null;
}

function FitBounds({ coords }: { coords: [number, number][] }) {
  const map = useMap();

  useEffect(() => {
    if (coords.length < 2) return;
    const bounds = L.latLngBounds(coords);
    map.fitBounds(bounds, { padding: [60, 60] });
  }, [coords, map]);

  return null;
}

function RecenterOnUser({ userLocation }: { userLocation: [number, number] | null }) {
  const map = useMap();
  const hasCentered = useRef(false);

  useEffect(() => {
    if (!userLocation || hasCentered.current) return;
    map.setView(userLocation, 15);
    hasCentered.current = true;
  }, [userLocation, map]);

  return null;
}

function MapView({
  routes,
  selectedRoute,
  showHeatmap,
  darkMode,
  userLocation,
  destinationCoords
}: MapViewProps) {

  const [routeCoords, setRouteCoords] = useState<[number, number][]>([]);
  const [heading, setHeading] = useState(0);
  const lastPos = useRef<[number, number] | null>(null);

  useEffect(() => {
    if (!userLocation) return;
    if (lastPos.current) {
      const [prevLat, prevLon] = lastPos.current;
      const [lat, lon] = userLocation;
      const angle = (Math.atan2(lon - prevLon, lat - prevLat) * 180) / Math.PI;
      setHeading(angle);
    }
    lastPos.current = userLocation;
  }, [userLocation]);

  useEffect(() => {
    if (!userLocation || !destinationCoords) {
      setRouteCoords([]);
      return;
    }

    const fetchRoute = async () => {
      try {
        const [uLat, uLon] = userLocation;
        const [dLat, dLon] = destinationCoords;

        const url = `https://router.project-osrm.org/route/v1/driving/${uLon},${uLat};${dLon},${dLat}?overview=full&geometries=geojson`;
        const res = await fetch(url);

        if (!res.ok) return;
        const data = await res.json();

        if (!data?.routes?.[0]?.geometry?.coordinates) return;

        const coords: [number, number][] = data.routes[0].geometry.coordinates.map(
          ([lng, lat]: [number, number]) => [lat, lng]
        );

        setRouteCoords(coords);
      } catch (err) {
        console.error('Route fetch failed:', err);
      }
    };

    fetchRoute();
  }, [userLocation, destinationCoords]);

  const selectedColor = routes.find(r => r.id === selectedRoute)?.color ?? '#8b5cf6';

  const carIcon = L.divIcon({
    className: '',
    html: `
      <div style="
        transform: translate(-50%, -50%) rotate(${heading}deg);
        transition: transform 0.2s linear;
      ">
        <img
          src="https://cdn-icons-png.flaticon.com/512/744/744465.png"
          style="width: 32px; height: 32px; filter: drop-shadow(0 0 4px rgba(0,0,0,0.6));"
        />
      </div>
    `,
  });

  const destinationIcon = L.divIcon({
    className: '',
    html: `
      <div style="transform: translate(-50%, -100%);">
        <svg width="32" height="40" viewBox="0 0 32 40" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M16 0C7.163 0 0 7.163 0 16c0 10 16 24 16 24S32 26 32 16C32 7.163 24.837 0 16 0z" fill="#ef4444"/>
          <circle cx="16" cy="16" r="7" fill="white"/>
        </svg>
      </div>
    `,
  });

  return (
    <MapContainer
      center={userLocation || [12.9716, 77.5946]}
      zoom={15}
      zoomControl={false}
      preferCanvas={true}
      style={{
        height: '100vh',
        width: '100%',
        zIndex: 0,
        filter: darkMode
          ? 'brightness(0.85) contrast(1.1)'
          : 'saturate(0.65) brightness(1.05)'
      }}
    >
      <TileLayer
        attribution="&copy; OpenStreetMap contributors"
        url={
          darkMode
            ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
            : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
        }
        keepBuffer={2}
      />

      <RecenterOnUser userLocation={userLocation} />

      {routeCoords.length > 0 && (
        <>
          <FitBounds coords={routeCoords} />

          {/* Route shadow for depth */}
          <Polyline
            positions={routeCoords}
            pathOptions={{
              color: '#000000',
              weight: 10,
              opacity: 0.15,
            }}
          />

          {/* Main route line */}
          <Polyline
            positions={routeCoords}
            pathOptions={{
              color: selectedColor,
              weight: 6,
              opacity: 0.95,
              lineCap: 'round',
              lineJoin: 'round',
            }}
          />

          {/* Route highlight (inner bright line) */}
          <Polyline
            positions={routeCoords}
            pathOptions={{
              color: '#ffffff',
              weight: 2,
              opacity: 0.4,
              lineCap: 'round',
              lineJoin: 'round',
            }}
          />
        </>
      )}

      {userLocation && (
        <Marker position={userLocation} icon={carIcon} />
      )}

      {destinationCoords && (
        <Marker position={destinationCoords} icon={destinationIcon} />
      )}

      {showHeatmap && (
        <>
          <Circle center={[12.9716, 77.5946]} radius={500} pathOptions={{ color: 'green', fillOpacity: 0.15 }} />
          <Circle center={[12.9680, 77.6000]} radius={400} pathOptions={{ color: 'yellow', fillOpacity: 0.15 }} />
          <Circle center={[12.9650, 77.5800]} radius={300} pathOptions={{ color: 'red', fillOpacity: 0.15 }} />
        </>
      )}
    </MapContainer>
  );
}

export default memo(MapView);