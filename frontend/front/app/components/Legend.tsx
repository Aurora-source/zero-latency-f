import { SignalHigh, SignalMedium, SignalLow } from 'lucide-react';

export default function Legend() {
  const signalLevels = [
    { label: 'Strong Signal', color: '#10b981' },
    { label: 'Medium Signal', color: '#fbbf24' },
    { label: 'Weak Signal', color: '#ef4444' }
  ];

  return (
    <div className="bg-white rounded-lg shadow-lg border border-gray-200 p-3">
      <h4 className="text-gray-900 font-semibold text-xs mb-2.5">
        Signal Strength
      </h4>

      <div className="space-y-2">
        {signalLevels.map((level, index) => {
          const icons = [SignalHigh, SignalMedium, SignalLow];
          const Icon = icons[index];
          return (
            <div key={level.label} className="flex items-center gap-2">
              <div
                className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                style={{ backgroundColor: level.color }}
              />
              <Icon className="w-3.5 h-3.5 flex-shrink-0" style={{ color: level.color }} />
              <span className="text-gray-700 text-xs">{level.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
