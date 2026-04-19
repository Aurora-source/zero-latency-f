import React from 'react';
import { View, Text, TouchableOpacity, ScrollView } from 'react-native';
import { Play, Pause, SkipForward, SkipBack, Shuffle, Repeat } from 'lucide-react-native';

export default function MediaScreen() {
  const upNext = [
    { title: 'Electric Dreams', artist: 'Midnight Radio', duration: '4:23' },
    { title: 'Sunset Drive', artist: 'Highway FM', duration: '3:54' },
    { title: 'City Lights', artist: 'Urban Beats', duration: '5:12' },
    { title: 'Night Cruise', artist: 'Drive FM', duration: '4:45' },
    { title: 'Summer Roads', artist: 'Coast Radio', duration: '3:38' },
  ];

  return (
    <View className="flex-1 bg-[#0a0a0a] flex-row p-8 gap-8">
      {/* Album Art */}
      <View className="w-80 justify-center">
        <View className="aspect-square bg-gray-800 rounded-lg border border-[#2a2a2a] items-center justify-center">
          <Text className="text-white/10 text-8xl">♪</Text>
        </View>
      </View>

      {/* Controls */}
      <View className="flex-1 justify-center px-8">
        <View className="mb-8">
          <Text className="text-4xl text-white mb-2">Highway Nights</Text>
          <Text className="text-xl text-gray-400">Midnight Radio</Text>
        </View>

        <View className="mb-8">
          <View className="h-1 bg-[#2a2a2a] rounded-full overflow-hidden mb-2">
            <View className="h-full w-3/5 bg-white rounded-full" />
          </View>
          <View className="flex-row justify-between">
            <Text className="text-xs text-gray-500">2:34</Text>
            <Text className="text-xs text-gray-500">4:12</Text>
          </View>
        </View>

        <View className="flex-row items-center justify-center gap-8">
          <TouchableOpacity><Shuffle size={20} color="#9ca3af" /></TouchableOpacity>
          <TouchableOpacity><SkipBack size={28} color="#fff" /></TouchableOpacity>
          <TouchableOpacity className="w-16 h-16 rounded-full bg-white items-center justify-center">
            <Pause size={32} color="#000" fill="#000" />
          </TouchableOpacity>
          <TouchableOpacity><SkipForward size={28} color="#fff" /></TouchableOpacity>
          <TouchableOpacity><Repeat size={20} color="#9ca3af" /></TouchableOpacity>
        </View>
      </View>

      {/* Queue */}
      <View className="w-96 bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] p-6">
        <Text className="text-lg text-white mb-4">Up Next</Text>
        <ScrollView className="flex-1">
          {upNext.map((track, i) => (
            <TouchableOpacity key={i} className="bg-[#0a0a0a] rounded-lg p-4 mb-2 flex-row items-center gap-4">
              <View className="w-10 h-10 bg-[#2a2a2a] rounded items-center justify-center">
                <Play size={16} color="#9ca3af" fill="#9ca3af" />
              </View>
              <View className="flex-1">
                <Text className="text-white text-sm" numberOfLines={1}>{track.title}</Text>
                <Text className="text-gray-500 text-xs" numberOfLines={1}>{track.artist}</Text>
              </View>
              <Text className="text-gray-600 text-xs">{track.duration}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      </View>
    </View>
  );
}