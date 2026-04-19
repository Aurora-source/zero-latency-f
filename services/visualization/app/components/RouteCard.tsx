import { motion } from "framer-motion";
import { memo, useMemo } from "react";
import {
  ChevronDown,
  ChevronUp,
  Clock,
  Navigation2,
  Signal,
} from "lucide-react";
import type { FormattedRoute, Strategy } from "../lib/api";

interface RouteCardProps {
  route: FormattedRoute;
  isSelected: boolean;
  isExplainOpen: boolean;
  onClick: () => void;
  onToggleExplain: () => void;
  delay: number;
}

export function RouteCardSkeleton({
  label,
  delay,
}: {
  label: string;
  delay: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.25 }}
      className="route-card-shimmer w-full overflow-hidden rounded-xl border border-white/15 bg-white/5 p-3 backdrop-blur-md"
    >
      <div className="mb-3 flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-3 w-28 rounded-full bg-white/15" />
          <div className="h-2.5 w-16 rounded-full bg-white/10" />
        </div>
        <div className="h-6 w-6 rounded-full bg-white/10" />
      </div>

      <div className="mb-3 h-8 rounded-xl bg-white/10 px-3 py-2 text-xs text-white/45">
        {label}
      </div>

      <div className="space-y-2">
        <div className="h-2 rounded-full bg-white/10" />
        <div className="h-2 w-3/4 rounded-full bg-white/10" />
      </div>
    </motion.div>
  );
}

export function RouteCardError({
  label,
  message,
}: {
  label: string;
  message: string;
}) {
  return (
    <div className="w-full rounded-xl border border-rose-300/20 bg-rose-500/10 p-3 backdrop-blur-md">
      <div className="mb-1 text-sm font-semibold text-rose-100">{label}</div>
      <div className="text-xs text-rose-100/80">{message}</div>
    </div>
  );
}

export function routeLabelForStrategy(strategy: Strategy) {
  if (strategy === "connected") return "Most Connected";
  if (strategy === "balanced") return "Balanced";
  return "Fastest";
}

function colorWithAlpha(color: string, alpha: number) {
  const normalized = color.replace("#", "");
  if (normalized.length !== 6) {
    return color;
  }

  const red = Number.parseInt(normalized.slice(0, 2), 16);
  const green = Number.parseInt(normalized.slice(2, 4), 16);
  const blue = Number.parseInt(normalized.slice(4, 6), 16);
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function ScoreBar({
  label,
  value,
  colorClass,
}: {
  label: string;
  value: number;
  colorClass: string;
}) {
  const percentage = Math.round(value * 100);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px] text-white/70">
        <span>{label}</span>
        <span>{percentage}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/15">
        <div
          className={`h-full rounded-full ${colorClass}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

function RouteCardComponent({
  route,
  isSelected,
  isExplainOpen,
  onClick,
  onToggleExplain,
  delay,
}: RouteCardProps) {
  const connectivityPercentage = Math.round(route.connectivity * 100);
  const cardStyle = useMemo(
    () =>
      ({
        backgroundColor: colorWithAlpha(route.color, isSelected ? 0.15 : 0.1),
        borderColor: colorWithAlpha(route.color, isSelected ? 0.55 : 0.5),
        borderLeftColor: route.color,
        borderLeftWidth: isSelected ? "4px" : "1px",
      }) as const,
    [isSelected, route.color],
  );
  const navigationIconStyle = useMemo(
    () => ({ color: route.color }),
    [route.color],
  );
  const dividerStyle = useMemo(
    () => ({ borderTopColor: colorWithAlpha(route.color, isSelected ? 0.22 : 0.16) }),
    [isSelected, route.color],
  );
  const explainButtonStyle = useMemo(
    () => ({
      borderColor: colorWithAlpha(route.color, isSelected ? 0.28 : 0.2),
      backgroundColor: colorWithAlpha(route.color, isSelected ? 0.14 : 0.08),
    }),
    [isSelected, route.color],
  );

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.25 }}
      className={`w-full rounded-xl border p-3 transition-all duration-200 backdrop-blur-md ${
        isSelected ? "scale-[1.02] shadow-lg" : ""
      }`}
      style={cardStyle}
    >
      <button
        type="button"
        onClick={onClick}
        className="w-full text-left"
      >
        <div className="mb-2.5 flex items-start justify-between">
          <div className="flex items-center gap-2">
            <div
              className="h-3 w-3 rounded-full"
              style={{ backgroundColor: route.color }}
            />
            <span className={`text-sm font-semibold ${isSelected ? "text-white" : "text-white/55"}`}>
              {route.label}
            </span>
          </div>

          <Navigation2
            className={`h-3.5 w-3.5 ${
              isSelected ? "opacity-100" : "opacity-0"
            }`}
            style={navigationIconStyle}
          />
        </div>

        <div className={`mb-2.5 flex items-center gap-4 text-xs ${isSelected ? "text-white/80" : "text-white/50"}`}>
          <div className="flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5" />
            <span>{route.time}</span>
          </div>
          <div className={isSelected ? "text-white/45" : "text-white/30"}>|</div>
          <span>{route.distance}</span>
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between text-xs">
            <div className={`flex items-center gap-1.5 ${isSelected ? "text-white/75" : "text-white/50"}`}>
              <Signal className="h-3 w-3" />
              <span>Coverage</span>
            </div>
            <span className={`font-semibold ${isSelected ? "text-white" : "text-white/55"}`}>
              {connectivityPercentage}%
            </span>
          </div>

          <div className="h-1.5 overflow-hidden rounded-full bg-white/20">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${connectivityPercentage}%` }}
              transition={{ duration: 0.6 }}
              className="h-full rounded-full"
              style={{ backgroundColor: route.color }}
            />
          </div>
        </div>
      </button>

      <div
        className="mt-3 flex items-center justify-between gap-3 border-t pt-3"
        style={dividerStyle}
      >
        <span className={`text-[11px] ${isSelected ? "text-white/55" : "text-white/45"}`}>Route details</span>

        <button
          type="button"
          onClick={onToggleExplain}
          className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-medium transition ${
            isSelected ? "text-white" : "text-white/70"
          }`}
          style={explainButtonStyle}
        >
          Explain
          {isExplainOpen ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </button>
      </div>

      {isExplainOpen ? (
        <div className="mt-3 space-y-3 rounded-xl border border-white/10 bg-black/20 p-3">
          <p className="text-xs leading-5 text-white/85">
            {route.explanation.summary}
          </p>

          <div className="space-y-2">
            {route.explanation.factors.map((factor) => (
              <div
                key={`${route.id}-${factor.factor}`}
                className="flex items-start gap-2 rounded-lg bg-white/5 px-2.5 py-2"
              >
                <div
                  className={`mt-0.5 flex h-5 w-5 items-center justify-center rounded-full ${
                    factor.impact === "positive"
                      ? "bg-emerald-500/20 text-emerald-300"
                      : "bg-rose-500/20 text-rose-300"
                  }`}
                >
                  {factor.impact === "positive" ? (
                    <ChevronUp className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronDown className="h-3.5 w-3.5" />
                  )}
                </div>
                <div className="min-w-0">
                  <div className="text-xs font-semibold text-white/90">
                    {factor.factor}
                  </div>
                  <div className="text-[11px] leading-4 text-white/65">
                    {factor.detail}
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="space-y-2 rounded-lg bg-white/5 p-2.5">
            <ScoreBar
              label="Connectivity"
              value={route.explanation.score_breakdown.connectivity}
              colorClass="bg-emerald-400"
            />
            <ScoreBar
              label="Speed"
              value={route.explanation.score_breakdown.speed}
              colorClass="bg-sky-400"
            />
            <ScoreBar
              label="Risk"
              value={route.explanation.score_breakdown.risk}
              colorClass="bg-amber-400"
            />
          </div>
        </div>
      ) : null}
    </motion.div>
  );
}

const RouteCard = memo(
  RouteCardComponent,
  (prevProps, nextProps) =>
    prevProps.route === nextProps.route &&
    prevProps.isSelected === nextProps.isSelected &&
    prevProps.isExplainOpen === nextProps.isExplainOpen &&
    prevProps.delay === nextProps.delay,
);

RouteCard.displayName = "RouteCard";

export default RouteCard;
