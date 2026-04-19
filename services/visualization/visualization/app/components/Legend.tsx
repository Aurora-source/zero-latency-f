import { SignalHigh, SignalMedium, SignalLow } from 'lucide-react';

export default function Legend() {
  const signalLevels = [
    { label: 'Strong Signal', color: '#10b981' },
    { label: 'Medium Signal', color: '#fbbf24' },
    { label: 'Weak Signal', color: '#ef4444' }
  ];

  return (
    <div className="bg-black/35 backdrop-blur-xl rounded-2xl border border-white/10 shadow-lg p-3">
      <h4 className="text-white/90 font-semibold text-xs mb-2.5">
        Signal Strength
      </h4>

      <div className="space-y-2">
        {signalLevels.map((level, index) => {
          const icons = [SignalHigh, SignalMedium, SignalLow];
          const Icon = icons[index];

          return (
            <div key={level.label} className="flex items-center gap-2">
              <div
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: level.color }}
              />

              <Icon
                className="w-4 h-4 stroke-[2.5] drop-shadow-[0_0_2px_rgba(255,255,255,0.5)]"
                style={{ color: level.color }}
              />

              <span className="text-white/90 text-xs">
                {level.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}