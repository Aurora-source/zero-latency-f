import { Home, Navigation, Music, Phone, Settings, Minus, Plus } from 'lucide-react';
import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router';

export function BottomNavBar() {
  const [driverTemp, setDriverTemp] = useState(21);
  const [passengerTemp, setPassengerTemp] = useState(21);
  const navigate = useNavigate();
  const location = useLocation();

  const navItems = [
    { icon: Home, label: 'Home', path: '/' },
    { icon: Navigation, label: 'Navigation', path: '/navigation' },
    { icon: Music, label: 'Media', path: '/media' },
    { icon: Phone, label: 'Phone', path: '/phone' },
    { icon: Settings, label: 'Settings', path: '/settings' },
  ];

  return (
    <div className="fixed bottom-0 left-0 right-0 h-20 bg-[#1a1a1a] border-t border-[#2a2a2a] flex items-center justify-between px-8">
      {/* Passenger Temperature (Left) */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => setPassengerTemp(prev => Math.max(16, prev - 0.5))}
          className="w-10 h-10 rounded-lg bg-[#2a2a2a] hover:bg-[#3a3a3a] flex items-center justify-center transition-all"
        >
          <Minus className="w-4 h-4 text-gray-300" />
        </button>
        <div className="flex flex-col items-center min-w-[70px]">
          <div className="text-2xl text-white">{passengerTemp}°</div>
          <div className="text-xs text-gray-500 uppercase">Passenger</div>
        </div>
        <button
          onClick={() => setPassengerTemp(prev => Math.min(28, prev + 0.5))}
          className="w-10 h-10 rounded-lg bg-[#2a2a2a] hover:bg-[#3a3a3a] flex items-center justify-center transition-all"
        >
          <Plus className="w-4 h-4 text-gray-300" />
        </button>
      </div>

      {/* Navigation Icons */}
      <div className="flex items-center gap-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = location.pathname === item.path;
          return (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              className={`flex flex-col items-center justify-center w-[84px] h-16 rounded-lg transition-all ${
                isActive
                  ? 'bg-[#2a2a2a]'
                  : 'hover:bg-[#222]'
              }`}
            >
              <Icon className={`w-6 h-6 mb-0.5 ${isActive ? 'text-white' : 'text-gray-500'}`} />
              <span className={`text-[10px] ${isActive ? 'text-white' : 'text-gray-500'}`}>
                {item.label}
              </span>
            </button>
          );
        })}
      </div>

      {/* Driver Temperature (Right) */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => setDriverTemp(prev => Math.max(16, prev - 0.5))}
          className="w-10 h-10 rounded-lg bg-[#2a2a2a] hover:bg-[#3a3a3a] flex items-center justify-center transition-all"
        >
          <Minus className="w-4 h-4 text-gray-300" />
        </button>
        <div className="flex flex-col items-center min-w-[70px]">
          <div className="text-2xl text-white">{driverTemp}°</div>
          <div className="text-xs text-gray-500 uppercase">Driver</div>
        </div>
        <button
          onClick={() => setDriverTemp(prev => Math.min(28, prev + 0.5))}
          className="w-10 h-10 rounded-lg bg-[#2a2a2a] hover:bg-[#3a3a3a] flex items-center justify-center transition-all"
        >
          <Plus className="w-4 h-4 text-gray-300" />
        </button>
      </div>
    </div>
  );
}
