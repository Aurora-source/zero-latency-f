import { Zap, Radio } from 'lucide-react';
import { motion } from 'framer-motion';

interface ConnectivitySliderProps {
  value: number;
  onChange: (value: number) => void;
}

export default function ConnectivitySlider({ value, onChange }: ConnectivitySliderProps) {
  const getMode = (v: number) => (v < 33 ? "fast" : v < 66 ? "balanced" : "connected");
  const getIndex = (v: number) => (v < 33 ? 0 : v < 66 ? 1 : 2);

  const mode = getMode(value);
  const index = getIndex(value);

  const setMode = (m: string) => {
    if (m === "fast") onChange(0);
    else if (m === "balanced") onChange(50);
    else onChange(100);
  };

  return (
    <div className="space-y-3">
      <div className="flex justify-between text-xs text-white/60">
        <div className="flex items-center gap-1.5">
          <Zap className="w-3.5 h-3.5 text-blue-400" />
          <span>Fastest</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span>Best Coverage</span>
          <Radio className="w-3.5 h-3.5 text-green-400" />
        </div>
      </div>

      <div className="relative flex bg-white/10 backdrop-blur-xl rounded-full p-1 border border-white/20 overflow-hidden">

        {/* Sliding indicator */}
        <motion.div
          className="absolute top-1 bottom-1 bg-white rounded-full shadow"
          animate={{
            left: `calc(${index * 33.333}% + 4px)`,
            width: "calc(33.333% - 8px)"
          }}
          transition={{ type: "spring", stiffness: 400, damping: 30 }}
        />

        {/* Buttons */}
        {["fast", "balanced", "connected"].map((m, i) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`flex-1 py-2 text-xs font-medium z-10 ${
              index === i ? "text-black" : "text-white/50"
            }`}
          >
            {m.charAt(0).toUpperCase() + m.slice(1)}
          </button>
        ))}
      </div>

      <div className="text-center">
        <div className="inline-flex items-center gap-2 bg-white/20 backdrop-blur-md rounded-md px-3 py-1.5">
          <span className="text-xs text-white/60">Mode:</span>
          <span className="text-xs font-semibold text-white/90">
            {mode === "fast" && "Speed Priority"}
            {mode === "balanced" && "Balanced"}
            {mode === "connected" && "Coverage Priority"}
          </span>
        </div>
      </div>
    </div>
  );
}