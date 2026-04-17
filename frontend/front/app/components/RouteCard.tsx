import { motion } from 'framer-motion';
import { Clock, Navigation2, Signal } from 'lucide-react';

interface Route {
  id: number;
  label: string;
  time: string;
  distance: string;
  connectivity: number;
  color: string;
  warning?: string;
}

interface RouteCardProps {
  route: Route;
  isSelected: boolean;
  onClick: () => void;
  delay: number;
}

export default function RouteCard({ route, isSelected, onClick, delay }: RouteCardProps) {
  const connectivityPercentage = Math.round(route.connectivity * 100);

  return (
    <motion.button
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.25 }}
      onClick={onClick}
      className={`w-full text-left rounded-xl p-3 transition-all duration-200 ${
        isSelected
          ? 'bg-white/20 backdrop-blur-md border border-blue-400/50 shadow-lg scale-[1.02]'
          : 'bg-white/10 backdrop-blur-md border border-white/20 hover:bg-white/15'
      }`}
    >
      <div className="flex items-start justify-between mb-2.5">
        <div className="flex items-center gap-2">
          <div
            className="w-3 h-3 rounded-full"
            style={{ backgroundColor: route.color }}
          />
          <span className="font-semibold text-white/90 text-sm">
            {route.label}
          </span>
        </div>

        <Navigation2
          className={`w-3.5 h-3.5 ${
            isSelected ? 'text-blue-400 opacity-100' : 'opacity-0'
          }`}
        />
      </div>

      <div className="flex items-center gap-4 mb-2.5 text-xs text-white/60">
        <div className="flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5" />
          <span>{route.time}</span>
        </div>
        <div className="text-white/40">•</div>
        <span>{route.distance}</span>
      </div>

      <div>
        <div className="flex items-center justify-between mb-1 text-xs">
          <div className="flex items-center gap-1.5 text-white/60">
            <Signal className="w-3 h-3" />
            <span>Coverage</span>
          </div>
          <span className="text-white/90 font-semibold">
            {connectivityPercentage}%
          </span>
        </div>

        <div className="h-1.5 bg-white/20 rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${connectivityPercentage}%` }}
            transition={{ duration: 0.6 }}
            className="h-full rounded-full"
            style={{ backgroundColor: route.color }}
          />
        </div>
      </div>
    </motion.button>
  );
}