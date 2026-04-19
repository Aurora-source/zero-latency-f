import { Battery, Zap, Navigation, Wind, Lock, Gauge } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';

export function DashboardScreen() {
  const navigate = useNavigate();
  const [currentTime, setCurrentTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="h-full pb-20 relative bg-[#0a0a0a]">
      {/* Map Background */}
      <div className="absolute inset-0">
        <div className="w-full h-full bg-gradient-to-b from-[#1a1a1a] to-[#0a0a0a] relative">
          {/* Minimal map grid */}
          <div className="absolute inset-0 opacity-5">
            <div className="grid grid-cols-24 grid-rows-12 h-full w-full">
              {Array.from({ length: 288 }).map((_, i) => (
                <div key={i} className="border border-gray-700" />
              ))}
            </div>
          </div>

          {/* Current position */}
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
            <div className="w-2 h-2 bg-blue-500 rounded-full" />
          </div>

          {/* Road lines */}
          <div className="absolute inset-0 opacity-10">
            <div className="absolute top-1/3 left-0 right-0 h-px bg-gray-600" />
            <div className="absolute top-2/3 left-0 right-0 h-px bg-gray-600" />
            <div className="absolute top-0 bottom-0 left-1/3 w-px bg-gray-600" />
            <div className="absolute top-0 bottom-0 right-1/3 w-px bg-gray-600" />
          </div>
        </div>
      </div>

      {/* Top Status Bar */}
      <div className="relative z-10 p-6 flex items-center justify-between">
        <div className="flex items-center gap-8">
          {/* Time */}
          <div className="text-white">
            <div className="text-2xl">{currentTime.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })}</div>
            <div className="text-xs text-gray-500">{currentTime.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}</div>
          </div>

          {/* Speed */}
          <div className="text-center">
            <div className="text-6xl text-white font-light">68</div>
            <div className="text-xs text-gray-500">km/h</div>
          </div>

          {/* Autopilot Status */}
          <div className="flex items-center gap-2 bg-[#1a1a1a] px-4 py-2 rounded-lg">
            <Navigation className="w-4 h-4 text-blue-500" />
            <span className="text-sm text-gray-400">Cruise Control</span>
          </div>
        </div>

        {/* Right side indicators */}
        <div className="flex items-center gap-4">
          <Lock className="w-5 h-5 text-gray-500" />
          <div className="flex items-center gap-2">
            <Gauge className="w-5 h-5 text-gray-400" />
            <span className="text-sm text-gray-400">35 PSI</span>
          </div>
        </div>
      </div>

      {/* Main Content Cards */}
      <div className="relative z-10 px-6 pb-6 grid grid-cols-3 gap-4 mt-32">
        {/* Trip Info */}
        <div className="bg-[#1a1a1a]/80 backdrop-blur-sm rounded-xl p-6 border border-[#2a2a2a]">
          <div className="text-xs text-gray-500 uppercase mb-4">Trip</div>
          <div className="space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">Distance</span>
              <span className="text-xl text-white">248 km</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">Duration</span>
              <span className="text-xl text-white">3h 24m</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">Avg Speed</span>
              <span className="text-xl text-white">73 km/h</span>
            </div>
          </div>
        </div>

        {/* Battery/Energy */}
        <div className="bg-[#1a1a1a]/80 backdrop-blur-sm rounded-xl p-6 border border-[#2a2a2a]">
          <div className="text-xs text-gray-500 uppercase mb-4">Battery</div>
          <div className="flex items-center gap-4 mb-4">
            <Battery className="w-10 h-10 text-green-500" />
            <div>
              <div className="text-4xl text-white">87%</div>
              <div className="text-sm text-gray-400">462 km range</div>
            </div>
          </div>
          <div className="w-full h-2 bg-[#2a2a2a] rounded-full overflow-hidden">
            <div className="h-full w-[87%] bg-green-500 rounded-full" />
          </div>
          <div className="flex items-center gap-2 mt-3">
            <Zap className="w-4 h-4 text-gray-500" />
            <span className="text-xs text-gray-500">12 kW consumption</span>
          </div>
        </div>

        {/* Climate Quick Access */}
        <div className="bg-[#1a1a1a]/80 backdrop-blur-sm rounded-xl p-6 border border-[#2a2a2a]">
          <div className="text-xs text-gray-500 uppercase mb-4">Climate</div>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Wind className="w-6 h-6 text-blue-400" />
                <span className="text-sm text-gray-400">A/C</span>
              </div>
              <span className="text-lg text-white">On</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">Inside</span>
              <span className="text-2xl text-white">21°C</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-400">Outside</span>
              <span className="text-2xl text-white">28°C</span>
            </div>
            <button
              onClick={() => navigate('/climate')}
              className="w-full bg-[#2a2a2a] hover:bg-[#3a3a3a] rounded-lg py-3 text-sm text-white transition-all"
            >
              Full Climate Controls
            </button>
          </div>
        </div>
      </div>

      {/* Bottom Quick Actions */}
      <div className="absolute bottom-24 left-6 right-6 z-10">
        <div className="flex gap-3">
          <button className="flex-1 bg-[#1a1a1a]/80 backdrop-blur-sm hover:bg-[#2a2a2a] rounded-xl py-4 text-sm text-white border border-[#2a2a2a] transition-all">
            Charge Port
          </button>
          <button className="flex-1 bg-[#1a1a1a]/80 backdrop-blur-sm hover:bg-[#2a2a2a] rounded-xl py-4 text-sm text-white border border-[#2a2a2a] transition-all">
            Trunk
          </button>
          <button className="flex-1 bg-[#1a1a1a]/80 backdrop-blur-sm hover:bg-[#2a2a2a] rounded-xl py-4 text-sm text-white border border-[#2a2a2a] transition-all">
            Locks
          </button>
          <button className="flex-1 bg-[#1a1a1a]/80 backdrop-blur-sm hover:bg-[#2a2a2a] rounded-xl py-4 text-sm text-white border border-[#2a2a2a] transition-all">
            Sentry Mode
          </button>
        </div>
      </div>
    </div>
  );
}
