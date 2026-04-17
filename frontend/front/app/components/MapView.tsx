import { MapContainer, TileLayer, Polyline, Circle } from 'react-leaflet';
import { useEffect, useState, memo } from 'react';

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
}

function MapView({ routes, selectedRoute, showHeatmap, darkMode }: MapViewProps) {
  const [baseRoute, setBaseRoute] = useState<[number, number][]>([]);

  const start = { lat: 12.9716, lng: 77.5946 };
  const end = { lat: 12.9800, lng: 77.6100 };

  useEffect(() => {
    const fetchRoute = async () => {
      try {
        const res = await fetch(
          `https://router.project-osrm.org/route/v1/driving/${start.lng},${start.lat};${end.lng},${end.lat}?overview=full&geometries=geojson`
        );
        const data = await res.json();

        const coords = data.routes[0].geometry.coordinates.map(
          ([lng, lat]: [number, number]) => [lat, lng]
        );

        setBaseRoute(coords);
      } catch (err) {
        console.error("Routing error:", err);
      }
    };

    fetchRoute();
  }, []);

  return (
    <MapContainer
      center={[12.9716, 77.5946]}
      zoom={13}
      zoomControl={false}
      preferCanvas={true}
      style={{
        height: '100vh',
        width: '100%',
        zIndex: 0,
        filter: darkMode
          ? "brightness(0.85) contrast(1.1)"
          : "saturate(0.65) brightness(1.05)"
      }}
    >
      <TileLayer
        attribution="&copy; OpenStreetMap contributors"
        url={
          darkMode
            ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        }
        keepBuffer={2}
      />

      {baseRoute.length > 0 &&
        routes.map((route) => (
          <Polyline
            key={route.id}
            positions={baseRoute}
            pathOptions={{
              color: darkMode ? "#60a5fa" : route.color,
              weight: route.id === selectedRoute ? 8 : 4,
              opacity: route.id === selectedRoute ? 1 : 0.4,
            }}
          />
        ))}

      {showHeatmap && (
        <>
          <Circle
            center={[12.9716, 77.5946]}
            radius={500}
            pathOptions={{ color: 'green', fillOpacity: 0.15 }}
          />
          <Circle
            center={[12.9680, 77.6000]}
            radius={400}
            pathOptions={{ color: 'yellow', fillOpacity: 0.15 }}
          />
          <Circle
            center={[12.9650, 77.5800]}
            radius={300}
            pathOptions={{ color: 'red', fillOpacity: 0.15 }}
          />
        </>
      )}
    </MapContainer>
  );
}

export default memo(MapView);