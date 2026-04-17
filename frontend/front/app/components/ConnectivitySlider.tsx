import { Zap, Radio } from 'lucide-react';
import { motion } from 'framer-motion';

interface ConnectivitySliderProps {
  value: number;
  onChange: (value: number) => void;
}

export default function ConnectivitySlider({ value, onChange }: ConnectivitySliderProps) {
  const getMode = (v: number) => {
    if (v < 33) return "fast";
    if (v < 66) return "balanced";
    return "connected";
  };

  const getIndex = (v: number) => {
    if (v < 33) return 0;
    if (v < 66) return 1;
    return 2;
  };

  const mode = getMode(value);
  const index = getIndex(value);

  const setMode = (m: string) => {
    if (m === "fast") onChange(0);
    else if (m === "balanced") onChange(50);
    else onChange(100);
  };

  return (
    <div className="space-y-3">
      {/* Labels */}
      <div className="flex items-center justify-between text-xs text-gray-600">
        <div className="flex items-center gap-1.5">
          <Zap className="w-3.5 h-3.5 text-blue-600" />
          <span>Fastest</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span>Best Coverage</span>
          <Radio className="w-3.5 h-3.5 text-green-600" />
        </div>
      </div>

      {/* Sliding Toggle */}
      <div className="relative flex bg-gradient-to-r from-blue-100 via-purple-100 to-green-100 rounded-full p-1">
        
        {/* Sliding indicator */}
        <motion.div
          className="absolute top-1 bottom-1 bg-white rounded-full shadow"
          animate={{
            left: `calc(${index * 33.33}% + 4px)`,
            width: "calc(33.33% - 8px)"
          }}
          transition={{ type: "spring", stiffness: 400, damping: 30 }}
        />

        {/* Buttons */}
        {[
          { key: "fast", label: "Fast" },
          { key: "balanced", label: "Balanced" },
          { key: "connected", label: "Connected" },
        ].map((m, i) => (
          <button
            key={m.key}
            onClick={() => setMode(m.key)}
            className={`flex-1 py-2 text-xs font-medium z-10 ${
              index === i ? "text-gray-900" : "text-gray-500"
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {/* Status indicator */}
      <div className="text-center">
        <div className="inline-flex items-center gap-2 bg-gray-100 rounded-md px-3 py-1.5">
          <span className="text-xs text-gray-600">Mode:</span>
          <span className="text-xs font-semibold text-gray-900">
            {mode === "fast" && "Speed Priority"}
            {mode === "balanced" && "Balanced"}
            {mode === "connected" && "Coverage Priority"}
          </span>
        </div>
      </div>
    </div>
  );
}