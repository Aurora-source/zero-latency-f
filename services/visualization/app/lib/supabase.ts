export interface Hotspot {
  id: string;
  name: string;
  lat: number;
  lon: number;
  signal_strength: 'strong' | 'medium' | 'weak';
  radius_meters: number;
  city: string;
}

// Supabase is not wired for this demo stack; keep a stub for compatibility.
export async function fetchHotspots(_: string = "bangalore"): Promise<Hotspot[]> {
  return [];
}
