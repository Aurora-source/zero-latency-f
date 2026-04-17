import { Zap, Radio } from 'lucide-react';

interface ConnectivitySliderProps {
  value: number;
  onChange: (value: number) => void;
}

export default function ConnectivitySlider({ value, onChange }: ConnectivitySliderProps) {
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(Number(e.target.value));
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

      {/* Slider container */}
      <div className="relative py-2">
        {/* Slider input */}
        <input
          type="range"
          min="0"
          max="100"
          value={value}
          onChange={handleChange}
          className="w-full h-2 bg-gradient-to-r from-blue-200 via-purple-200 to-green-200 rounded-full appearance-none cursor-pointer slider"
          style={{
            background: `linear-gradient(to right, #3b82f6 0%, #8b5cf6 50%, #10b981 100%)`
          }}
        />
      </div>

      {/* Status indicator */}
      <div className="text-center">
        <div className="inline-flex items-center gap-2 bg-gray-100 rounded-md px-3 py-1.5">
          <span className="text-xs text-gray-600">Mode:</span>
          <span className="text-xs font-semibold text-gray-900">
            {value < 30 && 'Speed Priority'}
            {value >= 30 && value <= 70 && 'Balanced'}
            {value > 70 && 'Coverage Priority'}
          </span>
        </div>
      </div>

      <style>{`
        .slider::-webkit-slider-thumb {
          appearance: none;
          width: 18px;
          height: 18px;
          border-radius: 50%;
          background: white;
          border: 2px solid #3b82f6;
          cursor: pointer;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        .slider::-moz-range-thumb {
          width: 18px;
          height: 18px;
          border-radius: 50%;
          background: white;
          border: 2px solid #3b82f6;
          cursor: pointer;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
      `}</style>
    </div>
  );
}
