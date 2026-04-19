import { Battery, Gauge, Lock, Navigation, Radio, Route, Server, Wifi } from 'lucide-react';
import { useNavigate } from 'react-router';
import { useEffect, useMemo, useState } from 'react';

import {
  DEFAULT_PREDICTION_REQUEST,
  DEFAULT_ROUTE_REQUEST,
  fetchCacheStatus,
  fetchPrediction,
  fetchRoute,
} from '../api/apiClient';

function clampPercent(value: number | undefined): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(value ?? 0)));
}

function routeDistanceKm(coordinates: [number, number][] | undefined): number {
  if (!coordinates || coordinates.length < 2) {
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

export function DashboardScreen() {
  const navigate = useNavigate();
  const [currentTime, setCurrentTime] = useState(new Date());
  const [coveragePercent, setCoveragePercent] = useState(0);
  const [signalStrength, setSignalStrength] = useState(0);
  const [routeEtaMinutes, setRouteEtaMinutes] = useState(0);
  const [routeDistance, setRouteDistance] = useState(0);
  const [routeSource, setRouteSource] = useState('Connecting');
  const [routeSummary, setRouteSummary] = useState('Fetching live route');
  const [tileProgress, setTileProgress] = useState(0);
  const [tileCount, setTileCount] = useState(0);
  const [connectionLost, setConnectionLost] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string>('Waiting for backend');

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let disposed = false;

    const loadData = async () => {
      const [cacheResult, routeResult, predictionResult] = await Promise.allSettled([
        fetchCacheStatus(),
        fetchRoute(DEFAULT_ROUTE_REQUEST),
        fetchPrediction(DEFAULT_PREDICTION_REQUEST),
      ]);

      if (disposed) {
        return;
      }

      let anySuccess = false;
      let hadFailure = false;

      if (cacheResult.status === 'fulfilled') {
        anySuccess = true;
        console.log('Response:', cacheResult.value);
        setCoveragePercent(
          clampPercent(
            cacheResult.value.real_coverage_percent ?? cacheResult.value.coverage_percent ?? 0,
          ),
        );
        setTileProgress(clampPercent(cacheResult.value.percent_complete ?? 0));
        setTileCount(Math.round(cacheResult.value.tile_count ?? cacheResult.value.total_tiles ?? 0));
      } else {
        hadFailure = true;
      }

      if (routeResult.status === 'fulfilled') {
        anySuccess = true;
        console.log('Response:', routeResult.value);
        const coordinates = routeResult.value.coordinates ?? [];
        const distanceKm = routeDistanceKm(coordinates);
        setRouteDistance(distanceKm);
        setRouteEtaMinutes(Number(routeResult.value.total_time_min ?? 0));
        setRouteSource(routeResult.value.signal_source ?? 'Live backend');
        setRouteSummary(routeResult.value.explanation?.summary ?? 'Balanced route ready');
      } else {
        hadFailure = true;
      }

      if (predictionResult.status === 'fulfilled') {
        anySuccess = true;
        console.log('Response:', predictionResult.value);
        const rawScore = Number(
          predictionResult.value.scores?.[DEFAULT_PREDICTION_REQUEST.segments[0].id] ?? 0,
        );
        setSignalStrength(clampPercent(rawScore * 100));
      } else {
        hadFailure = true;
      }

      setConnectionLost(hadFailure);
      setLastUpdated(
        anySuccess && !hadFailure
          ? `Updated ${new Date().toLocaleTimeString('en-US', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
              hour12: false,
            })}`
          : 'Connection Lost',
      );
    };

    loadData().catch((error) => {
      console.error('Dashboard load failed:', error);
      setConnectionLost(true);
      setLastUpdated('Connection Lost');
    });
    const interval = setInterval(() => {
      loadData().catch((error) => {
        console.error('Dashboard load failed:', error);
        setConnectionLost(true);
        setLastUpdated('Connection Lost');
      });
    }, 8000);

    return () => {
      disposed = true;
      clearInterval(interval);
    };
  }, []);

  const averageSpeed = useMemo(() => {
    if (routeEtaMinutes <= 0 || routeDistance <= 0) {
      return 0;
    }
    return (routeDistance / routeEtaMinutes) * 60;
  }, [routeDistance, routeEtaMinutes]);

  return (
    <div className="h-full pb-20 relative bg-[#0a0a0a]">
      <div className="absolute inset-0">
        <div className="w-full h-full bg-gradient-to-b from-[#1a1a1a] to-[#0a0a0a] relative">
          <div className="absolute inset-0 opacity-5">
            <div className="grid grid-cols-24 grid-rows-12 h-full w-full">
              {Array.from({ length: 288 }).map((_, i) => (
                <div key={i} className="border border-gray-700" />
              ))}
            </div>
          </div>

          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
            <div className={`w-2.5 h-2.5 rounded-full ${connectionLost ? 'bg-red-500' : 'bg-blue-500'}`} />
          </div>

          <div className="absolute inset-0 opacity-10">
            <div className="absolute top-1/3 left-0 right-0 h-px bg-gray-600" />
            <div className="absolute top-2/3 left-0 right-0 h-px bg-gray-600" />
            <div className="absolute top-0 bottom-0 left-1/3 w-px bg-gray-600" />
            <div className="absolute top-0 bottom-0 right-1/3 w-px bg-gray-600" />
          </div>
        </div>
      </div>

      <div className="relative z-10 p-6 flex items-center justify-between">
        <div className="flex items-center gap-8">
          <div className="text-white">
            <div className="text-2xl">
              {currentTime.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })}
            </div>
            <div className="text-xs text-gray-500">
              {currentTime.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
            </div>
          </div>

          <div className="text-center">
            <div className="text-6xl text-white font-light">{signalStrength}</div>
            <div className="text-xs text-gray-500">signal score</div>
          </div>

          <div className="flex items-center gap-2 bg-[#1a1a1a] px-4 py-2 rounded-lg">
            <Navigation className={`w-4 h-4 ${connectionLost ? 'text-red-500' : 'text-blue-500'}`} />
            <span className="text-sm text-gray-400">
              {connectionLost ? 'Connection Lost' : routeSummary}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <Lock className="w-5 h-5 text-gray-500" />
          <div className="flex items-center gap-2">
            <Wifi className={`w-5 h-5 ${coveragePercent > 0 ? 'text-green-400' : 'text-yellow-400'}`} />
            <span className="text-sm text-gray-400">{coveragePercent}% coverage</span>
          </div>
          <div className="flex items-center gap-2">
            <Gauge className="w-5 h-5 text-gray-400" />
            <span className="text-sm text-gray-400">{routeSource}</span>
          </div>
        </div>
      </div>

      {connectionLost ? (
        <div className="relative z-10 px-6">
          <div className="inline-flex items-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-200">
            <Server className="w-4 h-4" />
            Connection Lost
          </div>
        </div>
      ) : null}

      <div className="relative z-10 px-6 pb-6 grid grid-cols-3 gap-4 mt-32">
        <div className="bg-[#1a1a1a]/80 backdrop-blur-sm rounded-xl p-6 border border-[#2a2a2a]">
          <div className="text-xs text-gray-500 uppercase mb-4">Live Route</div>
          <div className="space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">Distance</span>
              <span className="text-xl text-white">{routeDistance.toFixed(1)} km</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">ETA</span>
              <span className="text-xl text-white">{routeEtaMinutes.toFixed(1)} min</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">Avg Speed</span>
              <span className="text-xl text-white">{averageSpeed.toFixed(0)} km/h</span>
            </div>
          </div>
        </div>

        <div className="bg-[#1a1a1a]/80 backdrop-blur-sm rounded-xl p-6 border border-[#2a2a2a]">
          <div className="text-xs text-gray-500 uppercase mb-4">Signal</div>
          <div className="flex items-center gap-4 mb-4">
            <Battery className={`w-10 h-10 ${coveragePercent > 0 ? 'text-green-500' : 'text-yellow-500'}`} />
            <div>
              <div className="text-4xl text-white">{coveragePercent}%</div>
              <div className="text-sm text-gray-400">{routeSource}</div>
            </div>
          </div>
          <div className="w-full h-2 bg-[#2a2a2a] rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${coveragePercent > 0 ? 'bg-green-500' : 'bg-yellow-500'}`}
              style={{ width: `${coveragePercent}%` }}
            />
          </div>
          <div className="flex items-center gap-2 mt-3">
            <Radio className="w-4 h-4 text-gray-500" />
            <span className="text-xs text-gray-500">{signalStrength}% predicted signal strength</span>
          </div>
        </div>

        <div className="bg-[#1a1a1a]/80 backdrop-blur-sm rounded-xl p-6 border border-[#2a2a2a]">
          <div className="text-xs text-gray-500 uppercase mb-4">Backend Status</div>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Server className={`w-6 h-6 ${connectionLost ? 'text-red-400' : 'text-blue-400'}`} />
                <span className="text-sm text-gray-400">API</span>
              </div>
              <span className="text-lg text-white">{connectionLost ? 'Offline' : 'Connected'}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">Tiles Indexed</span>
              <span className="text-2xl text-white">{tileCount}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">Cache Build</span>
              <span className="text-2xl text-white">{tileProgress}%</span>
            </div>
            <button
              onClick={() => navigate('/navigation')}
              className="w-full bg-[#2a2a2a] hover:bg-[#3a3a3a] rounded-lg py-3 text-sm text-white transition-all"
            >
              Open Live Navigation
            </button>
          </div>
        </div>
      </div>

      <div className="absolute bottom-24 left-6 right-6 z-10">
        <div className="flex gap-3">
          <button className="flex-1 bg-[#1a1a1a]/80 backdrop-blur-sm rounded-xl py-4 text-sm text-white border border-[#2a2a2a]">
            {lastUpdated}
          </button>
          <button className="flex-1 bg-[#1a1a1a]/80 backdrop-blur-sm rounded-xl py-4 text-sm text-white border border-[#2a2a2a]">
            {coveragePercent > 0 ? 'Real tower coverage active' : 'AI estimate active'}
          </button>
          <button className="flex-1 bg-[#1a1a1a]/80 backdrop-blur-sm rounded-xl py-4 text-sm text-white border border-[#2a2a2a]">
            Route source: {routeSource}
          </button>
          <button className="flex-1 bg-[#1a1a1a]/80 backdrop-blur-sm rounded-xl py-4 text-sm text-white border border-[#2a2a2a]">
            Signal score: {signalStrength}%
          </button>
        </div>
      </div>
    </div>
  );
}
