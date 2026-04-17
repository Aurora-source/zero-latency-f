export default function CitySelector({ city, cities, onChange }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <label
        htmlFor="city-selector"
        className="font-mono text-[11px] uppercase tracking-[0.28em] text-slate-500"
      >
        Active City
      </label>
      <div className="mt-3">
        <select
          id="city-selector"
          value={city}
          onChange={(event) => onChange(event.target.value)}
          className="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-base font-medium text-slate-900 outline-none transition focus:border-slate-400 focus:bg-white"
        >
          {Object.entries(cities).map(([value, config]) => (
            <option key={value} value={value}>
              {config.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
