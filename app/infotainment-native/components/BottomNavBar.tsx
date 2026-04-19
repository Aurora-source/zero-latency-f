import React, { useState } from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { Home, Navigation, Music, Phone, Settings, Minus, Plus } from 'lucide-react-native';

export default function BottomNavBar({ 
  currentRoute, 
  onNavigate 
}: { 
  currentRoute: string; 
  onNavigate: (route: string) => void;
}) {
  const [driverTemp, setDriverTemp] = useState(21);
  const [passengerTemp, setPassengerTemp] = useState(21);

  const navItems = [
    { icon: Home, label: 'Home', path: '/' },
    { icon: Navigation, label: 'Navigation ', path: '/navigation' },
    { icon: Music, label: 'Media', path: '/media' },
    { icon: Phone, label: 'Phone', path: '/phone' },
    { icon: Settings, label: 'Settings ', path: '/settings' },
  ];

  return (
    <View className="absolute bottom-0 left-0 right-0 h-20 bg-[#1a1a1a] border-t border-[#2a2a2a] flex-row items-center justify-between px-8">
      
      {/* Passenger Temperature (Left) */}
      <View className="flex-row items-center gap-3">
        <TouchableOpacity
          onPress={() => setPassengerTemp(prev => Math.max(16, prev - 1.0))}
          className="w-10 h-10 rounded-lg bg-[#2a2a2a] items-center justify-center"
        >
          <Minus size={16} color="#d1d5db" />
        </TouchableOpacity>
        <View className="items-center w-[70px]">
          <Text className="text-2xl text-white">{passengerTemp}°C </Text>
          <Text className="text-[10px] text-gray-500 uppercase">Passenger </Text>
        </View>
        <TouchableOpacity
          onPress={() => setPassengerTemp(prev => Math.min(28, prev + 1.0))}
          className="w-10 h-10 rounded-lg bg-[#2a2a2a] items-center justify-center"
        >
          <Plus size={16} color="#d1d5db" />
        </TouchableOpacity>
      </View>

      {/* Navigation Icons */}
      <View className="flex-row items-center gap-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = currentRoute === item.path;
          return (
            <TouchableOpacity
              key={item.path}
              onPress={() => onNavigate(item.path)}
              className={`items-center justify-center w-[84px] h-16 rounded-lg ${
                isActive ? 'bg-[#2a2a2a]' : ''
              }`}
            >
              <Icon size={24} color={isActive ? '#ffffff' : '#6b7280'} className="mb-1" />
              <Text className={`text-[10px] ${isActive ? 'text-white' : 'text-gray-500'}`}>
                {item.label}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>

      {/* Driver Temperature (Right) */}
      <View className="flex-row items-center gap-3">
        <TouchableOpacity
          onPress={() => setDriverTemp(prev => Math.max(16, prev - 1.0))}
          className="w-10 h-10 rounded-lg bg-[#2a2a2a] items-center justify-center"
        >
          <Minus size={16} color="#d1d5db" />
        </TouchableOpacity>
        <View className="items-center w-[70px]">
          <Text className="text-2xl text-white">{driverTemp}°C </Text>
          <Text className="text-[10px] text-gray-500 uppercase">Driver </Text>
        </View>
        <TouchableOpacity
          onPress={() => setDriverTemp(prev => Math.min(28, prev + 1.0))}
          className="w-10 h-10 rounded-lg bg-[#2a2a2a] items-center justify-center"
        >
          <Plus size={16} color="#d1d5db" />
        </TouchableOpacity>
      </View>
    </View>
  );
}