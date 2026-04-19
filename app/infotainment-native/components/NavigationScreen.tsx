import React, { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ActivityIndicator, ScrollView, Keyboard, Animated } from 'react-native';
import { Search, Crosshair, MapPin, Clock, Play, Sun, Moon, ArrowUpLeft, X, Navigation as NavIcon, AlertTriangle, Zap, Wifi } from 'lucide-react-native';
import MapView, { Marker, Polyline } from 'react-native-maps';
import * as Location from 'expo-location';

const getDistance = (lat1: number, lon1: number, lat2: number, lon2: number) => {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
  return R * (2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
};

const getArrivalTime = (durationMinutes: string) => {
  const now = new Date();
  const duration = parseFloat(durationMinutes) || 0;
  const arrivalDate = new Date(now.getTime() + duration * 60000);
  return arrivalDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
};

const PANEL_INNER_WIDTH = 356;
const SEGMENT_WIDTH = PANEL_INNER_WIDTH / 3;

export default function NavigationScreen() {
  const [currentLocation, setCurrentLocation] = useState<any>({
    latitude: 12.9716,
    longitude: 77.5946,
    latitudeDelta: 0.05,
    longitudeDelta: 0.05,
  });

  const [userHeading, setUserHeading] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [routeOptions, setRouteOptions] = useState<any[]>([]);
  const [selectedRouteIndex, setSelectedRouteIndex] = useState<number | null>(null);
  const [isNavigating, setIsNavigating] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(true);
  const [predictions, setPredictions] = useState<any[]>([]);
  const [showPredictions, setShowPredictions] = useState(false);
  const [targetMarker, setTargetMarker] = useState<any>(null);
  const [routingMode, setRoutingMode] = useState<'Fast' | 'Balanced' | 'Connected'>('Balanced');

  const sliderAnim = useRef(new Animated.Value(1)).current;
  const mapRef = useRef<MapView>(null);
  const searchTimeout = useRef<any>(null);

  const modeIndex: Record<string, number> = { Fast: 0, Balanced: 1, Connected: 2 };

  const modeColors: Record<string, string> = {
    Fast: '#3b82f6',
    Balanced: '#8b5cf6',
    Connected: '#10b981',
  };

  const handleModeChange = (mode: 'Fast' | 'Balanced' | 'Connected') => {
    setRoutingMode(mode);
    Animated.spring(sliderAnim, {
      toValue: modeIndex[mode],
      useNativeDriver: true,
      tension: 120,
      friction: 10,
    }).start();
  };

  const pillTranslateX = sliderAnim.interpolate({
    inputRange: [0, 1, 2],
    outputRange: [0, SEGMENT_WIDTH, SEGMENT_WIDTH * 2],
  });

  useEffect(() => {
    let sub: any;
    (async () => {
      let { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') return;
      sub = await Location.watchPositionAsync(
        { accuracy: Location.Accuracy.BestForNavigation, timeInterval: 1000, distanceInterval: 1 },
        (loc) => {
          const { latitude, longitude, heading } = loc.coords;
          setCurrentLocation((prev: any) => ({ ...prev, latitude, longitude }));
          if (heading !== null) setUserHeading(heading);
        }
      );
    })();
    return () => sub?.remove();
  }, []);

  const handleTyping = (text: string) => {
    setSearchQuery(text);
    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    if (text.length < 2) { setPredictions([]); setShowPredictions(false); return; }
    searchTimeout.current = setTimeout(async () => {
      try {
        const url = `https://photon.komoot.io/api/?q=${encodeURIComponent(text)}&lat=${currentLocation?.latitude}&lon=${currentLocation?.longitude}&limit=5`;
        const res = await fetch(url);
        const data = await res.json();
        setPredictions(data.features.map((f: any) => ({
          id: f.properties.osm_id?.toString() || Math.random().toString(),
          name: f.properties.name || f.properties.street || "Place",
          address: `${f.properties.city || ''} ${f.properties.state || ''}`.trim(),
          lat: f.geometry.coordinates[1],
          lng: f.geometry.coordinates[0],
        })));
        setShowPredictions(true);
      } catch (e) { console.error("Search failed:", e); }
    }, 400);
  };

  const fetchSingleRoute = async (
    fromLat: number, fromLng: number,
    toLat: number, toLng: number,
    waypointLat?: number, waypointLng?: number
  ) => {
    try {
      let coords = `${fromLng},${fromLat};`;
      if (waypointLat !== undefined && waypointLng !== undefined) {
        coords += `${waypointLng},${waypointLat};`;
      }
      coords += `${toLng},${toLat}`;

      const url = `https://router.project-osrm.org/route/v1/driving/${coords}?overview=full&geometries=geojson&alternatives=false`;
      const res = await fetch(url, {
        headers: { 'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0' }
      });
      const text = await res.text();
      if (!text.startsWith('{')) return null;
      const data = JSON.parse(text);
      if (!data.routes?.length) return null;
      return {
        pts: data.routes[0].geometry.coordinates.map((c: any) => ({ latitude: c[1], longitude: c[0] })),
        dur: (data.routes[0].duration / 60).toFixed(1),
        dis: (data.routes[0].distance / 1000).toFixed(1),
      };
    } catch {
      return null;
    }
  };

  const calculatePath = async (target: any) => {
    setIsLoading(true);

    const fromLat = currentLocation.latitude;
    const fromLng = currentLocation.longitude;
    const toLat = target.lat;
    const toLng = target.lng;
    const midLat = (fromLat + toLat) / 2;
    const midLng = (fromLng + toLng) / 2;

    const [fastest, balanced, connected] = await Promise.all([
      fetchSingleRoute(fromLat, fromLng, toLat, toLng),
      fetchSingleRoute(fromLat, fromLng, toLat, toLng, midLat + 0.008, midLng - 0.008),
      fetchSingleRoute(fromLat, fromLng, toLat, toLng, midLat - 0.008, midLng + 0.008),
    ]);

    const fallback = (offsetLat = 0, offsetLng = 0) => {
      const d = getDistance(fromLat, fromLng, toLat, toLng);
      return {
        pts: [
          { latitude: fromLat, longitude: fromLng },
          { latitude: midLat + offsetLat, longitude: midLng + offsetLng },
          { latitude: toLat, longitude: toLng },
        ],
        dur: (d * 2.2).toFixed(1),
        dis: d.toFixed(1),
      };
    };

    const r0 = fastest   ?? fallback();
    const r1 = balanced  ?? fallback(0.003, -0.003);
    const r2 = connected ?? fallback(-0.003, 0.003);

    setRouteOptions([
      { type: "Most Connected", duration: r2.dur, distance: r2.dis, coverage: 82, color: "#10b981", points: r2.pts },
      { type: "Balanced",       duration: r1.dur, distance: r1.dis, coverage: 54, color: "#8b5cf6", points: r1.pts },
      { type: "Fastest",        duration: r0.dur, distance: r0.dis, coverage: 39, color: "#3b82f6", points: r0.pts },
    ]);
    setSelectedRouteIndex(0);
    mapRef.current?.fitToCoordinates(r0.pts, { edgePadding: { top: 150, right: 100, bottom: 320, left: 550 } });
    setIsLoading(false);
  };

  const startNav = () => {
    setIsNavigating(true);
    mapRef.current?.animateCamera({
      center: { latitude: currentLocation.latitude, longitude: currentLocation.longitude },
      pitch: 65, heading: userHeading, zoom: 18
    }, { duration: 2000 });
  };

  const cancelNav = () => {
    setIsNavigating(false);
    mapRef.current?.animateCamera({ pitch: 0, zoom: 14 }, { duration: 1000 });
  };

  const darkStyle = [
    { elementType: "geometry", stylers: [{ color: "#212121" }] },
    { featureType: "road", elementType: "geometry.fill", stylers: [{ color: "#2c2c2c" }] },
    { featureType: "water", elementType: "geometry", stylers: [{ color: "#000000" }] }
  ];

  const activeRouteColor = selectedRouteIndex !== null
    ? routeOptions[selectedRouteIndex]?.color ?? '#3b82f6'
    : '#3b82f6';

  return (
    <View className="flex-1 bg-[#0a0a0a]">
      <MapView
        ref={mapRef}
        style={StyleSheet.absoluteFillObject}
        initialRegion={currentLocation}
        customMapStyle={isDarkMode ? darkStyle : []}
        showsUserLocation={!isNavigating}
        followsUserLocation={isNavigating}
      >
        {targetMarker && <Marker coordinate={targetMarker} />}
        {isNavigating && (
          <Marker coordinate={currentLocation} flat anchor={{ x: 0.5, y: 0.5 }} rotation={userHeading}>
            <View className="bg-blue-600 p-2 rounded-full border-2 border-white shadow-lg">
              <NavIcon size={30} color="#fff" fill="#fff" />
            </View>
          </Marker>
        )}

        {/* Dimmed unselected routes */}
        {routeOptions.map((opt, idx) =>
          idx !== selectedRouteIndex ? (
            <Polyline
              key={`dim-${idx}`}
              coordinates={opt.points}
              strokeColor={opt.color + '55'}
              strokeWidth={6}
              lineCap="round"
            />
          ) : null
        )}

        {/* Selected route — shadow layer */}
        {selectedRouteIndex !== null && routeOptions[selectedRouteIndex] && (
          <Polyline
            coordinates={routeOptions[selectedRouteIndex].points}
            strokeColor="rgba(0,0,0,0.3)"
            strokeWidth={14}
            lineCap="round"
          />
        )}

        {/* Selected route — main colored line */}
        {selectedRouteIndex !== null && routeOptions[selectedRouteIndex] && (
          <Polyline
            coordinates={routeOptions[selectedRouteIndex].points}
            strokeColor={activeRouteColor}
            strokeWidth={10}
            lineCap="round"
          />
        )}

        {/* Selected route — white inner highlight */}
        {selectedRouteIndex !== null && routeOptions[selectedRouteIndex] && (
          <Polyline
            coordinates={routeOptions[selectedRouteIndex].points}
            strokeColor="rgba(255,255,255,0.35)"
            strokeWidth={3}
            lineCap="round"
          />
        )}
      </MapView>

      {!isNavigating && (
        <>
          <TouchableOpacity
            className="absolute top-8 right-8 bg-[#1a1a1a] p-4 rounded-xl border border-[#333] z-50 shadow-lg"
            onPress={() => setIsDarkMode(!isDarkMode)}
          >
            {isDarkMode ? <Sun size={24} color="#fbbf24" /> : <Moon size={24} color="#3b82f6" />}
          </TouchableOpacity>

          <View className="absolute top-8 w-full items-center z-40" pointerEvents="box-none">
            <View className="w-1/3">
              <View className="bg-[#1a1a1a] rounded-xl px-6 py-4 border border-[#333] flex-row items-center shadow-2xl">
                {isLoading ? <ActivityIndicator size="small" color="#3b82f6" /> : <Search size={24} color="#9ca3af" />}
                <TextInput
                  className="flex-1 text-white text-lg ml-4 pr-1"
                  placeholder="Where to?"
                  placeholderTextColor="#6b7280"
                  value={searchQuery}
                  onChangeText={handleTyping}
                />
                <TouchableOpacity onPress={() => mapRef.current?.animateToRegion(currentLocation)}>
                  <Crosshair size={22} color="#3b82f6" />
                </TouchableOpacity>
              </View>
              {showPredictions && predictions.length > 0 && (
                <View className="bg-[#121212] rounded-xl mt-2 border border-[#333] overflow-hidden max-h-96 shadow-2xl">
                  <ScrollView keyboardShouldPersistTaps="handled">
                    {predictions.map((p, i) => (
                      <TouchableOpacity
                        key={i}
                        className="p-6 border-b border-[#222]"
                        onPress={() => {
                          setTargetMarker({ latitude: p.lat, longitude: p.lng });
                          calculatePath(p);
                          setSearchQuery(p.name);
                          setShowPredictions(false);
                          Keyboard.dismiss();
                        }}
                      >
                        <View className="flex-row items-center">
                          <MapPin size={20} color="#3b82f6" />
                          <View className="ml-4">
                            <Text className="text-white text-lg font-medium pr-1">{p.name}</Text>
                            <Text className="text-gray-500 text-sm pr-1">{p.address}</Text>
                          </View>
                        </View>
                      </TouchableOpacity>
                    ))}
                  </ScrollView>
                </View>
              )}
            </View>
          </View>

          {routeOptions.length > 0 && (
            <View className="absolute left-6 top-[130px] bottom-[90px] w-[460px] bg-[#0d0d0d] rounded-xl border border-[#222] shadow-2xl overflow-hidden z-20">
              <View className="p-6 border-b border-[#1a1a1a]">
                <Text className="text-gray-500 text-[11px] font-black uppercase tracking-[3px]">Route Selection</Text>
              </View>
              <ScrollView className="flex-1" showsVerticalScrollIndicator={false} contentContainerStyle={{ padding: 20 }}>
                {routeOptions.map((opt, idx) => (
                  <TouchableOpacity
                    key={idx}
                    onPress={() => {
                      setSelectedRouteIndex(idx);
                      mapRef.current?.fitToCoordinates(opt.points, { edgePadding: { top: 150, right: 100, bottom: 320, left: 550 } });
                    }}
                    style={{
                      padding: 24,
                      borderRadius: 12,
                      marginBottom: 16,
                      borderWidth: 2,
                      borderColor: selectedRouteIndex === idx ? opt.color : 'transparent',
                      backgroundColor: selectedRouteIndex === idx ? '#1a1a1a' : '#141414',
                    }}
                  >
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                      <View style={{ width: 12, height: 12, borderRadius: 2, backgroundColor: opt.color }} />
                      <Text style={{ color: '#fff', fontSize: 18, fontWeight: '700' }}>{opt.type}</Text>
                    </View>
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 16 }}>
                      <Clock size={18} color="#9ca3af" />
                      <Text style={{ color: '#9ca3af', fontSize: 16 }}>{opt.duration} min | {opt.distance} km</Text>
                    </View>
                    {opt.type !== "Fastest" && (
                      <View style={{ marginBottom: 16 }}>
                        <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 8 }}>
                          <Text style={{ color: '#6b7280', fontSize: 14 }}>Coverage</Text>
                          <Text style={{ color: '#fff', fontSize: 14, fontWeight: '700' }}>{opt.coverage}%</Text>
                        </View>
                        <View style={{ height: 6, backgroundColor: '#262626', borderRadius: 4, overflow: 'hidden' }}>
                          <View style={{ width: `${opt.coverage}%`, height: '100%', backgroundColor: opt.color, borderRadius: 4 }} />
                        </View>
                      </View>
                    )}
                    {selectedRouteIndex === idx && (
                      <TouchableOpacity
                        onPress={startNav}
                        style={{
                          backgroundColor: opt.color,
                          paddingVertical: 16,
                          borderRadius: 10,
                          flexDirection: 'row',
                          alignItems: 'center',
                          justifyContent: 'center',
                          marginTop: 12,
                        }}
                      >
                        <Play size={22} color="#fff" fill="#fff" />
                        <Text style={{ color: '#fff', fontSize: 18, fontWeight: '900', marginLeft: 10, textTransform: 'uppercase' }}>Start Trip</Text>
                      </TouchableOpacity>
                    )}
                  </TouchableOpacity>
                ))}
              </ScrollView>
              {selectedRouteIndex === 2 && (
                <View className="bg-amber-950/40 border-t border-amber-500/30 p-5 flex-row items-center">
                  <AlertTriangle size={20} color="#f59e0b" />
                  <Text className="text-amber-500/90 text-sm font-bold ml-4 pr-1">Warning: Low Connectivity Areas enroute</Text>
                </View>
              )}
            </View>
          )}
        </>
      )}

      {isNavigating && (
        <>
          <View className="absolute top-10 left-10 right-10 flex-row justify-between z-50" pointerEvents="box-none">
            <View style={{ backgroundColor: activeRouteColor, padding: 24, borderRadius: 12, flexDirection: 'row', alignItems: 'center', width: 450 }}>
              <View style={{ backgroundColor: 'rgba(255,255,255,0.2)', padding: 16, borderRadius: 8, marginRight: 24 }}>
                <ArrowUpLeft size={45} color="#fff" />
              </View>
              <View>
                <Text style={{ color: '#fff', fontSize: 36, fontWeight: '900' }}>450 m</Text>
                <Text style={{ color: 'rgba(255,255,255,0.8)', fontSize: 18, fontWeight: '500' }}>Turn left onto MG Road</Text>
              </View>
            </View>
            <TouchableOpacity onPress={cancelNav} className="bg-[#1a1a1a] p-5 rounded-xl border border-[#333] shadow-lg">
              <X size={35} color="#ef4444" />
            </TouchableOpacity>
          </View>

          {/* ROUTING PRIORITY PANEL */}
          <View style={{
            position: 'absolute',
            left: 40,
            top: '28%',
            width: 420,
            backgroundColor: 'rgba(26,26,26,0.95)',
            borderRadius: 30,
            padding: 32,
            borderWidth: 1,
            borderColor: '#333',
            zIndex: 50,
          }}>
            <Text style={{ color: '#fff', fontSize: 22, fontWeight: '700', marginBottom: 24 }}>
              Routing Priority
            </Text>

            {/* Labels row — absolute pinned to edges */}
            <View style={{ height: 24, marginBottom: 16, position: 'relative' }}>
              <View style={{ position: 'absolute', left: 0, flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <Zap size={16} color="#60a5fa" />
                <Text style={{ color: '#9ca3af', fontSize: 14 }}>Fastest</Text>
              </View>
              <View style={{ position: 'absolute', right: 0, flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <Text style={{ color: '#9ca3af', fontSize: 14 }}>Best Coverage</Text>
                <Wifi size={16} color="#10b981" />
              </View>
            </View>

            {/* Slider track */}
            <View style={{
              backgroundColor: '#2a2a2a',
              borderRadius: 100,
              height: 64,
              flexDirection: 'row',
              alignItems: 'center',
              overflow: 'hidden',
              position: 'relative',
            }}>
              <Animated.View style={{
                position: 'absolute',
                width: SEGMENT_WIDTH,
                height: '100%',
                backgroundColor: '#ffffff',
                borderRadius: 100,
                transform: [{ translateX: pillTranslateX }],
                shadowColor: '#000',
                shadowOffset: { width: 0, height: 2 },
                shadowOpacity: 0.2,
                shadowRadius: 4,
                elevation: 3,
              }} />
              {(['Fast', 'Balanced', 'Connected'] as const).map((mode) => (
                <TouchableOpacity
                  key={mode}
                  onPress={() => handleModeChange(mode)}
                  style={{ flex: 1, alignItems: 'center', justifyContent: 'center', height: '100%' }}
                >
                  <Text style={{
                    fontSize: 15,
                    fontWeight: '700',
                    color: routingMode === mode ? '#000000' : '#6b7280',
                    zIndex: 1,
                  }}>
                    {mode}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* Mode badge */}
            <View style={{ marginTop: 20, alignItems: 'center' }}>
              <View style={{
                backgroundColor: modeColors[routingMode] + '22',
                borderWidth: 1.5,
                borderColor: modeColors[routingMode] + '80',
                paddingHorizontal: 24,
                paddingVertical: 10,
                borderRadius: 14,
                flexDirection: 'row',
                alignItems: 'center',
              }}>
                <View style={{
                  width: 8,
                  height: 8,
                  borderRadius: 4,
                  backgroundColor: modeColors[routingMode],
                  marginRight: 10,
                }} />
                <Text style={{ color: '#9ca3af', fontSize: 15, fontWeight: '500' }}>
                  Mode:{' '}
                </Text>
                <Text style={{ color: modeColors[routingMode], fontSize: 15, fontWeight: '800' }}>
                  {routingMode}
                </Text>
              </View>
            </View>
          </View>

          {/* BOTTOM DASHBOARD */}
          <View style={{
            position: 'absolute', bottom: 0, left: 0, right: 0,
            backgroundColor: '#0d0d0d',
            borderTopWidth: 1, borderTopColor: '#222',
            paddingHorizontal: 64, paddingVertical: 40,
            flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
            zIndex: 50,
          }}>
            <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 16 }}>
              <Text style={{ color: '#6b7280', fontSize: 18, fontWeight: '700', textTransform: 'uppercase' }}>Arrival</Text>
              <Text style={{ color: '#fff', fontSize: 48, fontWeight: '900' }}>
                {getArrivalTime(routeOptions[selectedRouteIndex!]?.duration)}
              </Text>
            </View>
            <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 8 }}>
              <Text style={{ color: activeRouteColor, fontSize: 48, fontWeight: '900' }}>
                {routeOptions[selectedRouteIndex!]?.duration}
              </Text>
              <Text style={{ color: activeRouteColor + '99', fontSize: 24, fontWeight: '700' }}>min</Text>
            </View>
            <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 8 }}>
              <Text style={{ color: '#fff', fontSize: 48, fontWeight: '900' }}>{routeOptions[selectedRouteIndex!]?.distance}</Text>
              <Text style={{ color: '#6b7280', fontSize: 24, fontWeight: '700', textTransform: 'uppercase' }}>km</Text>
            </View>
          </View>
        </>
      )}
    </View>
  );
}