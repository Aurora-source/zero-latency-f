const MODE_META = {
  fastest: {
    label: "Fastest",
    subtitle: "Lowest ETA",
    color: "#1976D2",
  },
  connected: {
    label: "Connected",
    subtitle: "Best signal coverage",
    color: "#388E3C",
  },
  balanced: {
    label: "Balanced",
    subtitle: "ETA plus connectivity",
    color: "#7B1FA2",
  },
};

export default function RoutePanel({ loading, routes, selectedMode, onSelect }) {
  return (
    <section>
      <div className="mb-4">
        <p className="font-mono text-xs uppercase tracking-[0.3em] text-slate-500">
          Route Options
        </p>
        <p className="mt-2 text-sm text-slate-600">
          Click a route card to emphasize that path on the map.
        </p>
      </div>

      <div className="space-y-3">
        {Object.entries(MODE_META).map(([mode, meta]) => {
          const route = routes[mode];
          const isActive = selectedMode === mode;

          return (
            <button
              key={mode}
              type="button"
              onClick={() => route && onSelect(mode)}
              className={`w-full rounded-[24px] border p-4 text-left transition ${
                isActive
                  ? "border-slate-900 bg-slate-900 text-white shadow-lg"
                  : "border-slate-200 bg-white text-slate-900 hover:border-slate-300 hover:bg-slate-50"
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3">
                  <span
                    className="mt-1 h-3 w-3 rounded-full"
                    style={{ backgroundColor: meta.color }}
                  />
                  <div>
                    <p className="text-lg font-semibold">{meta.label}</p>
                    <p className={`text-sm ${isActive ? "text-white/75" : "text-slate-500"}`}>
                      {meta.subtitle}
                    </p>
                  </div>
                </div>
                <span
                  className={`rounded-full px-3 py-1 text-[11px] font-mono uppercase tracking-[0.24em] ${
                    isActive
                      ? "bg-white/15 text-white"
                      : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {isActive ? "Active" : "Show"}
                </span>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3">
                <div className={`rounded-2xl p-3 ${isActive ? "bg-white/10" : "bg-slate-50"}`}>
                  <p className={`font-mono text-[11px] uppercase tracking-[0.24em] ${isActive ? "text-white/70" : "text-slate-500"}`}>
                    ETA
                  </p>
                  <p className="mt-2 text-xl font-semibold">
                    {route ? `${route.total_time_min.toFixed(1)} min` : loading ? "Loading" : "-"}
                  </p>
                </div>

                <div className={`rounded-2xl p-3 ${isActive ? "bg-white/10" : "bg-slate-50"}`}>
                  <p className={`font-mono text-[11px] uppercase tracking-[0.24em] ${isActive ? "text-white/70" : "text-slate-500"}`}>
                    Connectivity
                  </p>
                  <p className="mt-2 text-xl font-semibold">
                    {route ? route.avg_connectivity.toFixed(2) : loading ? "Loading" : "-"}
                  </p>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
