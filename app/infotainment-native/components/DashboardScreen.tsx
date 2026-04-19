import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { Battery, Zap, Navigation, Wind, Plus, Minus, Gauge } from 'lucide-react-native';
import { LinearGradient } from 'expo-linear-gradient';

export default function DashboardScreen() {
  const [currentTime, setCurrentTime] = useState(new Date());
  const [isAcOn, setIsAcOn] = useState(true);
  const [cruiseControl, setCruiseControl] = useState(false); 
  const [cruiseSpeed, setCruiseSpeed] = useState(65);

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const increaseSpeed = () => setCruiseSpeed(prev => Math.min(prev + 5, 150));
  const decreaseSpeed = () => setCruiseSpeed(prev => Math.max(prev - 5, 30));

  return (
    <View className="flex-1 bg-[#0a0a0a]">
      {/* Background Map Simulation */}
      <LinearGradient colors={['#1a1a1a', '#0a0a0a']} className="absolute inset-0">
        <View className="absolute inset-0 opacity-10">
          <View className="absolute top-1/3 left-0 right-0 h-[1px] bg-gray-600" />
          <View className="absolute top-2/3 left-0 right-0 h-[1px] bg-gray-600" />
          <View className="absolute top-0 bottom-0 left-1/3 w-[1px] bg-gray-600" />
          <View className="absolute top-0 bottom-0 right-1/3 w-[1px] bg-gray-600" />
        </View>
        <View className="absolute top-1/2 left-1/2 w-2 h-2 bg-blue-500 rounded-full" />
      </LinearGradient>

      {/* FIXED: Added top-10 spacing for the Clock & Date */}
      <View className="absolute top-10 left-0 right-0 items-center z-20">
        <Text className="text-6xl text-white font-extralight tracking-tighter">
          {currentTime.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })}
        </Text>
        <Text className="text-sm text-blue-500 font-bold uppercase tracking-[4px] mt-1">
          {currentTime.toLocaleDateString('en-US', { 
            weekday: 'short', 
            month: 'short', 
            day: 'numeric' 
          }).toUpperCase().replace(',', '')} 
        </Text>
      </View>

      {/* Top Status Bar Placeholder */}
      <View className="p-6 flex-row items-center justify-between z-10">
        <View className="flex-row items-center gap-8">
          <View className="w-10 h-10" />
        </View>
      </View>

      {/* Main Content Grid */}
      <View className="flex-row px-6 pb-6 gap-4 mt-16 z-10">
        
        {/* COLUMN 1: Trip & TPMS */}
        <View className="flex-1 gap-4">
          <View className="bg-[#1a1a1a]/90 rounded-xl p-6 border border-[#2a2a2a]">
            <Text className="text-xs text-gray-500 uppercase mb-4 pr-1">Trip A </Text>
            <View className="flex-row justify-between items-center mb-3">
              <Text className="text-sm text-gray-400 pr-1">Distance </Text>
              <Text className="text-xl text-white pr-1">248 km </Text>
            </View>
            <View className="flex-row justify-between items-center mb-3">
              <Text className="text-sm text-gray-400 pr-1">Duration </Text>
              <Text className="text-xl text-white pr-1">3h 24m </Text>
            </View>
            <View className="flex-row justify-between items-center">
              <Text className="text-sm text-gray-400 pr-1">Average Speed </Text>
              <Text className="text-xl text-white pr-1">73 km/h </Text>
            </View>
          </View>

          <View className="bg-[#1a1a1a]/90 rounded-xl p-6 border border-[#2a2a2a]">
            <View className="flex-row items-center gap-2 mb-4">
              <Gauge size={16} color="#9ca3af" />
              <Text className="text-xs text-gray-500 uppercase pr-1">Tire Pressure PSI </Text>
            </View>
            <View className="flex-row justify-between mb-3">
              <View>
                <Text className="text-gray-400 text-xs pr-1">FL </Text>
                <Text className="text-white text-xl pr-1">35 </Text>
              </View>
              <View className="items-end">
                <Text className="text-gray-400 text-xs pr-1">FR </Text>
                <Text className="text-white text-xl pr-1">35 </Text>
              </View>
            </View>
            <View className="flex-row justify-between">
              <View>
                <Text className="text-gray-400 text-xs pr-1">RL </Text>
                <Text className="text-white text-xl pr-1">34 </Text>
              </View>
              <View className="items-end">
                <Text className="text-gray-400 text-xs pr-1">RR </Text>
                <Text className="text-white text-xl pr-1">36 </Text>
              </View>
            </View>
          </View>
        </View>

        {/* COLUMN 2: Battery */}

        <View className="flex-1">

          <View className="flex-1 bg-[#1a1a1a]/90 rounded-xl p-6 border border-[#2a2a2a]">

            <Text className="text-xs text-gray-500 uppercase mb-4 pr-1">Battery </Text>

            <View className="flex-row items-center gap-4 mb-4">

              <Battery size={40} color="#22c55e" />

              <View>

                <Text className="text-4xl text-white pr-1">87% </Text>

                <Text className="text-sm text-gray-400 pr-1">462 km range </Text>

              </View>

            </View>

            <View className="w-full h-2 bg-[#2a2a2a] rounded-full overflow-hidden">

              <View className="h-full w-[87%] bg-green-500 rounded-full" />

            </View>

            <View className="flex-row items-center gap-2 mt-3">

              <Zap size={16} color="#6b7280" />

              <Text className="text-xs text-gray-500 pr-1">12 kW consumption </Text>

            </View>

          </View>

        </View>

        {/* COLUMN 3: Climate, Cruise & Stepper */}
        <View className="flex-1 gap-4">
          <View className="bg-[#1a1a1a]/90 rounded-xl p-6 border border-[#2a2a2a]">
            <Text className="text-xs text-gray-500 uppercase mb-4 pr-1">Climate </Text>
            <View className="flex-row items-center justify-between mb-4">
              <View className="flex-row items-center gap-3">
                <Wind size={24} color={isAcOn ? "#60a5fa" : "#6b7280"} />
                <Text className="text-sm text-gray-400 pr-1">A/C </Text>
              </View>
              <TouchableOpacity onPress={() => setIsAcOn(!isAcOn)} className={`w-14 h-7 rounded-full justify-center px-1 ${isAcOn ? 'bg-blue-500' : 'bg-[#2a2a2a]'}`}>
                <View className={`w-5 h-5 bg-white rounded-full ${isAcOn ? 'self-end' : 'self-start'}`} />
              </TouchableOpacity>
            </View>
            <View className="flex-row justify-between items-center mb-4">
              <Text className="text-sm text-gray-400 pr-1">Inside </Text>
              <Text className="text-2xl text-white pr-1">21°C </Text>
            </View>
            <View className="flex-row justify-between items-center">
              <Text className="text-sm text-gray-400 pr-1">Outside </Text>
              <Text className="text-2xl text-white pr-1">28°C </Text>
            </View>
          </View>

          <TouchableOpacity 
            onPress={() => setCruiseControl(!cruiseControl)}
            className={`flex-row items-center justify-between p-4 rounded-xl border ${cruiseControl ? 'bg-blue-900/20 border-blue-500/50' : 'bg-[#1a1a1a]/90 border-[#2a2a2a]'}`}
          >
            <View className="flex-row items-center gap-3">
              <Navigation size={24} color={cruiseControl ? "#3b82f6" : "#9ca3af"} />
              <Text className={`text-base pr-1 ${cruiseControl ? 'text-blue-400' : 'text-gray-400'}`}>Cruise Control </Text>
            </View>
            <Text className={`text-xl pr-1 ${cruiseControl ? 'text-blue-400' : 'text-white'}`}>
              {cruiseControl ? 'Active ' : 'Off '} 
            </Text>
          </TouchableOpacity>

          {/* Stepper Component */}
          <View 
            className={`flex-1 bg-[#1a1a1a]/90 rounded-xl border border-[#2a2a2a] py-4 px-2 justify-evenly ${cruiseControl ? 'opacity-100' : 'opacity-30'}`} 
            pointerEvents={cruiseControl ? 'auto' : 'none'}
          >
            <Text className="text-xs text-gray-500 uppercase text-center pr-1">Set Limit</Text>
            
            <View className="flex-row items-center justify-between px-2">
              <TouchableOpacity 
                onPress={decreaseSpeed}
                className="w-12 h-12 bg-[#2a2a2a] rounded-full items-center justify-center border border-[#3a3a3a]"
                activeOpacity={0.7}
              >
                <Minus size={24} color="#9ca3af" />
              </TouchableOpacity>

              <View className="flex-row items-baseline justify-center flex-1 px-2">
                <Text className="text-4xl text-gray-400 font-light pr-1">{cruiseSpeed}</Text>
                <Text className="text-sm text-blue-500 font-medium pr-1">km/h</Text>
              </View>

              <TouchableOpacity 
                onPress={increaseSpeed}
                className="w-12 h-12 bg-[#2a2a2a] rounded-full items-center justify-center border border-[#3a3a3a]"
                activeOpacity={0.7}
              >
                <Plus size={24} color="#9ca3af" />
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </View>

      {/* Quick Actions Footer */}
      <View className="absolute bottom-6 left-6 right-6 flex-row gap-3 z-10">
        {['Charge Port', 'Trunk', 'Locks', 'Sentry Mode'].map((lbl) => (
          <TouchableOpacity key={lbl} className="flex-1 bg-[#1a1a1a]/90 py-4 rounded-xl border border-[#2a2a2a] items-center">
            <Text className="text-sm text-white pr-1">{lbl} </Text>
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}