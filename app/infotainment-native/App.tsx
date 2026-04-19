import React, { useState } from 'react';
import { View, StatusBar } from 'react-native';
import BottomNavBar from './components/BottomNavBar';
import DashboardScreen from './components/DashboardScreen';
import NavigationScreen from './components/NavigationScreen';
import MediaScreen from './components/MediaScreen';
import PhoneScreen from './components/PhoneScreen';
import SettingsScreen from './components/SettingsScreen';
import ClimateScreen from './components/ClimateScreen';

export default function App() {
  const [currentRoute, setCurrentRoute] = useState('/');

  const renderScreen = () => {
    switch (currentRoute) {
      case '/': return <DashboardScreen />;
      case '/navigation': return <NavigationScreen />;
      case '/media': return <MediaScreen />;
      case '/phone': return <PhoneScreen />;
      case '/settings': return <SettingsScreen />;
      case '/climate': return <ClimateScreen />;
      default: return <DashboardScreen />;
    }
  };

  return (
    <View className="flex-1 bg-black">
      {/* Hides the tablet status bar for kiosk mode */}
      <StatusBar hidden /> 
      
      {/* Main Screen Content (leaves room for the 80px bottom bar) */}
      <View className="flex-1 pb-20">
        {renderScreen()}
      </View>

      {/* Persistent Bottom Bar */}
      <BottomNavBar 
        currentRoute={currentRoute} 
        onNavigate={setCurrentRoute} 
      />
    </View>
  );
}