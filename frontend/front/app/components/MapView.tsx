import { MapContainer, TileLayer, Polyline, Circle } from 'react-leaflet';

interface Route {
  id: number;
  color: string;
  path: string;
}

interface MapViewProps {
  routes: Route[];
  selectedRoute: number;
  showHeatmap: boolean;
}

export default function MapView({ routes, selectedRoute, showHeatmap }: MapViewProps) {

  const routePaths: Record<string, [number, number][]> = {
    highway: [
      [12.9716, 77.5946],
      [12.9760, 77.6000],
      [12.9800, 77.6100],
    ],
    mixed: [
      [12.9716, 77.5946],
      [12.9680, 77.5800],
      [12.9650, 77.5700],
    ],
    urban: [
      [12.9716, 77.5946],
      [12.9700, 77.5900],
      [12.9680, 77.5850],
    ],
  };

  return (
    <MapContainer
      center={[12.9716, 77.5946]}
      zoom={13}
      zoomControl={false}
      style={{ height: '100vh', width: '100%', zIndex: 0 }}
      preferCanvas={true}
    >
      <TileLayer
        attribution="&copy; OpenStreetMap & Carto"
        url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
      />

      {routes.map((route) => (
        <Polyline
          key={route.id}
          positions={routePaths[route.path] || []}
          pathOptions={{
            color: route.color,
            weight: route.id === selectedRoute ? 6 : 3,
            opacity: route.id === selectedRoute ? 1 : 0.5,
          }}
        />
      ))}

      {showHeatmap && (
        <>
          <Circle center={[12.9716, 77.5946]} radius={500} pathOptions={{ color: 'green', fillOpacity: 0.3 }} />
          <Circle center={[12.9680, 77.6000]} radius={400} pathOptions={{ color: 'yellow', fillOpacity: 0.3 }} />
          <Circle center={[12.9650, 77.5800]} radius={300} pathOptions={{ color: 'red', fillOpacity: 0.3 }} />
        </>
      )}
    </MapContainer>
  );
}