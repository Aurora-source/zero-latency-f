import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import CitySelector from "./CitySelector";

interface HeaderProps {
  cities: string[];
  selectedCity: string | null;
  darkMode: boolean;
  onToggleDarkMode: () => void;
  onCitySelect: (city: string) => void;
  onCityHover?: (city: string) => void;
}

function Clock() {
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
    const intervalId = window.setInterval(updateTime, 1000);
    return () => window.clearInterval(intervalId);
  }, []);

  return (
    <div className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm font-medium text-white backdrop-blur-xl">
      {time}
    </div>
  );
}

export default function Header({
  cities,
  selectedCity,
  darkMode,
  onToggleDarkMode,
  onCitySelect,
  onCityHover,
}: HeaderProps) {
  return (
    <div className="pointer-events-auto absolute right-4 top-4 z-[1200] flex flex-wrap items-center justify-end gap-3">
      <Clock />
      <CitySelector
        cities={cities}
        selectedCity={selectedCity}
        onSelect={onCitySelect}
        onHover={onCityHover}
      />
      <button
        type="button"
        onClick={onToggleDarkMode}
        className="flex items-center justify-center rounded-xl border border-white/10 bg-black/40 px-3 py-2 backdrop-blur-xl"
        aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"}
      >
        {darkMode ? (
          <Sun className="h-5 w-5 text-yellow-300" />
        ) : (
          <Moon className="h-5 w-5 text-blue-300" />
        )}
      </button>
    </div>
  );
}
