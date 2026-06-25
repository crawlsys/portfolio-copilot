import type { AccountSnapshot, PositionSnapshot } from "@/api/client";
import { parseDecimal } from "@/lib/format";

export function totalUnrealizedPnl(positions: PositionSnapshot[]): number {
  return positions.reduce(
    (total, position) => total + parseDecimal(position.unrealizedPnl),
    0,
  );
}

export function positionPnlPercent(position: PositionSnapshot): number {
  const quantity = parseDecimal(position.quantity);
  const averageCost = parseDecimal(position.averageCost);
  const costBasis = quantity * averageCost;

  if (costBasis === 0) {
    return 0;
  }

  return parseDecimal(position.unrealizedPnl) / costBasis;
}

export function accountAsOf(snapshot: AccountSnapshot): string {
  if (!snapshot.asOf) {
    return "As of latest broker snapshot";
  }

  return `As of ${new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(snapshot.asOf))}`;
}
