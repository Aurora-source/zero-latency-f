import { useEffect, useState } from "react";

import { fetchRoute, fetchSegments } from "./api";
import CitySelector from "./components/CitySelector";
import MapView from "./components/MapView";
import RoutePanel from "./components/RoutePanel";

const CITY_CONFIG = {
  chennai: {
    label: "Chennai",
    center: [13.0827, 80.2707],
    origin: [13.0012, 80.2565],
    destination: [13.085, 80.2101],
  },
  mumbai: {
    label: "Mumbai",
    center: [19.076, 72.8777],
    origin: [19.0433, 72.8617],
    destination: [19.1187, 72.9068],
  },
  delhi: {
    label: "Delhi",
    center: [28.6139, 77.209],
    origin: [28.5921, 77.229],
    destination: [28.6714, 77.1131],
  },
};

const ROUTE_ORDER = ["fastest", "connected", "balanced"];

function formatCoordinate([lat, lon]) {
  return `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
}

function getErrorMessage(error) {
  if (error?.response?.data?.detail) {
    return error.response.data.detail;
  }
  if (error?.message) {
    return error.message;
  }
  return "Unable to load map data right now.";
}

export default function App() {
  const [city, setCity] = useState("chennai");
  const [segments, setSegments] = useState(null);
  const [routes, setRoutes] = useState({});
  const [selectedMode, setSelectedMode] = useState("balanced");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let ignore = false;
    const cityConfig = CITY_CONFIG[city];

    async function loadCity() {
      setIsLoading(true);
      setError("");
      setSelectedMode("balanced");

      try {
        const [segmentData, routeData] = await Promise.all([
          fetchSegments(city),
          Promise.all(
            ROUTE_ORDER.map((mode) =>
              fetchRoute({
                city,
                origin: cityConfig.origin,
                destination: cityConfig.destination,
                mode,
              }),
            ),
          ),
        ]);

        if (ignore) {
          return;
        }

        setSegments(segmentData);
        setRoutes(
          routeData.reduce((accumulator, route) => {
            accumulator[route.mode] = route;
            return accumulator;
          }, {}),
        );
      } catch (requestError) {
        if (!ignore) {
          setSegments(null);
          setRoutes({});
          setError(getErrorMessage(requestError));
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }

    loadCity();

    return () => {
      ignore = true;
    };
  }, [city]);

  const cityConfig = CITY_CONFIG[city];

  return (
    <div className="min-h-screen">
      <div className="mx-auto flex min-h-screen max-w-[1800px] flex-col gap-4 p-4 lg:grid lg:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="rounded-[28px] border border-white/60 bg-white/75 p-5 shadow-glow backdrop-blur xl:p-6">
          <div className="mb-6 space-y-4">
            <div>
              <p className="font-mono text-xs uppercase tracking-[0.35em] text-slate-500">
                Phase 1 Demo
              </p>
              <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">
                Connectivity-Aware Routing
              </h1>
              <p className="mt-3 text-sm leading-6 text-slate-600">
                Mock seeded connectivity overlays plus three route strategies:
                fastest, strongest signal, and a balanced compromise.
              </p>
            </div>

            <CitySelector city={city} cities={CITY_CONFIG} onChange={setCity} />

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <p className="font-mono text-[11px] uppercase tracking-[0.28em] text-slate-500">
                  Origin
                </p>
                <p className="mt-2 text-base font-semibold text-slate-900">
                  Demo Start
                </p>
                <p className="mt-1 text-sm text-slate-600">
                  {formatCoordinate(cityConfig.origin)}
                </p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <p className="font-mono text-[11px] uppercase tracking-[0.28em] text-slate-500">
                  Destination
                </p>
                <p className="mt-2 text-base font-semibold text-slate-900">
                  Demo Finish
                </p>
                <p className="mt-1 text-sm text-slate-600">
                  {formatCoordinate(cityConfig.destination)}
                </p>
              </div>
            </div>

            {error ? (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
                {error}
              </div>
            ) : null}
          </div>

          <RoutePanel
            loading={isLoading}
            routes={routes}
            selectedMode={selectedMode}
            onSelect={setSelectedMode}
          />
        </aside>

        <main className="overflow-hidden rounded-[30px] border border-white/60 bg-slate-900/10 shadow-glow backdrop-blur">
          <MapView
            city={city}
            center={cityConfig.center}
            origin={cityConfig.origin}
            destination={cityConfig.destination}
            segments={segments}
            routes={routes}
            selectedMode={selectedMode}
          />
        </main>
      </div>
    </div>
  );
}
