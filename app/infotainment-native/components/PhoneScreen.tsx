import React from 'react';
import { View, Text, TouchableOpacity, ScrollView } from 'react-native';
import { Phone, PhoneCall, PhoneMissed, PhoneIncoming } from 'lucide-react-native';

export default function PhoneScreen() {
  const recentCalls = [
    { name: 'Sarah Johnson', type: 'outgoing', time: '10 min ago', avatar: 'SJ' },
    { name: 'Mike Chen', type: 'incoming', time: '1 hour ago', avatar: 'MC' },
    { name: 'Emily Davis', type: 'missed', time: '2 hours ago', avatar: 'ED' },
    { name: 'Alex Turner', type: 'incoming', time: '3 hours ago', avatar: 'AT' },
  ];

  const favorites = [
    { name: 'Home', avatar: 'H' },
    { name: 'Office', avatar: 'O' },
    { name: 'Mom', avatar: 'M' },
    { name: 'Dad', avatar: 'D' },
  ];

  const getCallIcon = (type: string) => {
    switch (type) {
      case 'outgoing': return <PhoneCall size={16} color="#3b82f6" />;
      case 'incoming': return <PhoneIncoming size={16} color="#22c55e" />;
      case 'missed': return <PhoneMissed size={16} color="#ef4444" />;
      default: return <Phone size={16} color="#fff" />;
    }
  };

  return (
    <View className="flex-1 bg-[#0a0a0a] flex-row p-8 gap-6">
      {/* Favorites */}
      <View className="w-80 bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] p-6">
        <Text className="text-lg text-white mb-4">Favorites</Text>
        <View className="flex-row flex-wrap justify-between gap-y-3">
          {favorites.map((contact, i) => (
            <TouchableOpacity key={i} className="w-[48%] bg-[#0a0a0a] rounded-lg p-5 items-center gap-3">
              <View className="w-16 h-16 bg-[#2a2a2a] rounded-full items-center justify-center">
                <Text className="text-xl text-white">{contact.avatar}</Text>
              </View>
              <Text className="text-sm text-white">{contact.name}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      {/* Recent Calls */}
      <View className="flex-1 bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] p-8">
        <View className="flex-row items-center justify-between mb-6">
          <Text className="text-xl text-white">Recent Calls</Text>
          <TouchableOpacity className="w-14 h-14 bg-green-500 rounded-full items-center justify-center">
            <Phone size={24} color="#000" fill="#000" />
          </TouchableOpacity>
        </View>

        <ScrollView className="space-y-2">
          {recentCalls.map((call, i) => (
            <TouchableOpacity key={i} className="bg-[#0a0a0a] rounded-lg p-5 mb-2 flex-row items-center gap-5">
              <View className="w-12 h-12 bg-[#2a2a2a] rounded-full items-center justify-center">
                <Text className="text-sm text-white">{call.avatar}</Text>
              </View>
              <View className="flex-1">
                <Text className="text-white mb-1">{call.name}</Text>
                <Text className="text-xs text-gray-500">{call.time}</Text>
              </View>
              <View className="flex-row items-center gap-4">
                {getCallIcon(call.type)}
                <View className="w-10 h-10 bg-[#2a2a2a] rounded-full items-center justify-center">
                  <Phone size={16} color="#22c55e" fill="#22c55e" />
                </View>
              </View>
            </TouchableOpacity>
          ))}
        </ScrollView>
      </View>
    </View>
  );
}