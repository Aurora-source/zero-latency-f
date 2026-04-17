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

  // FIXED ORDER — never changes
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

  // Only update route DATA, not order
  useEffect(() => {
    setRoutes(generateRoutes(connectivityWeight));
  }, [connectivityWeight]);

  // Control highlight based on slider
  useEffect(() => {
    if (connectivityWeight < 40) {
      setSelectedRoute(2); // Fastest
    } else if (connectivityWeight > 60) {
      setSelectedRoute(0); // Connected
    } else {
      setSelectedRoute(1); // Balanced
    }
  }, [connectivityWeight]);

  return (
    <div className="size-full bg-white relative overflow-hidden" style={{ fontFamily: 'system-ui, -apple-system, sans-serif' }}>

      <MapView
        routes={routes}
        selectedRoute={selectedRoute}
        showHeatmap={showHeatmap}
        connectivityWeight={connectivityWeight}
      />

      {/* Top Search Bar */}
      <motion.div
        initial={{ y: -20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="absolute top-4 left-1/2 -translate-x-1/2 w-full max-w-2xl px-4 z-30"
      >
        <div className="bg-white rounded-lg shadow-lg border border-gray-200 p-3">
          <div className="flex items-center gap-2">
            <div className="flex-1 flex items-center gap-2 bg-gray-50 rounded px-3 py-2.5 border border-gray-200">
              <Navigation className="w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="Start Location"
                defaultValue="Downtown Tech Hub, San Francisco"
                className="flex-1 bg-transparent text-gray-900 placeholder:text-gray-400 outline-none text-sm"
              />
            </div>
            <div className="flex-1 flex items-center gap-2 bg-gray-50 rounded px-3 py-2.5 border border-gray-200">
              <Search className="w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="Destination"
                defaultValue="Silicon Valley Research Center"
                className="flex-1 bg-transparent text-gray-900 placeholder:text-gray-400 outline-none text-sm"
              />
            </div>
            <button className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 rounded text-white text-sm font-medium transition-colors">
              Search
            </button>
          </div>
        </div>
      </motion.div>

      {/* Left Panel */}
      <motion.div
        initial={{ x: -30, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="absolute left-4 top-24 w-[380px] z-20 space-y-3"
      >
        <div className="bg-white rounded-lg shadow-lg border border-gray-200 p-4">
          <h3 className="font-semibold text-gray-900 mb-4 text-sm">
            Routing Priority
          </h3>
          <ConnectivitySlider value={connectivityWeight} onChange={setConnectivityWeight} />
        </div>

        <div className="bg-white rounded-lg shadow-lg border border-gray-200 p-4">
          <h3 className="font-semibold text-gray-900 mb-3 text-sm">
            Available Routes
          </h3>
          <div className="space-y-2">
            {routes.map((route, index) => (
              <RouteCard
                key={route.id}
                route={route}
                isSelected={selectedRoute === route.id}
              onClick={() => {
                if (route.id === 0) setConnectivityWeight(100);   // Connected
                else if (route.id === 1) setConnectivityWeight(50); // Balanced
                else setConnectivityWeight(0);                    // Fastest
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
            className="bg-amber-50 rounded-lg border border-amber-200 p-3"
          >
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-amber-900 text-xs font-medium mb-1">Network Warning</p>
                <p className="text-amber-700 text-xs">
                  {routes[selectedRoute].warning}
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </motion.div>

      {/* Bottom Controls */}
      <motion.div
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="absolute bottom-4 right-4 z-20 space-y-3"
      >
        <div className="bg-white rounded-lg shadow-lg border border-gray-200 p-3">
          <button
            onClick={() => setShowHeatmap(!showHeatmap)}
            className="flex items-center gap-2.5 w-full"
          >
            <div className={`w-10 h-5 rounded-full relative transition-colors ${showHeatmap ? 'bg-blue-500' : 'bg-gray-300'}`}>
              <motion.div
                animate={{ x: showHeatmap ? 20 : 0 }}
                transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-sm"
              />
            </div>
            <div className="flex items-center gap-2 text-gray-700 text-sm font-medium">
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