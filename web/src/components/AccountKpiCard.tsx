import { Card } from "@tremor/react";
import { cn } from "@/lib/utils";

type AccountKpiCardProps = {
  label: string;
  value: string;
  trend?: number;
};

export function AccountKpiCard({ label, value, trend }: AccountKpiCardProps) {
  const hasTrend = typeof trend === "number";
  const positive = hasTrend && trend >= 0;

  return (
    <Card className="rounded-md border border-border bg-card p-4 shadow-none ring-0">
      <p className="text-sm text-muted-foreground">{label}</p>
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
