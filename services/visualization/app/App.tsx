import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import {
  AlertTriangle,
  Bike,
  Car,
  LocateFixed,
  Navigation,
  Search,
  Truck,
  type LucideIcon,
} from "lucide-react";
import Header from "./components/Header";
import RouteCard, {
  RouteCardError,
  RouteCardSkeleton,
  routeLabelForStrategy,
} from "./components/RouteCard";
import ConnectivitySlider from "./components/ConnectivitySlider";
import Legend from "./components/Legend";
import type {
  CoverageStatusInfo,
  FormattedRoute,
  ScoreSourceInfo,
  Strategy,
  Vehicle,
  ViewportBounds,
} from "./lib/api";
import {
  fetchCities,
  fetchCityContext,
  fetchCoverageStatus,
  fetchHotspotsForViewport,
  fetchPredictionReady,
  fetchRoute,
  fetchScoreSource,
  formatRouteForUI,
  geocodeLocation,
  isRouteLoadingResponse,
  preloadCity,
} from "./lib/api";
import type { Hotspot } from "./lib/supabase";

const MapView = lazy(() => import("./components/MapView"));

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
const VEHICLE_OPTIONS: Array<{
  id: Vehicle;
  label: string;
  icon: LucideIcon;
}> = [
  { id: "scooter", label: "Scooter", icon: Bike },
  { id: "bike", label: "Bike", icon: Bike },
  { id: "car", label: "Car", icon: Car },
  { id: "truck", label: "Truck", icon: Truck },
];

function buildRouteSlots(state: RouteSlotState): Record<Strategy, RouteSlot> {
  return {
    connected: { strategy: "connected", state },
    balanced: { strategy: "balanced", state },
    fastest: { strategy: "fastest", state },
  };
}

function sleep(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    const finish = () => { window.clearTimeout(timer); signal.removeEventListener("abort", finish); resolve(); };
    const timer = window.setTimeout(finish, ms);
    signal.addEventListener("abort", finish, { once: true });
    if (signal.aborted) finish();
  });
}

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
  if (pieces.length !== 2 || pieces.some((piece) => !piece)) throw new Error("Enter coordinates as latitude, longitude");

  const lat = Number(pieces[0]);
  const lon = Number(pieces[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    throw new Error("Enter valid latitude and longitude values");
  }
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    throw new Error("Coordinates must be valid latitude and longitude values");
  }

  return [lat, lon];
}

function scoreSourceLabel(source: ScoreSourceInfo | null) {
  if (!source) return null;
  if (source.provenanceSource === "trai") return "TRAI India";
  if (source.provenanceSource === "opencellid") return "OpenCellID";
  if (source.provenanceSource === "hybrid") return "Hybrid real and estimated data";
  if (source.provenanceSource === "unknown") return "Unknown provenance";
  return "Model or fallback estimate";
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
  const [routeReloadKey, setRouteReloadKey] = useState(0);
  const [scoreSource, setScoreSource] = useState<ScoreSourceInfo | null>(null);
  const [coverageStatus, setCoverageStatus] = useState<CoverageStatusInfo | null>(null);
  const [cityLoadingLabel, setCityLoadingLabel] = useState<string | null>(null);
  const [viewportBounds, setViewportBounds] = useState<ViewportBounds | null>(null);
  const [predictionReady, setPredictionReady] = useState<boolean | null>(null);
  const [serviceReloadKey, setServiceReloadKey] = useState(0);

  const requestSequence = useRef(0);
  const routeController = useRef<AbortController | null>(null);
  const locationControllers = useRef<Partial<Record<LocationTarget, AbortController>>>({});
  const locationSequence = useRef({ origin: 0, destination: 0 });
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
  const selectedRouteData = useMemo(
    () => routes.find((route) => route.id === selectedRoute) ?? null,
    [routes, selectedRoute],
  );
  const activeRealDataCoveragePercent =
    selectedRouteData?.realDataCoveragePercent ??
    coverageStatus?.real_data_coverage_percent ??
    scoreSource?.real_data_coverage_percent ??
    0;
  const activeGoodSignalPercent =
    selectedRouteData?.goodSignalPercent ?? scoreSource?.good_signal_percent ?? 0;
  const hasRouteInputs = Boolean(selectedCity && origin && destination);
  const hasRouteErrors = useMemo(
    () => ROUTE_ORDER.some((strategy) => routeSlots[strategy].state === "error"),
    [routeSlots],
  );

  const showToast = useCallback((message: string) => {
    setToastMessage(message);
  }, []);

  const updateLocation = useCallback((
    target: LocationTarget,
    coordinates: Coordinates,
    options?: { label?: string },
  ) => {
    const formatted = formatCoordinates(coordinates);
    routeController.current?.abort();
    requestSequence.current += 1;
    setRouteSlots(buildRouteSlots("idle"));
    const label = options?.label;

    if (target === "origin") {
      setOrigin(coordinates);
      setOriginInput(label ?? formatted);
    } else {
      setDestination(coordinates);
      setDestinationInput(label ?? formatted);
    }

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
    setRouteSlots(buildRouteSlots("idle"));
    setExplainedRouteId(null);
    setPreparingState(null);
    setOrigin(undefined);
    setDestination(undefined);
    setOriginInput("");
    setDestinationInput("");
    setHotspots([]);
    setScoreSource(null);
    setCoverageStatus(null);
  }, [selectedCity]);

  const retryRoutes = useCallback(() => {
    if (loadingRoutes) return;
    setError("");
    setRouteReloadKey((current) => current + 1);
  }, [loadingRoutes]);

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
    locationControllers.current[target]?.abort();
    const controller = new AbortController();
    locationControllers.current[target] = controller;
    const token = ++locationSequence.current[target];

    setActiveLocationTarget(target);
    setResolvingTarget(target);

    try {
      const parsedCoordinates = parseCoordinateInput(query);
      if (parsedCoordinates) {
        updateLocation(target, parsedCoordinates);
        setMapViewRequest({
          center: parsedCoordinates,
          zoom: LOCATION_ZOOM,
          behavior: "fly",
        });
      } else {
        const coordinates = await geocodeLocation(query, controller.signal);
        if (controller.signal.aborted || locationSequence.current[target] !== token) return;
        updateLocation(target, coordinates, { label: query });
        setMapViewRequest({ center: coordinates, zoom: LOCATION_ZOOM, behavior: "fly" });
      }
    } catch (err) {
      if (controller.signal.aborted || locationSequence.current[target] !== token) return;
      showToast(err instanceof Error ? err.message : `Unable to resolve ${target}`);
    } finally {
      if (locationSequence.current[target] === token) setResolvingTarget((current) => (current === target ? null : current));
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
    locationControllers.current.origin?.abort();
    const token = ++locationSequence.current.origin;
    setActiveLocationTarget("origin");

    if (!navigator.geolocation) {
      showToast("Location access denied");
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (locationSequence.current.origin !== token) return;
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
        if (locationSequence.current.origin !== token) return;
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
    locationControllers.current[target]?.abort();
    locationSequence.current[target] += 1;
    setResolvingTarget(null);
    setActiveLocationTarget(target);
    updateLocation(target, coordinates);
  }, [updateLocation]);

  const toggleExplanation = useCallback((routeId: number) => {
    setExplainedRouteId((current) => (current === routeId ? null : routeId));
  }, []);

  const handleViewportChange = useCallback((nextViewport: ViewportBounds) => {
    setViewportBounds(nextViewport);
  }, []);

  useEffect(() => {
    const controllers = locationControllers.current;
    return () => { Object.values(controllers).forEach((controller) => controller.abort()); routeController.current?.abort(); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchCities()
      .then((cities) => {
        if (cancelled) return;
        setError("");
        setCityList(cities);
        setSelectedCity((current) => current ?? cities[0] ?? null);
      })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [serviceReloadKey]);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try { const ready = await fetchPredictionReady(); if (!cancelled) setPredictionReady(ready); }
      catch { if (!cancelled) setPredictionReady(false); }
    };
    void refresh();
    const timer = window.setInterval(refresh, 30_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!toastMessage) return undefined;
    const timeoutId = window.setTimeout(() => setToastMessage(""), 2500);
    return () => window.clearTimeout(timeoutId);
  }, [toastMessage]);

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
    setOriginInput("");
    setDestinationInput("");
    setScoreSource(null);
    setCityLoadingLabel(formatCityName(selectedCity));
    const locationToken = { ...locationSequence.current };

    fetchCityContext(selectedCity)
      .then((context) => {
        if (cancelled) return;

        const originUnchanged = locationSequence.current.origin === locationToken.origin;
        const destinationUnchanged = locationSequence.current.destination === locationToken.destination;
        if (originUnchanged) updateLocation("origin", context.origin);
        if (destinationUnchanged) updateLocation("destination", context.destination);
        if (originUnchanged && destinationUnchanged) setMapViewRequest({
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
  }, [selectedCity, updateLocation, serviceReloadKey]);

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
    let cancelled = false;

    const loadCoverageStatus = async () => {
      try {
        const status = await fetchCoverageStatus();
        if (!cancelled) setCoverageStatus(status);
      } catch {
        if (!cancelled) setCoverageStatus(null);
      }
    };

    void loadCoverageStatus();
    const intervalId = window.setInterval(loadCoverageStatus, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, []);

  useEffect(() => {
    if (!selectedCity || !origin || !destination) {
      setRouteSlots(buildRouteSlots("idle"));
      return undefined;
    }

    requestSequence.current += 1;
    const requestId = requestSequence.current;
    let cancelled = false;
    const controller = new AbortController();
    routeController.current = controller;
    const deadline = Date.now() + 10 * 60 * 1000;

    setError("");
    setRouteSlots(buildRouteSlots("loading"));
    setExplainedRouteId(null);
    setPreparingState(null);

    const loadStrategy = async (strategy: Strategy): Promise<RouteLoadResult> => {
      try {
        while (!cancelled && requestId === requestSequence.current) {
          if (Date.now() >= deadline) throw new Error("The road network is taking too long to load. Retry when the services are ready.");
          const response = await fetchRoute({
            city: selectedCity,
            origin,
            destination,
            strategy,
            vehicle: selectedVehicle,
          }, controller.signal);

          if (cancelled || requestId !== requestSequence.current) {
            return { status: "cancelled" };
          }

          if (isRouteLoadingResponse(response)) {
            const retryAfter = Math.max(1, response.retryAfter);
            if (retryAfter * 1000 > deadline - Date.now()) throw new Error("The road network is taking too long to load. Retry when the services are ready.");
            setPreparingState((current) => ({
              message: `Loading ${formatCityName(selectedCity)} road network... (first time ~60s)`,
              retryAt: Date.now() + retryAfter * 1000,
              startedAt: current?.startedAt ?? Date.now(),
            }));
            await sleep(retryAfter * 1000, controller.signal);
            continue;
          }

          const formattedRoute = formatRouteForUI(response, ROUTE_COLORS[strategy]);
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
            (result): result is PromiseFulfilledResult<Extract<RouteLoadResult, { status: "error" }>> =>
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
      controller.abort();
    };
  }, [selectedCity, origin, destination, selectedVehicle, routeReloadKey]);

  const editLocation = (target: LocationTarget, text: string) => {
    locationControllers.current[target]?.abort();
    locationSequence.current[target] += 1;
    routeController.current?.abort();
    requestSequence.current += 1;
    setRouteSlots(buildRouteSlots("idle"));
    setPreparingState(null);
    setResolvingTarget(null);
    if (target === "origin") { setOrigin(undefined); setOriginInput(text); }
    else { setDestination(undefined); setDestinationInput(text); }
  };

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

  return (
    <div className="relative h-dvh w-full overflow-hidden bg-black">
      <div className="relative h-full">
        <Suspense fallback={<div className="h-full w-full bg-black text-white" role="status">Loading map…</div>}>
        <MapView
          city={selectedCity}
          origin={origin}
          destination={destination}
          routes={routes}
          selectedRoute={selectedRoute}
          showHeatmap={showHeatmap}
          darkMode={darkMode}
          hotspots={hotspots}
          placementTarget={activeLocationTarget}
          viewRequest={mapViewRequest}
          onCoordinatePick={handleMapCoordinatePick}
          onViewportChange={handleViewportChange}
        />
        </Suspense>

        <div className="[&>div]:gap-2 [&>div>div:first-child]:hidden sm:[&>div>div:first-child]:block">
        <Header
          cities={cityList}
          selectedCity={selectedCity}
          darkMode={darkMode}
          onToggleDarkMode={() => setDarkMode((current) => !current)}
          onCitySelect={handleCityChange}
          onCityHover={handleCityHover}
        />
        </div>

        <div className="pointer-events-auto absolute left-4 right-4 top-[208px] z-[1200] group flex flex-row gap-1 rounded-2xl border border-white/10 bg-black/70 p-2 shadow-2xl backdrop-blur-xl lg:left-auto lg:right-0 lg:top-1/2 lg:w-12 lg:-translate-y-1/2 lg:flex-col lg:gap-2 lg:overflow-hidden lg:rounded-l-2xl lg:rounded-r-none lg:border-r-0 lg:bg-black/40 lg:hover:w-32">
          {VEHICLE_OPTIONS.map((option) => {
            const Icon = option.icon;
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => setSelectedVehicle(option.id)}
                aria-label={option.label}
                aria-pressed={selectedVehicle === option.id}
                className={`flex h-10 min-w-0 flex-1 items-center justify-center gap-1 rounded-xl border px-1.5 transition-colors lg:w-full lg:shrink-0 lg:justify-start lg:gap-3 ${
                  selectedVehicle === option.id
                    ? "border-sky-300/70 bg-sky-400/20 text-white"
                    : "border-transparent text-white/70 hover:bg-white/10 hover:text-white"
                }`}
              >
                <span className="flex w-5 shrink-0 items-center justify-center">
                  <Icon className="h-4 w-4" />
                </span>
                <span className="whitespace-nowrap text-xs font-medium tracking-wide lg:opacity-0 lg:transition-opacity lg:duration-300 lg:group-hover:opacity-100">
                  {option.label}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="pointer-events-auto absolute left-1/2 top-16 z-[1100] w-full max-w-2xl -translate-x-1/2 px-4 lg:top-4">
        <div className="rounded-2xl border border-white/10 bg-black/40 p-2 shadow-xl backdrop-blur-xl">
          <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
            <div
              className={`flex min-w-0 flex-1 items-center gap-2 rounded-xl px-3 py-2 ${
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
                onChange={(event) => editLocation("origin", event.target.value)}
                onKeyDown={(event) => handleLocationKeyDown("origin", event)}
                placeholder="Search origin or click map..."
                className="min-w-0 flex-1 bg-transparent text-sm text-white/80 outline-none placeholder:text-white/40"
                aria-label="Origin"
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

            <div className="hidden h-6 w-px bg-white/10 lg:block" />

            <div
              className={`flex min-w-0 flex-1 items-center gap-2 rounded-xl px-3 py-2 ${
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
                onChange={(event) => editLocation("destination", event.target.value)}
                onKeyDown={(event) => handleLocationKeyDown("destination", event)}
                placeholder="Search destination or click map..."
                className="min-w-0 flex-1 bg-transparent text-sm text-white/80 outline-none placeholder:text-white/40"
                aria-label="Destination"
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

      <div className="pointer-events-none absolute bottom-4 left-4 right-4 z-[1050] flex max-h-[43dvh] flex-col gap-2 lg:bottom-8 lg:right-auto lg:top-20 lg:max-h-none lg:w-[380px] lg:gap-3">
        <div className="pointer-events-auto shrink-0 rounded-2xl border border-white/10 bg-black/30 p-4 shadow-xl backdrop-blur-xl">
          <h3 className="mb-2 text-sm text-white lg:mb-4">Routing Priority</h3>
          <ConnectivitySlider value={connectivityWeight} onChange={setConnectivityWeight} />
        </div>

        <div className="pointer-events-auto flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-white/10 bg-black/30 p-4 shadow-xl backdrop-blur-xl">
          <h3 className="mb-3 shrink-0 text-sm text-white">Available Routes</h3>
          {predictionReady === false ? <p role="status" className="mb-2 text-xs text-amber-200">Prediction unavailable: routes may use retained or neutral estimates.</p> : null}

          {cityLoadingLabel ? (
            <div className="mb-3 shrink-0 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-white/75">
              Loading {cityLoadingLabel} network...
            </div>
          ) : null}

          {preparingState ? (
            <div className="mb-3 shrink-0 rounded-xl border border-sky-300/20 bg-sky-500/10 px-3 py-2 text-xs text-sky-100">
              <div>{preparingState.message}</div>
              <div className="mt-1 flex items-center justify-between gap-3 text-sky-100/70">
                <span>Elapsed {loadingElapsed}s</span>
                <span>Retrying in {retryCountdown ?? 0}s</span>
              </div>
            </div>
          ) : null}

          <div className="-mx-2 flex-1 space-y-2 overflow-y-auto p-2 transition-colors duration-300 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-transparent hover:[&::-webkit-scrollbar-thumb]:bg-white/20">
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
              <div className="mx-1 rounded-xl border border-white/10 bg-white/5 px-3 py-3 text-xs text-white/60">
                Set origin and destination to load routes.
              </div>
            )}

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
        <div className="pointer-events-none absolute bottom-10 left-1/2 z-[1300] hidden w-full max-w-md -translate-x-1/2 px-4 lg:block">
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

      <div className="absolute right-4 top-[276px] z-[1040] max-w-[calc(100%-2rem)] space-y-3 lg:bottom-10 lg:top-auto lg:max-w-md">
        <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-black/30 px-3 py-2 backdrop-blur-xl">
          <span className="text-sm text-white">Heatmap</span>
          <button
            type="button"
            onClick={() => setShowHeatmap((current) => !current)}
            aria-label="Toggle heatmap"
            aria-pressed={showHeatmap}
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

        <div className="hidden lg:block"><Legend /></div>

        {selectedRouteData?.signalDataLabel || scoreSource ? (
          <div
            className={`hidden rounded-xl border px-3 py-2 text-xs backdrop-blur-xl lg:block ${
              activeRealDataCoveragePercent > 0
                ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-100"
                : "border-amber-300/30 bg-amber-500/10 text-amber-100"
            }`}
          >
            Signal data: {selectedRouteData?.signalDataLabel ?? scoreSourceLabel(scoreSource)}
            <span className="ml-2 text-[11px] opacity-80">
              {Math.round(activeRealDataCoveragePercent)}% provider-backed · {Math.round(activeGoodSignalPercent)}% good estimate
            </span>
          </div>
        ) : null}

        {error ? (
          <div className="rounded-xl border border-rose-300/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-100">
            {error}
            {!hasRouteInputs ? <button type="button" onClick={() => setServiceReloadKey((value) => value + 1)} className="ml-2 underline">Retry services</button> : null}
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
