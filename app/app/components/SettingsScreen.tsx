import { Monitor, Volume2, Wifi, Shield, Settings } from 'lucide-react';
import { useState } from 'react';

export function SettingsScreen() {
  const [activeSection, setActiveSection] = useState('driver-assistance');
  const [laneKeep, setLaneKeep] = useState(true);
  const [blindSpot, setBlindSpot] = useState(true);
  const [speedLimit, setSpeedLimit] = useState(false);

  const menuItems = [
    { id: 'display', icon: Monitor, label: 'Display' },
    { id: 'sound', icon: Volume2, label: 'Sound' },
    { id: 'connectivity', icon: Wifi, label: 'Connectivity' },
    { id: 'driver-assistance', icon: Shield, label: 'Driver Assistance' },
    { id: 'system', icon: Settings, label: 'System' },
  ];

  const ToggleSwitch = ({
    enabled,
    onToggle
  }: {
    enabled: boolean;
    onToggle: () => void;
  }) => (
    <button
      onClick={onToggle}
      className={`relative w-16 h-8 rounded-full transition-all ${
        enabled ? 'bg-blue-500' : 'bg-[#2a2a2a]'
      }`}
    >
      <div
        className={`absolute top-1 w-6 h-6 bg-white rounded-full shadow-lg transition-transform ${
          enabled ? 'translate-x-9' : 'translate-x-1'
        }`}
      />
    </button>
  );

  return (
    <div className="h-full pb-20 p-8 flex gap-6 bg-[#0a0a0a]">
      {/* Left Menu */}
      <div className="w-72 bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] p-4">
        <div className="text-lg text-white mb-4">Settings</div>
        <div className="space-y-1">
          {menuItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeSection === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveSection(item.id)}
                className={`w-full flex items-center gap-3 p-3 rounded-lg transition-all ${
                  isActive
                    ? 'bg-[#2a2a2a] text-white'
                    : 'text-gray-400 hover:bg-[#1a1a1a]'
                }`}
              >
                <Icon className="w-5 h-5" />
                <span className="text-sm">{item.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Right Panel - Driver Assistance */}
      <div className="flex-1 bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] p-8">
        <div className="text-xl text-white mb-6">Driver Assistance</div>

        <div className="space-y-4 mb-12">
          <div className="flex items-center justify-between p-5 bg-[#0a0a0a] rounded-lg">
            <div>
              <div className="text-white mb-1">Lane Keep Assist</div>
              <div className="text-sm text-gray-500">Helps keep your vehicle centered in the lane</div>
            </div>
            <ToggleSwitch enabled={laneKeep} onToggle={() => setLaneKeep(!laneKeep)} />
          </div>

          <div className="flex items-center justify-between p-5 bg-[#0a0a0a] rounded-lg">
            <div>
              <div className="text-white mb-1">Blind Spot Monitoring</div>
              <div className="text-sm text-gray-500">Alerts you when vehicles are in your blind spot</div>
            </div>
            <ToggleSwitch enabled={blindSpot} onToggle={() => setBlindSpot(!blindSpot)} />
          </div>

          <div className="flex items-center justify-between p-5 bg-[#0a0a0a] rounded-lg">
            <div>
              <div className="text-white mb-1">Speed Limit Warning</div>
              <div className="text-sm text-gray-500">Notifies you when exceeding the speed limit</div>
            </div>
            <ToggleSwitch enabled={speedLimit} onToggle={() => setSpeedLimit(!speedLimit)} />
          </div>
        </div>

        {/* 3D Car Graphic */}
        <div className="bg-[#0a0a0a] rounded-xl p-8 border border-[#2a2a2a]">
          <div className="text-white mb-6 text-center">Active Safety Features</div>
          <div className="relative h-64 flex items-center justify-center">
            <svg viewBox="0 0 600 300" className="w-full max-w-2xl">
              {/* Car body */}
              <path
                d="M 150,150 L 150,120 L 200,90 L 400,90 L 450,120 L 450,150 L 420,200 L 180,200 Z"
                fill="none"
                stroke="#3a3a3a"
                strokeWidth="3"
              />

              {/* Lane detection lines */}
              {laneKeep && (
                <>
                  <path d="M 100,250 Q 150,200 200,180" stroke="#3b82f6" strokeWidth="2" strokeDasharray="5,5" />
                  <path d="M 500,250 Q 450,200 400,180" stroke="#3b82f6" strokeWidth="2" strokeDasharray="5,5" />
                </>
              )}

              {/* Blind spot zones */}
              {blindSpot && (
                <>
                  <ellipse cx="120" cy="150" rx="35" ry="70" fill="#3b82f6" opacity="0.2" />
                  <ellipse cx="480" cy="150" rx="35" ry="70" fill="#3b82f6" opacity="0.2" />
                </>
              )}

              {/* Speed limit indicator */}
              {speedLimit && (
                <>
                  <circle cx="300" cy="50" r="20" fill="none" stroke="#ef4444" strokeWidth="3" />
                  <text x="300" y="56" textAnchor="middle" fill="#ef4444" fontSize="16">100</text>
                </>
              )}
            </svg>
          </div>
        </div>
      </div>
    </div>
  );
}
