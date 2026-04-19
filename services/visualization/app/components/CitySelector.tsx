import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

interface CitySelectorProps {
  cities: string[];
  selectedCity: string | null;
  onSelect: (city: string) => void;
  onHover?: (city: string) => void;
}

function formatCityName(city: string) {
  return city.replace(/[_-]/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function CitySelector({
  cities,
  selectedCity,
  onSelect,
  onHover,
}: CitySelectorProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const selectedLabel = selectedCity ? formatCityName(selectedCity) : "Select city";

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!containerRef.current) return;
      if (containerRef.current.contains(event.target as Node)) return;
      setOpen(false);
    };

    window.addEventListener("pointerdown", handlePointerDown);
    return () => window.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  if (!cities.length) {
    return null;
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white backdrop-blur-xl"
      >
        <span>{selectedLabel}</span>
        <ChevronDown className={`h-4 w-4 transition ${open ? "rotate-180" : ""}`} />
      </button>

      {open ? (
        <div className="absolute right-0 top-full mt-2 min-w-[180px] rounded-2xl border border-white/10 bg-black/85 p-2 shadow-xl backdrop-blur-xl">
          {cities.map((city) => (
            <button
              key={city}
              type="button"
              onMouseEnter={() => onHover?.(city)}
              onFocus={() => onHover?.(city)}
              onClick={() => {
                onSelect(city);
                setOpen(false);
              }}
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
  );
}
