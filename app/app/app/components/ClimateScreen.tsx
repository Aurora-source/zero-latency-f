import { Wind, Snowflake, Fan, Flame, ArrowUp, ArrowDown } from 'lucide-react';
import { useState } from 'react';

export function ClimateScreen() {
  const [driverTemp, setDriverTemp] = useState(21);
  const [passengerTemp, setPassengerTemp] = useState(21);
  const [acOn, setAcOn] = useState(true);
  const [defrost, setDefrost] = useState(false);
  const [recirculate, setRecirculate] = useState(false);
  const [seatHeat, setSeatHeat] = useState(1);

  const TemperatureControl = ({
    temp,
    setTemp,
    label,
    side
  }: {
    temp: number;
    setTemp: (temp: number) => void;
    label: string;
    side: 'left' | 'right';
  }) => {
    return (
      <div className="flex flex-col items-center">
        <div className="text-xs text-gray-500 uppercase mb-3">{label}</div>
        <button
          onClick={() => setTemp(Math.min(28, temp + 0.5))}
          className="w-12 h-12 rounded-lg bg-[#2a2a2a] hover:bg-[#3a3a3a] flex items-center justify-center transition-all mb-2"
        >
          <ArrowUp className="w-5 h-5 text-gray-300" />
        </button>
        <div className="text-6xl text-white my-4">{temp}°</div>
        <button
          onClick={() => setTemp(Math.max(16, temp - 0.5))}
          className="w-12 h-12 rounded-lg bg-[#2a2a2a] hover:bg-[#3a3a3a] flex items-center justify-center transition-all mt-2"
        >
          <ArrowDown className="w-5 h-5 text-gray-300" />
        </button>
      </div>
    );
  };

  return (
    <div className="h-full pb-20 p-8 bg-[#0a0a0a]">
      <div className="flex items-center justify-center gap-24 mb-12">
        {/* Passenger Temperature (Left) */}
        <TemperatureControl
          temp={passengerTemp}
          setTemp={setPassengerTemp}
          label="Passenger"
          side="left"
        />

        {/* Car Airflow Diagram */}
        <div className="relative w-96 h-64">
          <svg viewBox="0 0 400 300" className="w-full h-full">
            {/* Car outline */}
            <path
              d="M 80,150 L 80,100 L 120,80 L 280,80 L 320,100 L 320,150 L 280,200 L 120,200 Z"
              fill="none"
              stroke="#3a3a3a"
              strokeWidth="2"
            />
            {/* Windshield */}
            <line x1="120" y1="80" x2="280" y2="80" stroke="#3a3a3a" strokeWidth="3" />
            {/* Seats */}
            <rect x="140" y="140" width="40" height="40" fill="none" stroke="#4a4a4a" strokeWidth="2" rx="4" />
            <rect x="220" y="140" width="40" height="40" fill="none" stroke="#4a4a4a" strokeWidth="2" rx="4" />

            {/* Airflow arrows */}
            {acOn && (
              <>
                <path d="M 200,60 L 200,80" stroke="#3b82f6" strokeWidth="2" markerEnd="url(#arrowhead)" />
                <path d="M 160,150 L 160,130" stroke="#3b82f6" strokeWidth="2" markerEnd="url(#arrowhead)" />
                <path d="M 240,150 L 240,130" stroke="#3b82f6" strokeWidth="2" markerEnd="url(#arrowhead)" />
              </>
            )}

            <defs>
              <marker id="arrowhead" markerWidth="10" markerHeight="10" refX="5" refY="5" orient="auto">
                <polygon points="0,0 10,5 0,10" fill="#3b82f6" />
              </marker>
            </defs>
          </svg>
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-center">
            <div className="text-lg text-white">{acOn ? 'Climate Active' : 'Climate Off'}</div>
            <div className="text-sm text-gray-500">Auto Mode</div>
          </div>
        </div>

        {/* Driver Temperature (Right) */}
        <TemperatureControl
          temp={driverTemp}
          setTemp={setDriverTemp}
          label="Driver"
          side="right"
        />
      </div>

      {/* Control Buttons */}
      <div className="flex items-center justify-center gap-6 mb-8">
        <button
          onClick={() => setAcOn(!acOn)}
          className={`w-32 h-32 rounded-xl flex flex-col items-center justify-center transition-all ${
            acOn
              ? 'bg-blue-500 text-black'
              : 'bg-[#1a1a1a] text-gray-400 border border-[#2a2a2a]'
          }`}
        >
          <Snowflake className="w-8 h-8 mb-2" />
          <span className="text-sm">A/C</span>
        </button>

        <button
          onClick={() => setDefrost(!defrost)}
          className={`w-32 h-32 rounded-xl flex flex-col items-center justify-center transition-all ${
            defrost
              ? 'bg-[#2a2a2a] text-white'
              : 'bg-[#1a1a1a] text-gray-400 border border-[#2a2a2a]'
          }`}
        >
          <Wind className="w-8 h-8 mb-2" />
          <span className="text-sm">Defrost</span>
        </button>

        <button
          onClick={() => setRecirculate(!recirculate)}
          className={`w-32 h-32 rounded-xl flex flex-col items-center justify-center transition-all ${
            recirculate
              ? 'bg-[#2a2a2a] text-white'
              : 'bg-[#1a1a1a] text-gray-400 border border-[#2a2a2a]'
          }`}
        >
          <Fan className="w-8 h-8 mb-2" />
          <span className="text-sm">Recirculate</span>
        </button>

        <button
          onClick={() => setSeatHeat((seatHeat + 1) % 4)}
          className={`w-32 h-32 rounded-xl flex flex-col items-center justify-center transition-all ${
            seatHeat > 0
              ? 'bg-[#2a2a2a] text-white'
              : 'bg-[#1a1a1a] text-gray-400 border border-[#2a2a2a]'
          }`}
        >
          <Flame className="w-8 h-8 mb-2" />
          <span className="text-sm">Seat {seatHeat > 0 ? seatHeat : 'Off'}</span>
        </button>
      </div>

      {/* Additional Info */}
      <div className="flex justify-center gap-8">
        <div className="bg-[#1a1a1a] rounded-xl p-6 border border-[#2a2a2a]">
          <div className="text-xs text-gray-500 mb-2">Inside Temperature</div>
          <div className="text-2xl text-white">21°C</div>
        </div>
        <div className="bg-[#1a1a1a] rounded-xl p-6 border border-[#2a2a2a]">
          <div className="text-xs text-gray-500 mb-2">Outside Temperature</div>
          <div className="text-2xl text-white">28°C</div>
        </div>
        <div className="bg-[#1a1a1a] rounded-xl p-6 border border-[#2a2a2a]">
          <div className="text-xs text-gray-500 mb-2">Air Quality</div>
          <div className="text-2xl text-green-500">Good</div>
        </div>
      </div>
    </div>
  );
}
