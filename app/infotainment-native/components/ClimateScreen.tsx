import React, { useState } from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { Wind, Snowflake, Fan, Flame, ArrowUp, ArrowDown } from 'lucide-react-native';
import Svg, { Path, Line, Rect, Defs, Marker, Polygon } from 'react-native-svg';

export default function ClimateScreen() {
  const [driverTemp, setDriverTemp] = useState(21);
  const [passengerTemp, setPassengerTemp] = useState(21);
  const [acOn, setAcOn] = useState(true);
  const [defrost, setDefrost] = useState(false);
  const [recirculate, setRecirculate] = useState(false);
  const [seatHeat, setSeatHeat] = useState(1);

  const TempControl = ({ temp, setTemp, label }: any) => (
    <View className="items-center">
      <Text className="text-xs text-gray-500 uppercase mb-3">{label}</Text>
      <TouchableOpacity onPress={() => setTemp(Math.min(28, temp + 0.5))} className="w-12 h-12 rounded-lg bg-[#2a2a2a] items-center justify-center mb-2">
        <ArrowUp size={20} color="#d1d5db" />
      </TouchableOpacity>
      <Text className="text-6xl text-white my-4">{temp}°</Text>
      <TouchableOpacity onPress={() => setTemp(Math.max(16, temp - 0.5))} className="w-12 h-12 rounded-lg bg-[#2a2a2a] items-center justify-center mt-2">
        <ArrowDown size={20} color="#d1d5db" />
      </TouchableOpacity>
    </View>
  );

  return (
    <View className="flex-1 bg-[#0a0a0a] p-8">
      <View className="flex-row items-center justify-center gap-24 mb-12">
        <TempControl temp={passengerTemp} setTemp={setPassengerTemp} label="Passenger" />

        {/* Car Diagram using React Native SVG */}
        <View className="w-96 h-64 relative items-center justify-center">
          <Svg viewBox="0 0 400 300" width="100%" height="100%">
            <Defs>
              <Marker id="arrowhead" markerWidth="10" markerHeight="10" refX="5" refY="5" orient="auto">
                <Polygon points="0,0 10,5 0,10" fill="#3b82f6" />
              </Marker>
            </Defs>
            <Path d="M 80,150 L 80,100 L 120,80 L 280,80 L 320,100 L 320,150 L 280,200 L 120,200 Z" fill="none" stroke="#3a3a3a" strokeWidth="2" />
            <Line x1="120" y1="80" x2="280" y2="80" stroke="#3a3a3a" strokeWidth="3" />
            <Rect x="140" y="140" width="40" height="40" fill="none" stroke="#4a4a4a" strokeWidth="2" rx="4" />
            <Rect x="220" y="140" width="40" height="40" fill="none" stroke="#4a4a4a" strokeWidth="2" rx="4" />
            
            {acOn && (
              <>
                <Path d="M 200,60 L 200,80" stroke="#3b82f6" strokeWidth="2" markerEnd="url(#arrowhead)" />
                <Path d="M 160,150 L 160,130" stroke="#3b82f6" strokeWidth="2" markerEnd="url(#arrowhead)" />
                <Path d="M 240,150 L 240,130" stroke="#3b82f6" strokeWidth="2" markerEnd="url(#arrowhead)" />
              </>
            )}
          </Svg>
          <View className="absolute inset-0 items-center justify-center">
            <Text className="text-lg text-white">{acOn ? 'Climate Active' : 'Climate Off'}</Text>
            <Text className="text-sm text-gray-500">Auto Mode</Text>
          </View>
        </View>

        <TempControl temp={driverTemp} setTemp={setDriverTemp} label="Driver" />
      </View>

      <View className="flex-row items-center justify-center gap-6 mb-8">
        <TouchableOpacity onPress={() => setAcOn(!acOn)} className={`w-32 h-32 rounded-xl items-center justify-center border border-[#2a2a2a] ${acOn ? 'bg-blue-500' : 'bg-[#1a1a1a]'}`}>
          <Snowflake size={32} color={acOn ? '#000' : '#9ca3af'} className="mb-2" />
          <Text className={`text-sm ${acOn ? 'text-black font-bold' : 'text-gray-400'}`}>A/C</Text>
        </TouchableOpacity>
        
        <TouchableOpacity onPress={() => setDefrost(!defrost)} className={`w-32 h-32 rounded-xl items-center justify-center border border-[#2a2a2a] ${defrost ? 'bg-[#2a2a2a]' : 'bg-[#1a1a1a]'}`}>
          <Wind size={32} color={defrost ? '#fff' : '#9ca3af'} className="mb-2" />
          <Text className={`text-sm ${defrost ? 'text-white font-bold' : 'text-gray-400'}`}>Defrost</Text>
        </TouchableOpacity>

        <TouchableOpacity onPress={() => setRecirculate(!recirculate)} className={`w-32 h-32 rounded-xl items-center justify-center border border-[#2a2a2a] ${recirculate ? 'bg-[#2a2a2a]' : 'bg-[#1a1a1a]'}`}>
          <Fan size={32} color={recirculate ? '#fff' : '#9ca3af'} className="mb-2" />
          <Text className={`text-sm ${recirculate ? 'text-white font-bold' : 'text-gray-400'}`}>Recirc</Text>
        </TouchableOpacity>

        <TouchableOpacity onPress={() => setSeatHeat((seatHeat + 1) % 4)} className={`w-32 h-32 rounded-xl items-center justify-center border border-[#2a2a2a] ${seatHeat > 0 ? 'bg-[#2a2a2a]' : 'bg-[#1a1a1a]'}`}>
          <Flame size={32} color={seatHeat > 0 ? '#fff' : '#9ca3af'} className="mb-2" />
          <Text className={`text-sm ${seatHeat > 0 ? 'text-white font-bold' : 'text-gray-400'}`}>Seat {seatHeat > 0 ? seatHeat : 'Off'}</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}