import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RouteCard from "../app/components/RouteCard";
import type { FormattedRoute } from "../app/lib/api";

const route: FormattedRoute = {
  id: 0,
  strategy: "connected",
  vehicle: "car",
  label: "Most Connected",
  time: "20.0 min",
  distance: "8.4 km",
  connectivity: 0.85,
  color: "#10b981",
  coordinates: [[12.9716, 77.5946]],
  segments: [],
  signalSegments: [],
  signalSource: "Hybrid",
  provenanceSource: "hybrid",
  towerCount: 12,
  routeSignalPercent: 85,
  realDataCoveragePercent: 50,
  goodSignalPercent: 75,
  signalDataLabel: "Hybrid real and estimated data (12 towers in corridor)",
  explanation: {
    summary: "Prioritizes reliable coverage.",
    factors: [],
    score_breakdown: { connectivity: 0.8, speed: 0.5, risk: 0.2 },
  },
};

describe("RouteCard", () => {
  it("renders route metrics and wires selection and explanation actions", () => {
    const onClick = vi.fn();
    const onToggleExplain = vi.fn();

    const { rerender } = render(
      <RouteCard
        route={route}
        isSelected
        isExplainOpen={false}
        onClick={onClick}
        onToggleExplain={onToggleExplain}
        delay={0}
      />,
    );

    expect(screen.getByText("20.0 min")).toBeInTheDocument();
    expect(screen.getByText("8.4 km")).toBeInTheDocument();
    expect(screen.getByText("85%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Most Connected/i }));
    fireEvent.click(screen.getByRole("button", { name: /Explain/i }));
    expect(onClick).toHaveBeenCalledOnce();
    expect(onToggleExplain).toHaveBeenCalledOnce();

    rerender(
      <RouteCard
        route={route}
        isSelected
        isExplainOpen
        onClick={onClick}
        onToggleExplain={onToggleExplain}
        delay={0}
      />,
    );
    expect(screen.getByText("Prioritizes reliable coverage.")).toBeInTheDocument();
  });
});
