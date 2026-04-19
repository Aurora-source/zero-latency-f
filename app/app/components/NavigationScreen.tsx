import { ArrowUpRight, Navigation } from 'lucide-react';

export function NavigationScreen() {
  return (
    <div className="h-full pb-20 relative bg-[#0a0a0a]">
      {/* Map Background */}
      <div className="absolute inset-0 bg-gradient-to-b from-[#1a1a1a] to-[#0a0a0a]">
        {/* Route visualization */}
        <div className="absolute inset-0 opacity-40">
          <svg className="w-full h-full">
            <path
              d="M 200,600 Q 400,400 600,500 T 1200,300 L 1400,200"
              stroke="#3b82f6"
              strokeWidth="8"
              fill="none"
              strokeLinecap="round"
            />
          </svg>
        </div>

        {/* Grid pattern */}
        <div className="absolute inset-0 opacity-5">
          <div className="grid grid-cols-24 grid-rows-12 h-full w-full">
            {Array.from({ length: 288 }).map((_, i) => (
              <div key={i} className="border border-gray-700" />
            ))}
          </div>
        </div>

        {/* Current position marker */}
        <div className="absolute bottom-1/3 left-1/4">
          <div className="w-3 h-3 bg-blue-500 rounded-full" />
        </div>
      </div>

      {/* Next Turn Instruction - Top Left */}
      <div className="absolute top-8 left-8 bg-[#1a1a1a]/95 backdrop-blur-xl rounded-2xl p-6 border border-[#2a2a2a] max-w-md">
        <div className="flex items-center gap-6">
          <div className="w-20 h-20 bg-[#2a2a2a] rounded-xl flex items-center justify-center">
            <ArrowUpRight className="w-10 h-10 text-white" strokeWidth={2} />
          </div>
          <div>
            <div className="text-xs text-gray-500 uppercase mb-1">In 500 m</div>
            <div className="text-2xl text-white mb-1">Turn Right</div>
            <div className="text-sm text-gray-400">Main Street</div>
          </div>
        </div>
      </div>

      {/* Trip Info - Bottom Right */}
      <div className="absolute bottom-24 right-8 bg-[#1a1a1a]/95 backdrop-blur-xl rounded-2xl p-6 border border-[#2a2a2a] min-w-[280px]">
        <div className="flex items-center gap-3 mb-4">
          <Navigation className="w-5 h-5 text-blue-500" />
          <div className="text-lg text-white">Downtown Plaza</div>
        </div>
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-gray-400">ETA</span>
            <span className="text-xl text-white">3:47 PM</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Distance</span>
            <span className="text-xl text-white">13.5 km</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">Traffic</span>
            <span className="text-xl text-green-500">Light</span>
          </div>
        </div>
      </div>
    </div>
  );
}
