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

interface GraphNode {
  lat: number;
  lon: number;
}

interface GraphEdge {
  to: number;
  weight: number;
}

type Graph = Map<number, GraphEdge[]>;
type Nodes = Map<number, GraphNode>;

function haversine(a: GraphNode, b: GraphNode): number {
  const R = 6371000;
  const dLat = (b.lat - a.lat) * Math.PI / 180;
  const dLon = (b.lon - a.lon) * Math.PI / 180;
  const lat1 = a.lat * Math.PI / 180;
  const lat2 = b.lat * Math.PI / 180;
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
}

function nearestNode(nodes: Nodes, lat: number, lon: number): number {
  let best = -1;
  let bestDist = Infinity;
  for (const [id, node] of nodes) {
    const d = haversine(node, { lat, lon });
    if (d < bestDist) { bestDist = d; best = id; }
  }
  return best;
}

function dijkstra(
  graph: Graph,
  nodes: Nodes,
  startId: number,
  endId: number
): number[] {
  const dist = new Map<number, number>();
  const prev = new Map<number, number>();
  const visited = new Set<number>();

  for (const id of nodes.keys()) dist.set(id, Infinity);
  dist.set(startId, 0);

  // Min-heap via sorted array (simple for moderate graph sizes)
  const queue: [number, number][] = [[0, startId]]; // [cost, nodeId]

  while (queue.length > 0) {
    queue.sort((a, b) => a[0] - b[0]);
    const [cost, u] = queue.shift()!;

    if (visited.has(u)) continue;
    visited.add(u);

    if (u === endId) break;

    for (const edge of graph.get(u) ?? []) {
      if (visited.has(edge.to)) continue;
      const newCost = cost + edge.weight;
      if (newCost < (dist.get(edge.to) ?? Infinity)) {
        dist.set(edge.to, newCost);
        prev.set(edge.to, u);
        queue.push([newCost, edge.to]);
      }
    }
  }

  // Reconstruct path
  const path: number[] = [];
  let cur: number | undefined = endId;
  while (cur !== undefined) {
    path.unshift(cur);
    cur = prev.get(cur);
  }

  return path[0] === startId ? path : [];
}

async function fetchRoadGraph(
  lat1: number, lon1: number,
  lat2: number, lon2: number
): Promise<{ graph: Graph; nodes: Nodes }> {
  const minLat = Math.min(lat1, lat2) - 0.02;
  const maxLat = Math.max(lat1, lat2) + 0.02;
  const minLon = Math.min(lon1, lon2) - 0.02;
  const maxLon = Math.max(lon1, lon2) + 0.02;

  const query = `
    [out:json][timeout:30];
    (
      way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link)$"]
        (${minLat},${minLon},${maxLat},${maxLon});
    );
    out body;
    >;
    out skel qt;
  `;

  const res = await fetch('https://overpass-api.de/api/interpreter', {
    method: 'POST',
    body: query,
  });

  const data = await res.json();

  const nodes: Nodes = new Map();
  const graph: Graph = new Map();

  for (const el of data.elements) {
    if (el.type === 'node') {
      nodes.set(el.id, { lat: el.lat, lon: el.lon });
    }
  }

  for (const el of data.elements) {
    if (el.type === 'way' && el.nodes?.length >= 2) {
      const nodeIds: number[] = el.nodes;
      const oneWay = el.tags?.oneway === 'yes' || el.tags?.highway === 'motorway';

      for (let i = 0; i < nodeIds.length - 1; i++) {
        const a = nodeIds[i];
        const b = nodeIds[i + 1];
        const na = nodes.get(a);
        const nb = nodes.get(b);
        if (!na || !nb) continue;

        const w = haversine(na, nb);

        if (!graph.has(a)) graph.set(a, []);
        graph.get(a)!.push({ to: b, weight: w });

        if (!oneWay) {
          if (!graph.has(b)) graph.set(b, []);
          graph.get(b)!.push({ to: a, weight: w });
        }
      }
    }
  }

  return { graph, nodes };
}

function FitBounds({ coords }: { coords: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (coords.length < 2) return;
    map.fitBounds(L.latLngBounds(coords), { padding: [60, 60] });
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
  const [loading, setLoading] = useState(false);
  const [heading, setHeading] = useState(0);
  const lastPos = useRef<[number, number] | null>(null);

  useEffect(() => {
    if (!userLocation) return;
    if (lastPos.current) {
      const [prevLat, prevLon] = lastPos.current;
      const [lat, lon] = userLocation;
      setHeading((Math.atan2(lon - prevLon, lat - prevLat) * 180) / Math.PI);
    }
    lastPos.current = userLocation;
  }, [userLocation]);

  useEffect(() => {
    if (!userLocation || !destinationCoords) {
      setRouteCoords([]);
      return;
    }

    const run = async () => {
      setLoading(true);
      try {
        const [uLat, uLon] = userLocation;
        const [dLat, dLon] = destinationCoords;

        const { graph, nodes } = await fetchRoadGraph(uLat, uLon, dLat, dLon);

        const startId = nearestNode(nodes, uLat, uLon);
        const endId = nearestNode(nodes, dLat, dLon);

        if (startId === -1 || endId === -1) {
          setLoading(false);
          return;
        }

        const pathIds = dijkstra(graph, nodes, startId, endId);

        if (pathIds.length === 0) {
          setLoading(false);
          return;
        }

        const coords: [number, number][] = pathIds
          .map(id => nodes.get(id))
          .filter(Boolean)
          .map(n => [n!.lat, n!.lon]);

        setRouteCoords(coords);
      } catch (err) {
        console.error('Dijkstra route failed:', err);
      } finally {
        setLoading(false);
      }
    };

    run();
  }, [userLocation, destinationCoords]);

  const selectedColor = routes.find(r => r.id === selectedRoute)?.color ?? '#8b5cf6';

  const carIcon = L.divIcon({
    className: '',
    html: `
      <div style="transform: translate(-50%, -50%) rotate(${heading}deg); transition: transform 0.2s linear;">
        <img src="https://cdn-icons-png.flaticon.com/512/744/744465.png"
          style="width: 32px; height: 32px; filter: drop-shadow(0 0 4px rgba(0,0,0,0.6));" />
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

  const loadingIcon = L.divIcon({
    className: '',
    html: `
      <div style="
        background: rgba(0,0,0,0.7);
        color: white;
        padding: 6px 12px;
        border-radius: 8px;
        font-size: 12px;
        white-space: nowrap;
        transform: translate(-50%, -50%);
      ">
        Calculating route...
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
          <Polyline
            positions={routeCoords}
            pathOptions={{ color: '#000000', weight: 10, opacity: 0.15 }}
          />
          <Polyline
            positions={routeCoords}
            pathOptions={{ color: selectedColor, weight: 6, opacity: 0.95, lineCap: 'round', lineJoin: 'round' }}
          />
          <Polyline
            positions={routeCoords}
            pathOptions={{ color: '#ffffff', weight: 2, opacity: 0.4, lineCap: 'round', lineJoin: 'round' }}
          />
        </>
      )}

      {userLocation && <Marker position={userLocation} icon={carIcon} />}

      {loading && userLocation && (
        <Marker position={userLocation} icon={loadingIcon} />
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