"use client";

import { DonutChart } from "@tremor/react";
import type { PositionSnapshot } from "@/api/client";
import { formatCurrency, parseDecimal } from "@/lib/format";

type HoldingsDonutChartProps = {
  positions: PositionSnapshot[];
};

const COLORS = ["cyan", "emerald", "amber", "rose", "indigo", "violet", "sky", "teal"];

export function HoldingsDonutChart({ positions }: HoldingsDonutChartProps) {
  const chartData = buildChartData(positions);

  return (
    <aside className="rounded-md border border-border bg-card p-4">
      <div className="mb-4">
        <h2 className="text-base font-semibold tracking-normal text-foreground">
          Top Holdings
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Largest positions by market value
        </p>
      </div>
      {chartData.length > 0 ? (
        <DonutChart
          data={chartData}
          category="value"
          index="name"
          valueFormatter={formatCurrency}
          colors={COLORS}
          className="h-72"
        />
      ) : (
        <div className="flex h-72 items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
          No holdings
        </div>
      )}
    </aside>
  );
}

function buildChartData(positions: PositionSnapshot[]) {
  const sorted = [...positions].sort(
    (a, b) => parseDecimal(b.marketValue) - parseDecimal(a.marketValue),
  );
  const top = sorted.slice(0, 7).map((position) => ({
    name: position.symbol,
    value: parseDecimal(position.marketValue),
  }));
  const otherValue = sorted
    .slice(7)
    .reduce((total, position) => total + parseDecimal(position.marketValue), 0);

  if (otherValue > 0) {
    top.push({ name: "Other", value: otherValue });
  }

  return top;
}
