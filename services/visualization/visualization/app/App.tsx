import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import {
  Search,
  Navigation,
  AlertTriangle,
  Sun,
  Moon,
  LocateFixed,
} from "lucide-react";
import MapView from "./components/MapView";
import RouteCard, {
  RouteCardError,
  RouteCardSkeleton,
  routeLabelForStrategy,
} from "./components/RouteCard";
import ConnectivitySlider from "./components/ConnectivitySlider";
import Legend from "./components/Legend";
import type { FormattedRoute, Strategy, Vehicle } from "./lib/api";
import {
  fetchCities,
  fetchCityContext,
  fetchHotspotsFromBackend,
  preloadCity,
  fetchRoute,
  formatRouteForUI,
  geocodeLocation,
  isRouteLoadingResponse,
} from "./lib/api";
import type { Hotspot } from "./lib/supabase";

type Coordinates = [number, number];
type LocationTarget = "origin" | "destination";
type RouteSlotState = "idle" | "loading" | "ready" | "error";

interface MapViewRequest {
  center: Coordinates;
  zoom?: number;
  behavior?: "fly" | "set";
}

interface RouteSlot {
  strategy: Strategy;
  state: RouteSlotState;
  route?: FormattedRoute;
  error?: string;
}

interface PreparingState {
  message: string;
  retryAt: number;
}

type RouteLoadResult =
  | { status: "ready" }
  | { status: "error"; message: string }
  | { status: "cancelled" };

const CITY_ZOOM = 12;
const LOCATION_ZOOM = 15;
const ROUTE_ORDER: Strategy[] = ["connected", "balanced", "fastest"];
const ROUTE_COLORS: Record<Strategy, string> = {
  connected: "#10b981",
  balanced: "#8b5cf6",
  fastest: "#3b82f6",
};
const ACTIVE_VIEW_COPY: Record<Strategy, string> = {
  fastest: "Optimized for shortest travel time",
  balanced: "Balanced between speed and connectivity",
  connected: "Optimized for best signal coverage",
};
const VEHICLE_OPTIONS: Array<{ id: Vehicle; icon: string; label: string }> = [
  { id: "bike" as Vehicle, icon: "🛵", label: "2 Wheeler" },
  { id: "car" as Vehicle, icon: "🚗", label: "Car" },
  { id: "truck" as Vehicle, icon: "🚚", label: "Truck" },
];

function buildRouteSlots(state: RouteSlotState): Record<Strategy, RouteSlot> {
  return {
    connected: { strategy: "connected", state },
    balanced: { strategy: "balanced", state },
    fastest: { strategy: "fastest", state },
  };
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

const Clock = () => {
  const [time, setTime] = useState("");

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTime(
        now.toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        }),
      );
    };

    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm font-medium text-white backdrop-blur-xl">
      {time}
    </div>
  );
};

function formatCityName(city: string) {
  return city.replace(/[_-]/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatCoordinates([lat, lon]: Coordinates) {
  return `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
}

function parseCoordinateInput(value: string): Coordinates | null {
  if (!value.includes(",")) {
    return null;
  }

  const pieces = value.split(",").map((piece) => piece.trim());
  if (pieces.length !== 2) {
    return null;
  }

  const lat = Number(pieces[0]);
  const lon = Number(pieces[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return null;
  }
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    throw new Error("Coordinates must be valid latitude and longitude values");
  }

  return [lat, lon];
}

async function reverseGeocode([lat, lon]: Coordinates): Promise<string | null> {
  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}&zoom=18&addressdetails=1`,
      { headers: { "Accept-Language": "en" } }
    );
    const data = await res.json();
    if (data && data.display_name) {
      const parts = data.display_name.split(",");
      return parts.slice(0, 3).join(",").trim();
    }
    return null;
  } catch {
    return null;
  }
}

function strategyForRoute(routeId: number): Strategy {
  if (routeId === 0) return "connected";
  if (routeId === 2) return "fastest";
  return "balanced";
}

export default function App() {
  const [showHeatmap, setShowHeatmap] = useState(true);
  const [selectedRoute, setSelectedRoute] = useState(1);
  const [connectivityWeight, setConnectivityWeight] = useState(50);
  const [darkMode, setDarkMode] = useState(false);
  const [selectedVehicle, setSelectedVehicle] = useState<Vehicle>("car");

  const [hotspots, setHotspots] = useState<Hotspot[]>([]);
  const [selectedCity, setSelectedCity] = useState<string | null>(null);
  const [origin, setOrigin] = useState<Coordinates>();
  const [destination, setDestination] = useState<Coordinates>();
  const [originInput, setOriginInput] = useState("");
  const [destinationInput, setDestinationInput] = useState("");
  const [activeLocationTarget, setActiveLocationTarget] =
    useState<LocationTarget>("origin");
  const [mapViewRequest, setMapViewRequest] = useState<MapViewRequest | null>(null);
  const [routeSlots, setRouteSlots] = useState<Record<Strategy, RouteSlot>>(
    buildRouteSlots("idle"),
  );
  const [error, setError] = useState("");
  const [toastMessage, setToastMessage] = useState("");
  const [resolvingTarget, setResolvingTarget] = useState<LocationTarget | null>(null);
  const [explainedRouteId, setExplainedRouteId] = useState<number | null>(null);
  const [preparingState, setPreparingState] = useState<PreparingState | null>(null);
  const [retryCountdown, setRetryCountdown] = useState<number | null>(null);
  const [routeReloadKey, setRouteReloadKey] = useState(0);
  const requestSequence = useRef(0);

  const routes = useMemo(
    () =>
      ROUTE_ORDER.map((strategy) => routeSlots[strategy].route).filter(
        (route): route is FormattedRoute => Boolean(route),
      ),
    [routeSlots],
  );
  const loadingRoutes = useMemo(
    () => ROUTE_ORDER.some((strategy) => routeSlots[strategy].state === "loading"),
    [routeSlots],
  );
  const activeMode = useMemo(
    () => strategyForRoute(selectedRoute),
    [selectedRoute],
  );
  const selectedRouteData = useMemo(
    () => routes.find((route) => route.id === selectedRoute),
    [routes, selectedRoute],
  );
  const cityLabel = useMemo(
    () => (selectedCity ? formatCityName(selectedCity) : "Select city"),
    [selectedCity],
  );
  const hasRouteInputs = Boolean(selectedCity && origin && destination);
  const hasRouteErrors = useMemo(
    () => ROUTE_ORDER.some((strategy) => routeSlots[strategy].state === "error"),
    [routeSlots],
  );

  useEffect(() => {
    fetchCities()
      .then((cities) => {
        setSelectedCity((current) => current ?? cities[0] ?? null);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    fetchHotspotsFromBackend().then(setHotspots);
  }, []);

  useEffect(() => {
    if (!toastMessage) return undefined;
    const timeoutId = window.setTimeout(() => setToastMessage(""), 2500);
    return () => window.clearTimeout(timeoutId);
  }, [toastMessage]);

  useEffect(() => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const coordinates: Coordinates = [
            position.coords.latitude,
            position.coords.longitude,
          ];
          updateLocation("origin", coordinates);
          setMapViewRequest({
            center: coordinates,
            zoom: LOCATION_ZOOM,
            behavior: "fly",
          });
          setActiveLocationTarget("destination");
        },
        () => {},
        {
          enableHighAccuracy: true,
          timeout: 10000,
        }
      );
    }
  }, []);

  useEffect(() => {
    if (!preparingState) {
      setRetryCountdown(null);
      return undefined;
    }

    const updateCountdown = () => {
      const secondsLeft = Math.max(
        0,
        Math.ceil((preparingState.retryAt - Date.now()) / 1000),
      );
      setRetryCountdown(secondsLeft);
    };

    updateCountdown();
    const intervalId = window.setInterval(updateCountdown, 1000);
    return () => window.clearInterval(intervalId);
  }, [preparingState]);

  useEffect(() => {
    if (!loadingRoutes) {
      setPreparingState(null);
    }
  }, [loadingRoutes]);

  useEffect(() => {
    if (!selectedCity) return undefined;

    let cancelled = false;
    setError("");
    setRouteSlots(buildRouteSlots("idle"));
    setExplainedRouteId(null);
    setPreparingState(null);
    setOrigin(undefined);
    setDestination(undefined);

    fetchCityContext(selectedCity)
      .then((context) => {
        if (cancelled) return;

        setOrigin(context.origin);
        setDestination(context.destination);
        setOriginInput("Resolving...");
        setDestinationInput("Resolving...");

        void (async () => {
          const originAddr = await reverseGeocode(context.origin);
          if (!cancelled) setOriginInput(originAddr ?? formatCoordinates(context.origin));
          
          await sleep(1000);
          
          const destAddr = await reverseGeocode(context.destination);
          if (!cancelled) setDestinationInput(destAddr ?? formatCoordinates(context.destination));
        })();

        setMapViewRequest({
          center: context.center,
          zoom: CITY_ZOOM,
          behavior: "fly",
        });
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedCity]);

  useEffect(() => {
    if (!selectedCity || !origin || !destination) return undefined;

    requestSequence.current += 1;
    const requestId = requestSequence.current;
    let cancelled = false;

    setError("");
    setRouteSlots(buildRouteSlots("loading"));
    setExplainedRouteId(null);
    setPreparingState(null);

    const loadStrategy = async (strategy: Strategy): Promise<RouteLoadResult> => {
      try {
        while (!cancelled && requestId === requestSequence.current) {
          const response = await fetchRoute({
            city: selectedCity,
            origin,
            destination,
            strategy,
            vehicle: "car",
          });

          if (cancelled || requestId !== requestSequence.current) {
            return { status: "cancelled" };
          }

          if (isRouteLoadingResponse(response)) {
            const retryAfter = Math.max(1, response.retryAfter);
            setPreparingState({
              message: "Preparing city graph...",
              retryAt: Date.now() + retryAfter * 1000,
            });
            await sleep(retryAfter * 1000);
            continue;
          }

          const formattedRoute = formatRouteForUI(
            response,
            ROUTE_COLORS[strategy],
          );
          setRouteSlots((current) => ({
            ...current,
            [strategy]: {
              strategy,
              state: "ready",
              route: formattedRoute,
            },
          }));
          return { status: "ready" };
        }
      } catch (err) {
        if (cancelled || requestId !== requestSequence.current) {
          return { status: "cancelled" };
        }

        const message =
          err instanceof Error ? err.message : `Unable to load ${strategy} route`;
        setRouteSlots((current) => ({
          ...current,
          [strategy]: {
            strategy,
            state: "error",
            error: message,
          },
        }));
        return { status: "error", message };
      }

      return { status: "cancelled" };
    };

    const tasks = ROUTE_ORDER.map((strategy) => loadStrategy(strategy));
    void Promise.allSettled(tasks).then((results) => {
      if (cancelled || requestId !== requestSequence.current) return;

      const successfulLoads = results.filter(
        (result) => result.status === "fulfilled" && result.value.status === "ready",
      );
      if (!successfulLoads.length) {
        const failedMessages = results
          .filter(
            (result): result is PromiseFulfilledResult<RouteLoadResult> =>
              result.status === "fulfilled" && result.value.status === "error",
          )
          .map((result) => result.value.message);
        setError(
          failedMessages[0] ?? "Unable to load any routes for the selected city.",
        );
      }
    });

    return () => {
      cancelled = true;
    };
  }, [selectedCity, origin, destination, routeReloadKey]);

  useEffect(() => {
    if (connectivityWeight < 40) {
      setSelectedRoute(2);
      return;
    }
    if (connectivityWeight > 60) {
      setSelectedRoute(0);
      return;
    }
    setSelectedRoute(1);
  }, [connectivityWeight]);

  const showToast = (message: string) => {
    setToastMessage(message);
  };

  const updateLocation = (target: LocationTarget, coordinates: Coordinates, label?: string) => {
    if (target === "origin") {
      setOrigin(coordinates);
      if (label) {
        setOriginInput(label);
      } else {
        setOriginInput("Resolving...");
        reverseGeocode(coordinates).then(addr => {
          setOriginInput(addr ?? formatCoordinates(coordinates));
        });
      }
    } else {
      setDestination(coordinates);
      if (label) {
        setDestinationInput(label);
      } else {
        setDestinationInput("Resolving...");
        reverseGeocode(coordinates).then(addr => {
          setDestinationInput(addr ?? formatCoordinates(coordinates));
        });
      }
    }
  };

  const retryRoutes = () => {
    setError("");
    setRouteReloadKey((current) => current + 1);
  };

  const handleRouteSelect = (routeId: number) => {
    setSelectedRoute(routeId);
    if (routeId === 0) {
      setConnectivityWeight(80);
    } else if (routeId === 1) {
      setConnectivityWeight(50);
    } else {
      setConnectivityWeight(20);
    }
  };

  const resolveLocationInput = async (target: LocationTarget) => {
    const query = (target === "origin" ? originInput : destinationInput).trim();
    if (!query) return;

    setActiveLocationTarget(target);
    setResolvingTarget(target);

    try {
      const parsedCoords = parseCoordinateInput(query);
      if (parsedCoords) {
        updateLocation(target, parsedCoords);
        setMapViewRequest({ center: parsedCoords, zoom: LOCATION_ZOOM, behavior: "fly" });
      } else {
        const coordinates = await geocodeLocation(query);
        updateLocation(target, coordinates, query);
        setMapViewRequest({ center: coordinates, zoom: LOCATION_ZOOM, behavior: "fly" });
      }
      
      if (target === "origin") {
        setActiveLocationTarget("destination");
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : `Unable to resolve ${target}`);
    } finally {
      setResolvingTarget((current) => (current === target ? null : current));
    }
  };

  const handleLocationKeyDown = (
    target: LocationTarget,
    event: KeyboardEvent<HTMLInputElement>,
  ) => {
    if (event.key !== "Enter") return;

    event.preventDefault();
    void resolveLocationInput(target);
  };

  const handleLocateMe = () => {
    setActiveLocationTarget("origin");

    if (!navigator.geolocation) {
      showToast("Location access denied");
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const coordinates: Coordinates = [
          position.coords.latitude,
          position.coords.longitude,
        ];

        updateLocation("origin", coordinates);
        setMapViewRequest({
          center: coordinates,
          zoom: LOCATION_ZOOM,
          behavior: "fly",
        });
        setActiveLocationTarget("destination");
      },
      () => {
        showToast("Location access denied");
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
      },
    );
  };

  const handleMapCoordinatePick = (
    target: LocationTarget,
    coordinates: Coordinates,
  ) => {
    updateLocation(target, coordinates);
    if (target === "origin") {
      setActiveLocationTarget("destination");
    }
  };

  const toggleExplanation = (routeId: number) => {
    setExplainedRouteId((current) => (current === routeId ? null : routeId));
  };

  return (
    <div className="relative h-full w-full overflow-hidden bg-black">
      <div className="relative h-full">
        <MapView
          city={selectedCity}
          cityLabel={cityLabel}
          origin={origin}
          destination={destination}
          routes={routes}
          selectedRoute={selectedRoute}
          showHeatmap={showHeatmap}
          darkMode={darkMode}
          hotspots={hotspots}
          activeViewSubtitle={ACTIVE_VIEW_COPY[activeMode]}
          placementTarget={activeLocationTarget}
          viewRequest={mapViewRequest}
          onCoordinatePick={handleMapCoordinatePick}
        />

        <div className="pointer-events-auto absolute right-4 top-4 z-[1200] flex flex-wrap items-center justify-end gap-3">
          <Clock />
          <button
            onClick={() => setDarkMode((current) => !current)}
            className="flex items-center justify-center rounded-xl border border-white/10 bg-black/40 px-3 py-2 backdrop-blur-xl"
          >
            {darkMode ? (
              <Sun className="h-5 w-5 text-yellow-300" />
            ) : (
              <Moon className="h-5 w-5 text-blue-300" />
            )}
          </button>
        </div>

        <div className="pointer-events-auto absolute right-0 top-1/2 z-[1200] group flex w-12 -translate-y-1/2 flex-col gap-2 overflow-hidden rounded-l-2xl border border-r-0 border-white/10 bg-black/40 p-2 shadow-2xl backdrop-blur-xl transition-all duration-300 ease-in-out hover:w-32">
          {VEHICLE_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setSelectedVehicle(option.id)}
              className={`flex h-10 w-full shrink-0 items-center gap-3 rounded-xl border px-1.5 transition-colors ${
                selectedVehicle === option.id
                  ? "border-sky-300/70 bg-sky-400/20 text-white"
                  : "border-transparent text-white/70 hover:bg-white/10 hover:text-white"
              }`}
            >
              <span className="flex w-5 shrink-0 items-center justify-center text-xl">{option.icon}</span>
              <span className="whitespace-nowrap text-xs font-medium tracking-wide opacity-0 transition-opacity duration-300 group-hover:opacity-100">
                {option.label}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="pointer-events-auto absolute left-1/2 top-4 z-[1100] w-full max-w-2xl -translate-x-1/2 px-4">
        <div className="rounded-2xl border border-white/10 bg-black/40 p-2 shadow-xl backdrop-blur-xl">
          <div className="flex flex-col gap-2 md:flex-row md:items-center">
            <div
              className={`flex flex-1 items-center gap-2 rounded-xl px-3 py-2 ${
                activeLocationTarget === "origin"
                  ? "bg-white/16 ring-1 ring-blue-400/60"
                  : "bg-white/10"
              }`}
            >
              <button
                type="button"
                onClick={handleLocateMe}
                className="flex h-9 w-9 items-center justify-center rounded-full border border-white/20 bg-white/10 text-lg text-white transition hover:bg-white/20"
                aria-label="Locate my origin"
                title="Locate Me"
              >
                <LocateFixed className="h-4 w-4" />
              </button>
              <Navigation className="h-4 w-4 text-blue-400" />
              <input
                type="text"
                value={originInput}
                onFocus={() => setActiveLocationTarget("origin")}
                onChange={(event) => setOriginInput(event.target.value)}
                onKeyDown={(event) => handleLocationKeyDown("origin", event)}
                placeholder="Search origin or click map..."
                className="flex-1 bg-transparent text-sm text-white/80 outline-none placeholder:text-white/40"
              />
              <button
                type="button"
                onClick={() => void resolveLocationInput("origin")}
                disabled={resolvingTarget === "origin"}
                className="flex h-9 w-9 items-center justify-center rounded-full border border-white/20 bg-white/10 text-white transition hover:bg-white/20 disabled:opacity-50"
                aria-label="Confirm origin"
              >
                <Search className="h-4 w-4" />
              </button>
            </div>

            <div className="hidden h-6 w-px bg-white/10 md:block" />

            <div
              className={`flex flex-1 items-center gap-2 rounded-xl px-3 py-2 ${
                activeLocationTarget === "destination"
                  ? "bg-white/16 ring-1 ring-emerald-400/60"
                  : "bg-white/10"
              }`}
            >
              <Search className="h-4 w-4 text-white/60" />
              <input
                type="text"
                value={destinationInput}
                onFocus={() => setActiveLocationTarget("destination")}
                onChange={(event) => setDestinationInput(event.target.value)}
                onKeyDown={(event) => handleLocationKeyDown("destination", event)}
                placeholder="Search destination or click map..."
                className="flex-1 bg-transparent text-sm text-white/80 outline-none placeholder:text-white/40"
              />
              <button
                type="button"
                onClick={() => void resolveLocationInput("destination")}
                disabled={resolvingTarget === "destination"}
                className="flex h-9 w-9 items-center justify-center rounded-full border border-white/20 bg-white/10 text-white transition hover:bg-white/20 disabled:opacity-50"
                aria-label="Confirm destination"
              >
                <Search className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="pointer-events-none absolute bottom-8 left-4 top-20 z-20 flex w-[380px] flex-col gap-3">
        
        <div className="pointer-events-auto shrink-0 rounded-2xl border border-white/10 bg-black/30 p-4 shadow-xl backdrop-blur-xl">
          <h3 className="mb-4 text-sm text-white">Routing Priority</h3>
          <ConnectivitySlider value={connectivityWeight} onChange={setConnectivityWeight} />
        </div>

        <div className="pointer-events-auto flex min-h-0 flex-1 flex-col rounded-2xl border border-white/10 bg-black/30 p-4 shadow-xl backdrop-blur-xl overflow-hidden">
          <h3 className="mb-3 shrink-0 text-sm text-white">Available Routes</h3>

          {preparingState ? (
            <div className="mb-3 shrink-0 rounded-xl border border-sky-300/20 bg-sky-500/10 px-3 py-2 text-xs text-sky-100">
              <div>{preparingState.message}</div>
              <div className="mt-1 text-sky-100/70">
                Retrying in {retryCountdown ?? 0}s
              </div>
            </div>
          ) : null}

          <div className="flex-1 overflow-y-auto space-y-2 p-2 -mx-2 transition-colors duration-300 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-transparent hover:[&::-webkit-scrollbar-thumb]:bg-white/20">
            {hasRouteInputs ? (
              ROUTE_ORDER.map((strategy, index) => {
                const slot = routeSlots[strategy];
                if (slot.state === "ready" && slot.route) {
                  return (
                    <div key={strategy}>
                      <RouteCard
                        route={slot.route}
                        isSelected={selectedRoute === slot.route.id}
                        isExplainOpen={explainedRouteId === slot.route.id}
                        onClick={() => handleRouteSelect(slot.route!.id)}
                        onToggleExplain={() => toggleExplanation(slot.route!.id)}
                        delay={index * 0.05}
                      />
                    </div>
                  );
                }

                if (slot.state === "error") {
                  return (
                    <div key={strategy}>
                      <RouteCardError
                        label={routeLabelForStrategy(strategy)}
                        message={slot.error ?? "Route unavailable"}
                      />
                    </div>
                  );
                }

                return (
                  <div key={strategy}>
                    <RouteCardSkeleton
                      label={routeLabelForStrategy(strategy)}
                      delay={index * 0.05}
                    />
                  </div>
                );
              })
            ) : (
              <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-3 text-xs text-white/60 mx-1">
                Set origin and destination to load routes.
              </div>
            )}

            {loadingRoutes ? (
              <div className="text-[11px] text-white/45 mx-1">
                Loading route cards independently...
              </div>
            ) : null}

            {hasRouteErrors && !loadingRoutes ? (
              <div className="mx-1">
                <button
                  type="button"
                  onClick={retryRoutes}
                  className="mt-2 rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-[11px] font-medium text-white transition hover:bg-white/15"
                >
                  Retry
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {selectedRouteData?.warning ? (
        <div className="pointer-events-none absolute bottom-10 left-1/2 z-[1300] w-full max-w-md -translate-x-1/2 px-4">
          <div className="pointer-events-auto rounded-2xl border border-amber-500/30 bg-black/70 p-4 shadow-2xl backdrop-blur-xl">
            <div className="flex items-center justify-center gap-3">
              <AlertTriangle className="h-5 w-5 shrink-0 text-amber-400" />
              <p className="text-sm font-medium tracking-tight text-amber-400">
                {selectedRouteData.warning}
              </p>
            </div>
          </div>
        </div>
      ) : null}

      <div className="absolute bottom-10 right-4 z-20 space-y-3">
        <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-black/30 px-3 py-2 backdrop-blur-xl">
          <span className="text-sm text-white">Heatmap</span>
          <button
            onClick={() => setShowHeatmap((current) => !current)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors duration-200 focus:outline-none ${
              showHeatmap ? "bg-blue-500" : "bg-white/20"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform duration-200 ${
                showHeatmap ? "translate-x-6" : "translate-x-1"
              }`}
            />
          </button>
        </div>
        
        <Legend />

        {error ? (
          <div className="rounded-xl border border-rose-300/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-100">
            {error}
          </div>
        ) : null}
      </div>

      {toastMessage ? (
        <div className="pointer-events-none absolute bottom-6 left-1/2 z-[1300] -translate-x-1/2 rounded-full border border-white/15 bg-black/75 px-4 py-2 text-sm text-white shadow-lg backdrop-blur">
          {toastMessage}
        </div>
      ) : null}
    </div>
  );
}