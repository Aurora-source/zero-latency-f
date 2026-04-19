import { BrowserRouter, Routes, Route } from 'react-router';
import { BottomNavBar } from './components/BottomNavBar';
import { DashboardScreen } from './components/DashboardScreen';
import { NavigationScreen } from './components/NavigationScreen';
import { MediaScreen } from './components/MediaScreen';
import { PhoneScreen } from './components/PhoneScreen';
import { SettingsScreen } from './components/SettingsScreen';
import { ClimateScreen } from './components/ClimateScreen';

export default function App() {
  return (
    <BrowserRouter>
      <div className="w-[1920px] h-[720px] bg-black text-white overflow-hidden dark">
        <Routes>
          <Route path="/" element={<DashboardScreen />} />
          <Route path="/navigation" element={<NavigationScreen />} />
          <Route path="/media" element={<MediaScreen />} />
          <Route path="/phone" element={<PhoneScreen />} />
          <Route path="/settings" element={<SettingsScreen />} />
          <Route path="/climate" element={<ClimateScreen />} />
        </Routes>
        <BottomNavBar />
      </div>
    </BrowserRouter>
  );
}