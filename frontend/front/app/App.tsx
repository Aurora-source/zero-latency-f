import { useState, useEffect } from 'react';
import { Search, Navigation, AlertTriangle, Sun, Moon } from 'lucide-react';
import MapView from './components/MapView';
import RouteCard from './components/RouteCard';
import ConnectivitySlider from './components/ConnectivitySlider';
import Legend from './components/Legend';
import { fetchHotspots, type Hotspot } from './lib/supabase';

export default function App() {
  const [showHeatmap, setShowHeatmap] = useState(true);
  const [selectedRoute, setSelectedRoute] = useState(1);
  const [connectivityWeight, setConnectivityWeight] = useState(50);
  const [darkMode, setDarkMode] = useState(false);
  const [routeMode, setRouteMode] = useState<'fastest' | 'balanced' | 'connected'>('balanced');
  const [hotspots, setHotspots] = useState<Hotspot[]>([]);

  const [start, setStart] = useState("Detecting location...");
  const [destination, setDestination] = useState("");

  const [userLocation, setUserLocation] = useState<[number, number] | null>(null);
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [destinationCoords, setDestinationCoords] = useState<[number, number] | null>(null);

  useEffect(() => {
    fetchHotspots().then(setHotspots);
  }, []);

  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(async (pos) => {
      const lat = pos.coords.latitude;
      const lon = pos.coords.longitude;
      setUserLocation([lat, lon]);
      try {
        const res = await fetch(
          `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`
        );
        const data = await res.json();
        if (data?.display_name) setStart(data.display_name);
      } catch {}
    });
  }, []);

  useEffect(() => {
    if (destination.length < 2) {
      setSearchResults([]);
      return;
    }
    const delay = setTimeout(async () => {
      try {
        let url = `https://photon.komoot.io/api/?q=${encodeURIComponent(destination)}&limit=8&lang=en`;
        if (userLocation) {
          const [lat, lon] = userLocation;
          url += `&lat=${lat}&lon=${lon}`;
        }
        const res = await fetch(url);
        const data = await res.json();
        const features = data?.features ?? [];
        const results = features
          .filter((f: any) => {
            if (!userLocation) return true;
            const [lon2, lat2] = f.geometry.coordinates;
            const dist = Math.hypot(lat2 - userLocation[0], lon2 - userLocation[1]);
            return dist < 3;
          })
          .map((f: any) => {
            const p = f.properties;
            const parts = [p.name, p.street, p.city, p.state, p.country].filter(Boolean);
            return {
              display_name: parts.join(', '),
              lat: String(f.geometry.coordinates[1]),
              lon: String(f.geometry.coordinates[0]),
            };
          });
        setSearchResults(results.slice(0, 6));
      } catch (err) {
        console.error(err);
      }
    }, 300);
    return () => clearTimeout(delay);
  }, [destination, userLocation]);

  const handleSelect = (place: any) => {
    setDestination(place.display_name);
    setDestinationCoords([parseFloat(place.lat), parseFloat(place.lon)]);
    setSearchResults([]);
  };

  const generateRoutes = (weight: number) => {
    return [
      {
        id: 0,
        label: 'Most Connected',
        time: weight > 60 ? '29 min' : '28 min',
        distance: weight > 60 ? '21.5 km' : '21.0 km',
        connectivity: weight > 60 ? 0.95 : 0.90,
        color: '#10b981',
      },
      {
        id: 1,
        label: 'Balanced',
        time: '25–26 min',
        distance: '19.8–20.1 km',
        connectivity: weight > 60 ? 0.85 : weight < 40 ? 0.75 : 0.82,
        color: '#8b5cf6',
      },
      {
        id: 2,
        label: 'Fastest',
        time: '22–23 min',
        distance: '18.5–19.0 km',
        connectivity: weight > 60 ? 0.72 : 0.68,
        color: '#3b82f6',
        warning: 'Low network coverage on some segments',
      }
    ];
  };

  const [routes, setRoutes] = useState(generateRoutes(connectivityWeight));

  useEffect(() => {
    setRoutes(generateRoutes(connectivityWeight));
  }, [connectivityWeight]);

  useEffect(() => {
    if (connectivityWeight < 40) setSelectedRoute(2);
    else if (connectivityWeight > 60) setSelectedRoute(0);
    else setSelectedRoute(1);
  }, [connectivityWeight]);

  const handleRouteSelect = (routeId: number) => {
    setSelectedRoute(routeId);
    if (routeId === 0) {
      setConnectivityWeight(80);
      setRouteMode('connected');
    } else if (routeId === 1) {
      setConnectivityWeight(50);
      setRouteMode('balanced');
    } else if (routeId === 2) {
      setConnectivityWeight(20);
      setRouteMode('fastest');
    }
  };

  return (
    <div className="size-full bg-black relative overflow-hidden">

      <MapView
        routes={routes}
        selectedRoute={selectedRoute}
        showHeatmap={showHeatmap}
        darkMode={darkMode}
        userLocation={userLocation}
        destinationCoords={destinationCoords}
        routeMode={routeMode}
        hotspots={hotspots}
      />

      <div className="absolute top-4 right-4 z-30">
        <button
          onClick={() => setDarkMode(!darkMode)}
          className="bg-black/40 backdrop-blur-xl border border-white/10 rounded-xl px-3 py-2"
        >
          {darkMode ? <Sun className="text-yellow-300" /> : <Moon className="text-blue-300" />}
        </button>
      </div>

      <div className="absolute top-4 left-1/2 -translate-x-1/2 w-full max-w-2xl px-4 z-20">
        <div className="bg-black/40 backdrop-blur-xl rounded-2xl border border-white/10 shadow-xl p-2">
          <div className="flex items-center gap-2">
            <div className="flex-1 flex items-center gap-3 bg-white/10 rounded-xl px-4 py-3">
              <Navigation className="w-4 h-4 text-blue-400" />
              <input
                type="text"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className="flex-1 bg-transparent text-white outline-none text-sm"
              />
            </div>

            <div className="w-px h-6 bg-white/10" />

            <div className="relative flex-1">
              <div className="flex items-center gap-3 bg-white/10 rounded-xl px-4 py-3">
                <Search className="w-4 h-4 text-white/60" />
                <input
                  type="text"
                  value={destination}
                  onChange={(e) => setDestination(e.target.value)}
                  placeholder="Destination"
                  className="flex-1 bg-transparent text-white outline-none text-sm placeholder-white/40"
                />
              </div>

              {searchResults.length > 0 && (
                <div className="absolute top-full mt-2 w-full bg-black/80 backdrop-blur-xl rounded-xl border border-white/10 max-h-60 overflow-y-auto z-50">
                  {searchResults.map((place, i) => (
                    <div
                      key={i}
                      onClick={() => handleSelect(place)}
                      className="px-3 py-2 text-xs text-white hover:bg-white/10 cursor-pointer"
                    >
                      {place.display_name}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="absolute left-4 top-24 w-[380px] z-20 space-y-3">
        <div className="bg-black/30 backdrop-blur-xl rounded-2xl border border-white/10 shadow-xl p-4">
          <h3 className="text-white text-sm mb-4">Routing Priority</h3>
          <ConnectivitySlider value={connectivityWeight} onChange={setConnectivityWeight} />
        </div>

        <div className="bg-black/30 backdrop-blur-xl rounded-2xl border border-white/10 shadow-xl p-4">
          <h3 className="text-white text-sm mb-3">Available Routes</h3>
          <div className="space-y-2">
            {routes.map((route, index) => (
              <RouteCard
                key={route.id}
                route={route}
                isSelected={selectedRoute === route.id}
                onClick={() => handleRouteSelect(route.id)}
                delay={index * 0.05}
              />
            ))}
          </div>
        </div>

        {routes[selectedRoute]?.warning && (
          <div className="bg-amber-500/10 rounded-2xl border border-amber-300/20 p-3">
            <div className="flex gap-2">
              <AlertTriangle className="text-amber-300" />
              <p className="text-xs text-amber-300">
                {routes[selectedRoute].warning}
              </p>
            </div>
          </div>
        )}
      </div>

      <div className="absolute bottom-4 right-4 z-20 space-y-3">
        <div className="bg-black/30 backdrop-blur-xl border border-white/10 rounded-xl px-3 py-2 flex items-center gap-3">
          <span className="text-white text-sm">Heatmap</span>
          <button
            onClick={() => setShowHeatmap(!showHeatmap)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors duration-200 focus:outline-none ${
              showHeatmap ? 'bg-blue-500' : 'bg-white/20'
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform duration-200 ${
                showHeatmap ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>
        {showHeatmap && <Legend />}
      </div>
    </div>
  );
}