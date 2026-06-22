"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronsUpDown, Search } from "lucide-react";
import type { PositionSnapshot } from "@/api/client";
import {
  formatCurrencyPrecise,
  formatPercent,
  formatPercentPoints,
  formatQuantity,
  parseDecimal,
} from "@/lib/format";
import { positionPnlPercent } from "@/lib/portfolio";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type PositionsTableProps = {
  positions: PositionSnapshot[];
};

type SortKey =
  | "symbol"
  | "quantity"
  | "averageCost"
  | "marketValue"
  | "livePrice"
  | "unrealizedPnl"
  | "pnlPercent"
  | "liveUnrealizedPnl"
  | "priceChangePct";

type SortState = {
  key: SortKey;
  direction: "asc" | "desc";
};

const columns: Array<{ key: SortKey; label: string; align?: "right" }> = [
  { key: "symbol", label: "Symbol" },
  { key: "quantity", label: "Quantity", align: "right" },
  { key: "averageCost", label: "Avg Cost", align: "right" },
  { key: "marketValue", label: "Market Value", align: "right" },
  { key: "livePrice", label: "Live Price", align: "right" },
  { key: "unrealizedPnl", label: "P/L ($)", align: "right" },
  { key: "pnlPercent", label: "P/L (%)", align: "right" },
  { key: "liveUnrealizedPnl", label: "Live P/L", align: "right" },
  { key: "priceChangePct", label: "Live P/L %", align: "right" },
];

export function PositionsTable({ positions }: PositionsTableProps) {
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<SortState>({
    key: "marketValue",
    direction: "desc",
  });

  const visiblePositions = useMemo(() => {
    const query = filter.trim().toLowerCase();
    const filtered = query
      ? positions.filter((position) =>
          [position.symbol, position.assetClass].some((value) =>
            value.toLowerCase().includes(query),
          ),
        )
      : positions;

    return [...filtered].sort((a, b) => {
      const left = sortValue(a, sort.key);
      const right = sortValue(b, sort.key);
      const result =
        typeof left === "string"
          ? left.localeCompare(String(right))
          : left - Number(right);

      return sort.direction === "asc" ? result : -result;
    });
  }, [filter, positions, sort]);

  function updateSort(key: SortKey) {
    setSort((current) => ({
      key,
      direction:
        current.key === key && current.direction === "desc" ? "asc" : "desc",
    }));
  }

  return (
    <section className="rounded-md border border-border bg-card">
      <div className="flex flex-col gap-3 border-b border-border p-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-base font-semibold tracking-normal text-foreground">
            Positions
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {visiblePositions.length} of {positions.length} holdings
          </p>
        </div>
        <label className="relative block w-full lg:w-72">
          <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter symbols"
            className="pl-8"
          />
        </label>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((column) => (
              <TableHead
                key={column.key}
                className={column.align === "right" ? "text-right" : undefined}
              >
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className={
                    column.align === "right"
                      ? "ml-auto px-1 text-muted-foreground"
                      : "-ml-2 px-1 text-muted-foreground"
                  }
                  onClick={() => updateSort(column.key)}
                >
                  {column.label}
                  <SortIcon active={sort.key === column.key} direction={sort.direction} />
                </Button>
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {visiblePositions.map((position) => {
            const pnl = parseDecimal(position.unrealizedPnl);
            const hasLivePrice = Boolean(position.livePrice);
            const livePnl = parseDecimal(position.liveUnrealizedPnl);
            const livePnlClassName = hasLivePrice
              ? livePnl >= 0
                ? "text-right tabular-nums text-emerald-400"
                : "text-right tabular-nums text-rose-400"
              : "text-right tabular-nums text-muted-foreground";
            const quoteTooltip = formatQuoteTooltip(position.quoteTime);
            return (
              <TableRow key={position.symbol}>
                <TableCell className="font-medium text-foreground">
                  <div>{position.symbol}</div>
                  <div className="text-xs font-normal text-muted-foreground">
                    {position.assetClass}
                  </div>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatQuantity(position.quantity)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatCurrencyPrecise(position.averageCost)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatCurrencyPrecise(position.marketValue)}
                </TableCell>
                <TableCell
                  className={
                    hasLivePrice
                      ? "text-right tabular-nums"
                      : "text-right tabular-nums text-muted-foreground"
                  }
                  title={quoteTooltip}
                >
                  {hasLivePrice ? formatCurrencyPrecise(position.livePrice ?? 0) : "—"}
                </TableCell>
                <TableCell
                  className={
                    pnl >= 0
                      ? "text-right tabular-nums text-emerald-400"
                      : "text-right tabular-nums text-rose-400"
                  }
                >
                  {formatCurrencyPrecise(position.unrealizedPnl)}
                </TableCell>
                <TableCell
                  className={
                    pnl >= 0
                      ? "text-right tabular-nums text-emerald-400"
                      : "text-right tabular-nums text-rose-400"
                  }
                >
                  {formatPercent(positionPnlPercent(position))}
                </TableCell>
                <TableCell
                  className={livePnlClassName}
                  title={quoteTooltip}
                >
                  {hasLivePrice
                    ? formatCurrencyPrecise(position.liveUnrealizedPnl ?? 0)
                    : "—"}
                </TableCell>
                <TableCell className={livePnlClassName} title={quoteTooltip}>
                  {hasLivePrice ? formatPercentPoints(position.priceChangePct) : "—"}
                </TableCell>
              </TableRow>
            );
          })}
          {visiblePositions.length === 0 ? (
            <TableRow>
              <TableCell colSpan={columns.length} className="h-28 text-center text-muted-foreground">
                No matching positions
              </TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>
    </section>
  );
}

function sortValue(position: PositionSnapshot, key: SortKey): string | number {
  if (key === "symbol") {
    return position.symbol;
  }
  if (key === "pnlPercent") {
    return positionPnlPercent(position);
  }
  return parseDecimal(position[key]);
}

function formatQuoteTooltip(value: string | null | undefined): string | undefined {
  if (!value) {
    return undefined;
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return `Quote ${new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed)}`;
}

function SortIcon({
  active,
  direction,
}: {
  active: boolean;
  direction: SortState["direction"];
}) {
  if (!active) {
    return <ChevronsUpDown className="h-3.5 w-3.5" />;
  }
  return direction === "asc" ? (
    <ArrowUp className="h-3.5 w-3.5" />
  ) : (
    <ArrowDown className="h-3.5 w-3.5" />
  );
}
