import { AlertTriangle, ArrowUpRight, Navigation, RadioTower, Route } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { DEFAULT_ROUTE_REQUEST, fetchRoute } from '../api/apiClient';

function routeDistanceKm(coordinates: [number, number][]): number {
  if (coordinates.length < 2) {
    return 0;
  }

  let totalMeters = 0;
  for (let index = 1; index < coordinates.length; index += 1) {
    const [prevLat, prevLon] = coordinates[index - 1];
    const [nextLat, nextLon] = coordinates[index];
    const dLat = (nextLat - prevLat) * 111_320;
    const meanLat = ((nextLat + prevLat) / 2) * (Math.PI / 180);
    const dLon = (nextLon - prevLon) * 111_320 * Math.cos(meanLat);
    totalMeters += Math.sqrt((dLat * dLat) + (dLon * dLon));
  }
  return totalMeters / 1000;
}

function buildRoutePath(coordinates: [number, number][]): string {
  if (coordinates.length < 2) {
    return '';
  }

  const lats = coordinates.map(([lat]) => lat);
  const lons = coordinates.map(([, lon]) => lon);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const width = 1920;
  const height = 720;
  const padding = 110;
  const spanLat = Math.max(maxLat - minLat, 0.001);
  const spanLon = Math.max(maxLon - minLon, 0.001);

  return coordinates
    .map(([lat, lon], index) => {
      const x = padding + ((lon - minLon) / spanLon) * (width - (padding * 2));
      const y = padding + ((maxLat - lat) / spanLat) * (height - (padding * 2));
      const command = index === 0 ? 'M' : 'L';
      return `${command} ${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
}

function trafficLabel(distanceKm: number, etaMinutes: number): string {
  if (distanceKm <= 0 || etaMinutes <= 0) {
    return 'Syncing';
  }
  const avgSpeed = (distanceKm / etaMinutes) * 60;
  if (avgSpeed >= 35) {
    return 'Light';
  }
  if (avgSpeed >= 22) {
    return 'Moderate';
  }
  return 'Heavy';
}

export function NavigationScreen() {
  const [coordinates, setCoordinates] = useState<[number, number][]>([]);
  const [etaMinutes, setEtaMinutes] = useState(0);
  const [coveragePercent, setCoveragePercent] = useState(0);
  const [signalSource, setSignalSource] = useState('Connecting');
  const [summary, setSummary] = useState('Loading live route');
  const [towerCount, setTowerCount] = useState(0);
  const [connectionLost, setConnectionLost] = useState(false);

  useEffect(() => {
    let disposed = false;

    const loadRoute = async () => {
      try {
        const data = await fetchRoute(DEFAULT_ROUTE_REQUEST);
        if (disposed) {
          return;
        }
        console.log('Response:', data);
        setCoordinates(data.coordinates ?? []);
        setEtaMinutes(Number(data.total_time_min ?? 0));
        setCoveragePercent(Math.max(0, Math.min(100, Math.round(data.coverage_percent ?? 0))));
        setSignalSource(data.signal_source ?? 'Live backend');
        setSummary(data.explanation?.summary ?? 'Balanced route ready');
        setTowerCount(Number(data.tower_count ?? 0));
        setConnectionLost(false);
      } catch (error) {
        if (disposed) {
          return;
        }
        console.error('Route API error:', error);
        setConnectionLost(true);
        setSummary('Connection Lost');
      }
    };

    loadRoute().catch((error) => {
      console.error('Route API error:', error);
      setConnectionLost(true);
      setSummary('Connection Lost');
    });
    const interval = setInterval(() => {
      loadRoute().catch((error) => {
        console.error('Route API error:', error);
        setConnectionLost(true);
        setSummary('Connection Lost');
      });
    }, 10000);

    return () => {
      disposed = true;
      clearInterval(interval);
    };
  }, []);

  const distanceKm = useMemo(() => routeDistanceKm(coordinates), [coordinates]);
  const pathData = useMemo(() => buildRoutePath(coordinates), [coordinates]);
  const traffic = useMemo(() => trafficLabel(distanceKm, etaMinutes), [distanceKm, etaMinutes]);
  const etaClock = useMemo(() => {
    if (etaMinutes <= 0) {
      return '--:--';
    }
    const arrival = new Date(Date.now() + (etaMinutes * 60_000));
    return arrival.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  }, [etaMinutes]);

  return (
    <div className="h-full pb-20 relative bg-[#0a0a0a]">
      <div className="absolute inset-0 bg-gradient-to-b from-[#1a1a1a] to-[#0a0a0a]">
        <div className="absolute inset-0 opacity-40">
          <svg className="w-full h-full" viewBox="0 0 1920 720" preserveAspectRatio="none">
            <path
              d={pathData}
              stroke={connectionLost ? '#ef4444' : '#3b82f6'}
              strokeWidth="8"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>

        <div className="absolute inset-0 opacity-5">
          <div className="grid grid-cols-24 grid-rows-12 h-full w-full">
            {Array.from({ length: 288 }).map((_, i) => (
              <div key={i} className="border border-gray-700" />
            ))}
          </div>
        </div>

        <div className="absolute bottom-1/3 left-1/4">
          <div className={`w-3 h-3 rounded-full ${connectionLost ? 'bg-red-500' : 'bg-blue-500'}`} />
        </div>
      </div>

      <div className="absolute top-8 left-8 bg-[#1a1a1a]/95 backdrop-blur-xl rounded-2xl p-6 border border-[#2a2a2a] max-w-md">
        <div className="flex items-center gap-6">
          <div className="w-20 h-20 bg-[#2a2a2a] rounded-xl flex items-center justify-center">
            {connectionLost ? (
              <AlertTriangle className="w-10 h-10 text-red-400" strokeWidth={2} />
            ) : (
              <ArrowUpRight className="w-10 h-10 text-white" strokeWidth={2} />
            )}
          </div>
          <div>
            <div className="text-xs text-gray-500 uppercase mb-1">
              {connectionLost ? 'Backend offline' : `${coveragePercent}% corridor coverage`}
            </div>
            <div className="text-2xl text-white mb-1">
              {connectionLost ? 'Connection Lost' : 'Live route active'}
            </div>
            <div className="text-sm text-gray-400">{summary}</div>
          </div>
        </div>
      </div>

      <div className="absolute top-8 right-8 bg-[#1a1a1a]/95 backdrop-blur-xl rounded-2xl px-5 py-4 border border-[#2a2a2a]">
        <div className="flex items-center gap-3">
          <RadioTower className={`w-5 h-5 ${coveragePercent > 0 ? 'text-green-400' : 'text-yellow-400'}`} />
          <div>
            <div className="text-xs text-gray-500 uppercase">Signal Source</div>
            <div className="text-sm text-white">{signalSource}</div>
          </div>
        </div>
      </div>

      <div className="absolute bottom-24 right-8 bg-[#1a1a1a]/95 backdrop-blur-xl rounded-2xl p-6 border border-[#2a2a2a] min-w-[320px]">
        <div className="flex items-center gap-3 mb-4">
          <Navigation className="w-5 h-5 text-blue-500" />
          <div className="text-lg text-white">Bangalore Corridor</div>
        </div>
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-gray-400">ETA</span>
            <span className="text-xl text-white">{etaClock}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Distance</span>
            <span className="text-xl text-white">{distanceKm.toFixed(1)} km</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Traffic</span>
            <span className={`text-xl ${traffic === 'Light' ? 'text-green-500' : traffic === 'Moderate' ? 'text-yellow-400' : 'text-red-400'}`}>
              {traffic}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Towers</span>
            <span className="text-xl text-white">{towerCount}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Coverage</span>
            <span className="text-xl text-white">{coveragePercent}%</span>
          </div>
        </div>
      </div>

      <div className="absolute bottom-24 left-8 bg-[#1a1a1a]/90 backdrop-blur-xl rounded-2xl px-5 py-4 border border-[#2a2a2a]">
        <div className="flex items-center gap-3">
          <Route className="w-5 h-5 text-blue-500" />
          <div>
            <div className="text-xs text-gray-500 uppercase">Route Status</div>
            <div className="text-sm text-white">{connectionLost ? 'Disconnected' : 'Synchronized with backend'}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
