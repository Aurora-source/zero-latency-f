import { createClient } from '@supabase/supabase-js';

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL;
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

export interface Hotspot {
  id: string;
  name: string;
  lat: number;
  lon: number;
  signal_strength: 'strong' | 'medium' | 'weak';
  radius_meters: number;
  city: string;
}

export async function fetchHotspots(city = 'bangalore'): Promise<Hotspot[]> {
  const { data, error } = await supabase
    .from('hotspots')
    .select('*')
    .eq('city', city);

  if (error) {
    console.error('Failed to fetch hotspots:', error);
    return [];
  }

  return data ?? [];
}