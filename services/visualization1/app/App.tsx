import {
  useCallback,
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
  ChevronDown,
} from "lucide-react";
import MapView from "./components/MapView";
import RouteCard, {
  RouteCardError,
  RouteCardSkeleton,
  routeLabelForStrategy,
} from "./components/RouteCard";
import ConnectivitySlider from "./components/ConnectivitySlider";
import Legend from "./components/Legend";
import type {
  FormattedRoute,
  ScoreSourceInfo,
  Strategy,
  Vehicle,
  ViewportBounds,
} from "./lib/api";
import {
  fetchCities,
  fetchCityContext,
  fetchHotspotsForViewport,
  fetchScoreSource,
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
  startedAt: number;
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
const ROUTE_LOADING_COPY: Record<Strategy, string> = {
  fastest: "Calculating fastest route...",
  balanced: "Computing balanced route...",
  connected: "Finding best coverage route...",
};
const VEHICLE_OPTIONS: Array<{ id: Vehicle; icon: string; label: string }> = [
  { id: "scooter", icon: "🛵", label: "Scooter" },
  { id: "bike", icon: "🚲", label: "Bike" },
  { id: "car", icon: "🚗", label: "Car" },
  { id: "truck", icon: "🚚", label: "Truck" },
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

function strategyForRoute(routeId: number): Strategy {
  if (routeId === 0) return "connected";
  if (routeId === 2) return "fastest";
  return "balanced";
}

export default function App() {
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [selectedRoute, setSelectedRoute] = useState(1);
  const [connectivityWeight, setConnectivityWeight] = useState(50);
  const [darkMode, setDarkMode] = useState(false);
  const [selectedVehicle, setSelectedVehicle] = useState<Vehicle>("car");

  const [hotspots, setHotspots] = useState<Hotspot[]>([]);
  const [cityList, setCityList] = useState<string[]>([]);
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
  const [loadingElapsed, setLoadingElapsed] = useState<number>(0);
  const [cityMenuOpen, setCityMenuOpen] = useState(false);
  const [routeReloadKey, setRouteReloadKey] = useState(0);
  const [scoreSource, setScoreSource] = useState<ScoreSourceInfo | null>(null);
  const [cityLoadingLabel, setCityLoadingLabel] = useState<string | null>(null);
  const [viewportBounds, setViewportBounds] = useState<ViewportBounds | null>(null);
  const requestSequence = useRef(0);
  const cityMenuRef = useRef<HTMLDivElement | null>(null);
  const preloadedCitiesRef = useRef<Set<string>>(new Set());

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
        setCityList(cities);
        setSelectedCity((current) => current ?? cities[0] ?? null);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!toastMessage) return undefined;

    const timeoutId = window.setTimeout(() => setToastMessage(""), 2500);
    return () => window.clearTimeout(timeoutId);
  }, [toastMessage]);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!cityMenuRef.current) return;
      if (cityMenuRef.current.contains(event.target as Node)) return;
      setCityMenuOpen(false);
    };

    window.addEventListener("pointerdown", handlePointerDown);
    return () => window.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  useEffect(() => {
    if (!preparingState) {
      setRetryCountdown(null);
      setLoadingElapsed(0);
      return undefined;
    }

    const updateCountdown = () => {
      const secondsLeft = Math.max(
        0,
        Math.ceil((preparingState.retryAt - Date.now()) / 1000),
      );
      setRetryCountdown(secondsLeft);
      setLoadingElapsed(
        Math.max(0, Math.floor((Date.now() - preparingState.startedAt) / 1000)),
      );
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
    setScoreSource(null);
    setCityLoadingLabel(formatCityName(selectedCity));

    fetchCityContext(selectedCity)
      .then((context) => {
        if (cancelled) return;

        setOrigin(context.origin);
        setDestination(context.destination);
        setOriginInput(formatCoordinates(context.origin));
        setDestinationInput(formatCoordinates(context.destination));
        setMapViewRequest({
          center: context.center,
          zoom: CITY_ZOOM,
          behavior: "fly",
        });
        setCityLoadingLabel(null);
      })
      .catch((err) => {
        if (!cancelled) {
          setCityLoadingLabel(null);
          setError(err.message);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedCity]);

  useEffect(() => {
    if (!showHeatmap || !selectedCity || !viewportBounds) {
      setHotspots([]);
      return undefined;
    }

    let cancelled = false;
    const loadHotspots = async () => {
      try {
        const nextHotspots = await fetchHotspotsForViewport(selectedCity, viewportBounds);
        if (!cancelled) {
          setHotspots(nextHotspots);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load hotspots");
        }
      }
    };

    void loadHotspots();
    const intervalId = window.setInterval(() => {
      void loadHotspots();
    }, 30000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [selectedCity, showHeatmap, viewportBounds]);

  useEffect(() => {
    if (!selectedCity) return undefined;

    let cancelled = false;
    const loadScoreSource = async () => {
      try {
        const source = await fetchScoreSource(selectedCity);
        if (!cancelled) {
          setScoreSource(source);
        }
      } catch {
        if (!cancelled) {
          setScoreSource(null);
        }
      }
    };

    void loadScoreSource();
    const intervalId = window.setInterval(() => {
      void loadScoreSource();
    }, 30000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
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
            vehicle: selectedVehicle,
          });

          if (cancelled || requestId !== requestSequence.current) {
            return { status: "cancelled" };
          }

          if (isRouteLoadingResponse(response)) {
            const retryAfter = Math.max(1, response.retryAfter);
            setPreparingState((current) => ({
              message: `Loading ${formatCityName(selectedCity)} road network... (first time ~60s)`,
              retryAt: Date.now() + retryAfter * 1000,
              startedAt: current?.startedAt ?? Date.now(),
            }));
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
  }, [selectedCity, origin, destination, selectedVehicle, routeReloadKey]);

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

  const showToast = useCallback((message: string) => {
    setToastMessage(message);
  }, []);

  const updateLocation = useCallback((target: LocationTarget, coordinates: Coordinates) => {
    if (target === "origin") {
      setOrigin(coordinates);
      setOriginInput(formatCoordinates(coordinates));
      return;
    }

    setDestination(coordinates);
    setDestinationInput(formatCoordinates(coordinates));
  }, []);

  const handleCityHover = useCallback((city: string) => {
    if (city === selectedCity || preloadedCitiesRef.current.has(city)) return;
    preloadedCitiesRef.current.add(city);
    void preloadCity(city).catch(() => {
      preloadedCitiesRef.current.delete(city);
    });
  }, [selectedCity]);

  const handleCityChange = useCallback((city: string) => {
    if (city === selectedCity) return;

    setSelectedCity(city);
    setCityMenuOpen(false);
    setRouteSlots(buildRouteSlots("idle"));
    setExplainedRouteId(null);
    setPreparingState(null);
    setOrigin(undefined);
    setDestination(undefined);
    setOriginInput("");
    setDestinationInput("");
  }, [selectedCity]);

  const retryRoutes = useCallback(() => {
    setError("");
    setRouteReloadKey((current) => current + 1);
  }, []);

  const handleRouteSelect = useCallback((routeId: number) => {
    setSelectedRoute(routeId);
    if (routeId === 0) {
      setConnectivityWeight(80);
    } else if (routeId === 1) {
      setConnectivityWeight(50);
    } else {
      setConnectivityWeight(20);
    }
  }, []);

  const resolveLocationInput = useCallback(async (target: LocationTarget) => {
    const query = (target === "origin" ? originInput : destinationInput).trim();
    if (!query) return;

    setActiveLocationTarget(target);
    setResolvingTarget(target);

    try {
      const coordinates = parseCoordinateInput(query) ?? (await geocodeLocation(query));
      updateLocation(target, coordinates);
      setMapViewRequest({
        center: coordinates,
        zoom: LOCATION_ZOOM,
        behavior: "fly",
      });
    } catch (err) {
      showToast(err instanceof Error ? err.message : `Unable to resolve ${target}`);
    } finally {
      setResolvingTarget((current) => (current === target ? null : current));
    }
  }, [destinationInput, originInput, showToast, updateLocation]);

  const handleLocationKeyDown = useCallback((
    target: LocationTarget,
    event: KeyboardEvent<HTMLInputElement>,
  ) => {
    if (event.key !== "Enter") return;

    event.preventDefault();
    void resolveLocationInput(target);
  }, [resolveLocationInput]);

  const handleLocateMe = useCallback(() => {
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
      },
      () => {
        showToast("Location access denied");
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
      },
    );
  }, [showToast, updateLocation]);

  const handleMapCoordinatePick = useCallback((
    target: LocationTarget,
    coordinates: Coordinates,
  ) => {
    setActiveLocationTarget(target);
    updateLocation(target, coordinates);
  }, [updateLocation]);

  const toggleExplanation = useCallback((routeId: number) => {
    setExplainedRouteId((current) => (current === routeId ? null : routeId));
  }, []);

  const handleViewportChange = useCallback((nextViewport: ViewportBounds) => {
    setViewportBounds(nextViewport);
  }, []);

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
          signalSource={scoreSource}
          placementTarget={activeLocationTarget}
          viewRequest={mapViewRequest}
          onCoordinatePick={handleMapCoordinatePick}
          onViewportChange={handleViewportChange}
        />

        <div className="pointer-events-auto absolute right-4 top-4 z-[1200] flex flex-col items-end gap-2">
          <div className="flex flex-wrap items-center justify-end gap-3">
            <Clock />
            {cityList.length ? (
              <div ref={cityMenuRef} className="relative">
                <button
                  type="button"
                  onClick={() => setCityMenuOpen((current) => !current)}
                  className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white backdrop-blur-xl"
                >
                  <span>{cityLabel}</span>
                  <ChevronDown className={`h-4 w-4 transition ${cityMenuOpen ? "rotate-180" : ""}`} />
                </button>

                {cityMenuOpen ? (
                  <div className="absolute right-0 top-full mt-2 min-w-[180px] rounded-2xl border border-white/10 bg-black/85 p-2 shadow-xl backdrop-blur-xl">
                    {cityList.map((city) => (
                      <button
                        key={city}
                        type="button"
                        onMouseEnter={() => handleCityHover(city)}
                        onFocus={() => handleCityHover(city)}
                        onClick={() => handleCityChange(city)}
                        className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm transition ${
                          city === selectedCity
                            ? "bg-sky-400/20 text-white"
                            : "text-white/75 hover:bg-white/10 hover:text-white"
                        }`}
                      >
                        <span>{formatCityName(city)}</span>
                        {city === selectedCity ? (
                          <span className="text-[10px] uppercase tracking-[0.18em] text-sky-200/80">
                            Live
                          </span>
                        ) : null}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
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

          <div className="flex flex-wrap items-center justify-end gap-2 rounded-2xl border border-white/10 bg-black/35 px-3 py-2 backdrop-blur-xl">
            <span className="mr-1 text-[11px] uppercase tracking-[0.2em] text-white/50">
              Vehicle
            </span>
            {VEHICLE_OPTIONS.map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => setSelectedVehicle(option.id)}
                className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs transition ${
                  selectedVehicle === option.id
                    ? "border-sky-300/70 bg-sky-400/20 text-white"
                    : "border-white/10 bg-white/5 text-white/70 hover:bg-white/10"
                }`}
              >
                <span className="text-sm leading-none">{option.icon}</span>
                <span>{option.label}</span>
              </button>
            ))}
          </div>
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

      <div className="absolute left-4 top-24 z-20 w-[380px] space-y-3">
        <div className="rounded-2xl border border-white/10 bg-black/30 p-4 shadow-xl backdrop-blur-xl">
          <h3 className="mb-4 text-sm text-white">Routing Priority</h3>
          <ConnectivitySlider value={connectivityWeight} onChange={setConnectivityWeight} />
        </div>

        <div className="rounded-2xl border border-white/10 bg-black/30 p-4 shadow-xl backdrop-blur-xl">
          <h3 className="mb-3 text-sm text-white">Available Routes</h3>

          {cityLoadingLabel ? (
            <div className="mb-3 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-white/75">
              Loading {cityLoadingLabel} network...
            </div>
          ) : null}

          {preparingState ? (
            <div className="mb-3 rounded-xl border border-sky-300/20 bg-sky-500/10 px-3 py-2 text-xs text-sky-100">
              <div>{preparingState.message}</div>
              <div className="mt-1 flex items-center justify-between gap-3 text-sky-100/70">
                <span>Elapsed {loadingElapsed}s</span>
                <span>Retrying in {retryCountdown ?? 0}s</span>
              </div>
            </div>
          ) : null}

          <div className="space-y-2">
            {hasRouteInputs ? (
              ROUTE_ORDER.map((strategy, index) => {
                const slot = routeSlots[strategy];
                if (slot.state === "ready" && slot.route) {
                  return (
                    <RouteCard
                      key={strategy}
                      route={slot.route}
                      isSelected={selectedRoute === slot.route.id}
                      isExplainOpen={explainedRouteId === slot.route.id}
                      onClick={() => handleRouteSelect(slot.route!.id)}
                      onToggleExplain={() => toggleExplanation(slot.route!.id)}
                      delay={index * 0.05}
                    />
                  );
                }

                if (slot.state === "error") {
                  return (
                    <RouteCardError
                      key={strategy}
                      label={routeLabelForStrategy(strategy)}
                      message={slot.error ?? "Route unavailable"}
                    />
                  );
                }

                return (
                  <RouteCardSkeleton
                    key={strategy}
                    label={routeLabelForStrategy(strategy)}
                    delay={index * 0.05}
                    message={ROUTE_LOADING_COPY[strategy]}
                  />
                );
              })
            ) : (
              <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-3 text-xs text-white/60">
                Set origin and destination to load routes.
              </div>
            )}

            {loadingRoutes ? (
              <div className="flex items-center gap-2 text-[11px] text-white/55">
                <span className="signal-bars signal-bars-inline">
                  <span />
                  <span />
                  <span />
                </span>
                <span>Fetching signal towers near your route...</span>
              </div>
            ) : null}

            {hasRouteErrors && !loadingRoutes ? (
              <button
                type="button"
                onClick={retryRoutes}
                className="rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-[11px] font-medium text-white transition hover:bg-white/15"
              >
                Retry
              </button>
            ) : null}
          </div>
        </div>

        {selectedRouteData?.warning ? (
          <div className="rounded-2xl border border-amber-300/20 bg-amber-500/10 p-3">
            <div className="flex gap-2">
              <AlertTriangle className="text-amber-300" />
              <p className="text-xs text-amber-300">
                {selectedRouteData.warning}
              </p>
            </div>
          </div>
        ) : null}
      </div>

      <div className="absolute bottom-4 right-4 z-20 space-y-3">
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
        {showHeatmap && !routes.length ? <Legend /> : null}

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
