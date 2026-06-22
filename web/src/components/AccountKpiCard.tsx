import { Card } from "@tremor/react";
import { cn } from "@/lib/utils";

type AccountKpiCardProps = {
  label: string;
  value: string;
  trend?: number;
  live?: boolean;
};

export function AccountKpiCard({ label, value, trend, live = false }: AccountKpiCardProps) {
  const hasTrend = typeof trend === "number";
  const positive = hasTrend && trend >= 0;

  return (
    <Card className="rounded-md border border-border bg-card p-4 shadow-none ring-0">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">{label}</p>
        {live ? (
          <span className="inline-flex items-center gap-1 rounded-sm border border-emerald-400/30 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-400">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            LIVE
          </span>
        ) : null}
      </div>
      <p className="mt-2 truncate text-2xl font-semibold tracking-normal text-foreground">
        {value}
      </p>
      {hasTrend ? (
        <p
          className={cn(
            "mt-2 text-xs font-medium",
            positive ? "text-emerald-400" : "text-rose-400",
          )}
        >
          {positive ? "Positive" : "Negative"} unrealized move
        </p>
      ) : null}
    </Card>
  );
}
