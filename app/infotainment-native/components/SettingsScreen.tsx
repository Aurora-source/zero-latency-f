import React, { useState } from 'react';
import { View, Text, TouchableOpacity, ScrollView } from 'react-native';
import { Monitor, Volume2, Wifi, Shield, Settings as SettingsIcon } from 'lucide-react-native';
import Svg, { Path, Ellipse, Circle, Text as SvgText } from 'react-native-svg';

export default function SettingsScreen() {
  const [activeSection, setActiveSection] = useState('driver-assistance');
  const [laneKeep, setLaneKeep] = useState(true);
  const [blindSpot, setBlindSpot] = useState(true);
  const [speedLimit, setSpeedLimit] = useState(false);

  const menuItems = [
    { id: 'display', icon: Monitor, label: 'Display' },
    { id: 'sound', icon: Volume2, label: 'Sound' },
    { id: 'connectivity', icon: Wifi, label: 'Connectivity' },
    { id: 'driver-assistance', icon: Shield, label: 'Driver Assistance' },
    { id: 'system', icon: SettingsIcon, label: 'System' },
  ];

  const ToggleSwitch = ({ enabled, onToggle }: any) => (
    <TouchableOpacity onPress={onToggle} className={`w-16 h-8 rounded-full justify-center px-1 ${enabled ? 'bg-blue-500' : 'bg-[#2a2a2a]'}`}>
      <View className={`w-6 h-6 bg-white rounded-full ${enabled ? 'self-end' : 'self-start'}`} />
    </TouchableOpacity>
  );

  const renderContent = () => {
    switch (activeSection) {
      case 'driver-assistance':
        return (
          <>
            <Text className="text-xl text-white mb-6 pr-2">Driver Assistance</Text>

            <View className="mb-12">
              <View className="flex-row items-center justify-between p-5 bg-[#0a0a0a] rounded-lg mb-4">
                <View className="flex-1 pr-4">
                  <Text className="text-white mb-1 pr-2">Lane Keep Assist</Text>
                  <Text className="text-sm text-gray-500 pr-2">Helps keep your vehicle centered</Text>
                </View>
                <ToggleSwitch enabled={laneKeep} onToggle={() => setLaneKeep(!laneKeep)} />
              </View>

              <View className="flex-row items-center justify-between p-5 bg-[#0a0a0a] rounded-lg mb-4">
                <View className="flex-1 pr-4">
                  <Text className="text-white mb-1 pr-2">Blind Spot Monitoring</Text>
                  <Text className="text-sm text-gray-500 pr-2">Alerts when vehicles are in blind spot</Text>
                </View>
                <ToggleSwitch enabled={blindSpot} onToggle={() => setBlindSpot(!blindSpot)} />
              </View>

              <View className="flex-row items-center justify-between p-5 bg-[#0a0a0a] rounded-lg">
                <View className="flex-1 pr-4">
                  <Text className="text-white mb-1 pr-2">Speed Limit Warning</Text>
                  <Text className="text-sm text-gray-500 pr-2">Notifies when exceeding limit</Text>
                </View>
                <ToggleSwitch enabled={speedLimit} onToggle={() => setSpeedLimit(!speedLimit)} />
              </View>
            </View>

            {/* 3D Car Graphic */}
            <View className="bg-[#0a0a0a] rounded-xl p-8 border border-[#2a2a2a] items-center mb-8">
              <Text className="text-white mb-6 pr-2">Active Safety Features</Text>
              <View className="h-64 w-full items-center justify-center">
                <Svg viewBox="0 0 600 300" width="100%" height="100%">
                  <Path d="M 150,150 L 150,120 L 200,90 L 400,90 L 450,120 L 450,150 L 420,200 L 180,200 Z" fill="none" stroke="#3a3a3a" strokeWidth="3" />
                  {laneKeep && (
                    <>
                      <Path d="M 100,250 Q 150,200 200,180" stroke="#3b82f6" strokeWidth="2" strokeDasharray="5,5" />
                      <Path d="M 500,250 Q 450,200 400,180" stroke="#3b82f6" strokeWidth="2" strokeDasharray="5,5" />
                    </>
                  )}
                  {blindSpot && (
                    <>
                      <Ellipse cx="120" cy="150" rx="35" ry="70" fill="#3b82f6" opacity="0.2" />
                      <Ellipse cx="480" cy="150" rx="35" ry="70" fill="#3b82f6" opacity="0.2" />
                    </>
                  )}
                  {speedLimit && (
                    <>
                      <Circle cx="300" cy="50" r="20" fill="none" stroke="#ef4444" strokeWidth="3" />
                      <SvgText x="300" y="56" textAnchor="middle" fill="#ef4444" fontSize="16">100</SvgText>
                    </>
                  )}
                </Svg>
              </View>
            </View>
          </>
        );
      case 'display': return <Text className="text-xl text-white pr-2">Display Settings</Text>;
      case 'sound': return <Text className="text-xl text-white pr-2">Sound Settings</Text>;
      case 'connectivity': return <Text className="text-xl text-white pr-2">Connectivity Settings</Text>;
      case 'system': return <Text className="text-xl text-white pr-2">System Info</Text>;
      default: return null;
    }
  };

  return (
    <View className="flex-1 bg-[#0a0a0a] flex-row p-8 gap-6">
      {/* Sidebar */}
      <View className="w-72 bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] p-4">
        <Text className="text-lg text-white mb-4 pr-2">Settings</Text>
        {menuItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeSection === item.id;
          return (
            <TouchableOpacity 
              key={item.id} 
              onPress={() => setActiveSection(item.id)} 
              className={`flex-row items-center gap-3 p-3 rounded-lg mb-1 ${isActive ? 'bg-[#2a2a2a]' : ''}`}
            >
              <Icon size={20} color={isActive ? '#fff' : '#9ca3af'} />
              {/* Added flex-1 and pr-2 right here to fix Android letter chopping */}
              <Text className={`text-sm ${isActive ? 'text-white' : 'text-gray-400'} flex-1 pr-2`}>
                {item.label}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>

      {/* Main Panel wrapped in ScrollView! */}
      <View className="flex-1 bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] overflow-hidden">
        <ScrollView className="flex-1 p-8" showsVerticalScrollIndicator={false}>
          {renderContent()}
        </ScrollView>
      </View>
    </View>
  );
}