import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Search, Layers, Navigation, AlertTriangle } from 'lucide-react';
import MapView from './components/MapView';
import RouteCard from './components/RouteCard';
import ConnectivitySlider from './components/ConnectivitySlider';
import Legend from './components/Legend';

export default function App() {
  const [showHeatmap, setShowHeatmap] = useState(true);
  const [selectedRoute, setSelectedRoute] = useState(1);
  const [connectivityWeight, setConnectivityWeight] = useState(50);

  const generateRoutes = (weight: number) => {
    return [
      {
        id: 0,
        label: 'Most Connected',
        time: weight > 60 ? '29 min' : '28 min',
        distance: weight > 60 ? '21.5 km' : '21.0 km',
        connectivity: weight > 60 ? 0.95 : 0.90,
        color: '#10b981',
        path: 'urban'
      },
      {
        id: 1,
        label: 'Balanced',
        time: '25–26 min',
        distance: '19.8–20.1 km',
        connectivity: weight > 60 ? 0.85 : weight < 40 ? 0.75 : 0.82,
        color: '#8b5cf6',
        path: 'mixed'
      },
      {
        id: 2,
        label: 'Fastest',
        time: '22–23 min',
        distance: '18.5–19.0 km',
        connectivity: weight > 60 ? 0.72 : 0.68,
        color: '#3b82f6',
        warning: 'Low network coverage on some segments',
        path: 'highway'
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

  return (
    <div className="size-full bg-black relative overflow-hidden" style={{ fontFamily: 'system-ui, -apple-system, sans-serif' }}>

      

      <MapView
        routes={routes}
        selectedRoute={selectedRoute}
        showHeatmap={showHeatmap}
      />

      <motion.div
        initial={{ y: -20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="absolute top-4 left-1/2 -translate-x-1/2 w-full max-w-2xl px-4 z-30"
      >
        <div className="bg-black/30 backdrop-blur-xl rounded-2xl border border-white/10 shadow-xl p-3">
          <div className="flex items-center gap-2">

            <div className="flex-1 flex items-center gap-2 bg-white/20 rounded px-3 py-2.5 border border-white/10">
              <Navigation className="w-4 h-4 text-white/60" />
              <input
                type="text"
                placeholder="Start Location"
                defaultValue="Downtown Tech Hub, San Francisco"
                className="flex-1 bg-transparent text-white placeholder:text-white/50 outline-none text-sm"
              />
            </div>

            <div className="flex-1 flex items-center gap-2 bg-white/20 rounded px-3 py-2.5 border border-white/10">
              <Search className="w-4 h-4 text-white/60" />
              <input
                type="text"
                placeholder="Destination"
                defaultValue="Silicon Valley Research Center"
                className="flex-1 bg-transparent text-white placeholder:text-white/50 outline-none text-sm"
              />
            </div>

            <button className="px-5 py-2.5 bg-blue-500/80 backdrop-blur-md rounded text-white text-sm font-medium">
              Search
            </button>

          </div>
        </div>
      </motion.div>

      <motion.div
        initial={{ x: -30, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="absolute left-4 top-24 w-[380px] z-20 space-y-3"
      >
        <div className="bg-black/30 backdrop-blur-xl rounded-2xl border border-white/10 shadow-xl p-4">
          <h3 className="font-semibold text-white/90 mb-4 text-sm">
            Routing Priority
          </h3>
          <ConnectivitySlider value={connectivityWeight} onChange={setConnectivityWeight} />
        </div>

        <div className="bg-black/30 backdrop-blur-xl rounded-2xl border border-white/10 shadow-xl p-4">
          <h3 className="font-semibold text-white/90 mb-3 text-sm">
            Available Routes
          </h3>

          <div className="space-y-2">
            {routes.map((route, index) => (
              <RouteCard
                key={route.id}
                route={route}
                isSelected={selectedRoute === route.id}
                onClick={() => {
                  if (route.id === 0) setConnectivityWeight(100);
                  else if (route.id === 1) setConnectivityWeight(50);
                  else setConnectivityWeight(0);
                }}
                delay={index * 0.05}
              />
            ))}
          </div>
        </div>

        {routes[selectedRoute]?.warning && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-amber-500/10 backdrop-blur-md rounded-2xl border border-amber-300/20 p-3"
          >
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-300 mt-0.5" />
              <div>
                <p className="text-amber-200 text-xs font-medium mb-1">
                  Network Warning
                </p>
                <p className="text-amber-300 text-xs">
                  {routes[selectedRoute].warning}
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </motion.div>

      <motion.div
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        className="absolute bottom-4 right-4 z-20 space-y-3"
      >
        <div className="bg-black/30 backdrop-blur-xl rounded-2xl border border-white/10 shadow-lg p-3">
          <button
            onClick={() => setShowHeatmap(!showHeatmap)}
            className="flex items-center gap-2.5 w-full"
          >
            <div className={`w-10 h-5 rounded-full relative ${showHeatmap ? 'bg-blue-500' : 'bg-white/30'}`}>
              <motion.div
                animate={{ x: showHeatmap ? 20 : 0 }}
                transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white"
              />
            </div>

            <div className="flex items-center gap-2 text-white/80 text-sm font-medium">
              <Layers className="w-4 h-4" />
              <span>Network Heatmap</span>
            </div>
          </button>
        </div>

        {showHeatmap && <Legend />}
      </motion.div>
    </div>
  );
}