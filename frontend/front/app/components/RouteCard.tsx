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
      transition={{ delay, duration: 0.3 }}
      onClick={onClick}
      className={`w-full text-left rounded-lg p-3 transition-all ${
        isSelected
          ? 'bg-blue-50 border-2 border-blue-500 shadow-sm'
          : 'bg-gray-50 border border-gray-200 hover:border-gray-300'
      }`}
    >
      <div className="flex items-start justify-between mb-2.5">
        <div className="flex items-center gap-2">
          <div
            className="w-3 h-3 rounded-full flex-shrink-0"
            style={{ backgroundColor: route.color }}
          />
          <span className="font-semibold text-gray-900 text-sm">
            {route.label}
          </span>
        </div>
        {isSelected && (
          <Navigation2 className="w-3.5 h-3.5 text-blue-600" />
        )}
      </div>

      <div className="flex items-center gap-4 mb-2.5 text-xs text-gray-600">
        <div className="flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5" />
          <span>{route.time}</span>
        </div>
        <div className="text-gray-400">•</div>
        <span>{route.distance}</span>
      </div>

      {/* Connectivity bar */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-1.5 text-xs text-gray-600">
            <Signal className="w-3 h-3" />
            <span>Coverage</span>
          </div>
          <span className="text-xs font-semibold text-gray-900">
            {connectivityPercentage}%
          </span>
        </div>
        <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${connectivityPercentage}%` }}
            transition={{ delay: 0.2 + delay, duration: 0.8, ease: 'easeOut' }}
            className="h-full rounded-full"
            style={{ backgroundColor: route.color }}
          />
        </div>
      </div>
    </motion.button>
  );
}
