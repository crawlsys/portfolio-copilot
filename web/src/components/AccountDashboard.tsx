import type { AccountSnapshot } from "@/api/client";
import type { AccountOption } from "@/lib/accounts";
import { accountAsOf, totalUnrealizedPnl } from "@/lib/portfolio";
import { formatCurrency } from "@/lib/format";
import { AccountKpiCard } from "@/components/AccountKpiCard";
import { AccountSelector } from "@/components/AccountSelector";
import { HoldingsDonutChart } from "@/components/HoldingsDonutChart";
import { PositionsTable } from "@/components/PositionsTable";
import { RefreshButton } from "@/components/RefreshButton";
import { SiteNav } from "@/components/SiteNav";

type AccountDashboardProps = {
  accounts: AccountOption[];
  selectedAccountId: string;
  snapshot?: AccountSnapshot;
  error?: string;
  showRefresh?: boolean;
};

export function AccountDashboard({
  accounts,
  selectedAccountId,
  snapshot,
  error,
  showRefresh = false,
}: AccountDashboardProps) {
  const positions = snapshot?.positions ?? [];
  const aggregatePnl = totalUnrealizedPnl(positions);
  const hasLiveValue = Boolean(snapshot?.liveNetLiquidation);
  const livePnl = snapshot?.liveDayPnl ? Number(snapshot.liveDayPnl) : undefined;
  const showLiveBadge = hasFreshLiveQuote(positions);
  const kpiGridClassName = hasLiveValue
    ? "grid gap-3 sm:grid-cols-2 xl:grid-cols-6"
    : "grid gap-3 sm:grid-cols-2 xl:grid-cols-5";

  return (
    <main className="min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-border pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-sm text-muted-foreground">Portfolio</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-normal text-foreground">
              Account Dashboard
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {snapshot ? accountAsOf(snapshot) : "Waiting for portfolio data"}
            </p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <SiteNav />
            <AccountSelector accounts={accounts} selectedAccountId={selectedAccountId} />
            {showRefresh ? <RefreshButton accountId={selectedAccountId} /> : null}
          </div>
        </header>

        {error ? (
          <section className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive-foreground">
            {error}
          </section>
        ) : null}

        <section className={kpiGridClassName}>
          {hasLiveValue ? (
            <AccountKpiCard
              label="Live Value"
              value={formatCurrency(snapshot?.liveNetLiquidation ?? 0)}
              live={showLiveBadge}
            />
          ) : null}
          <AccountKpiCard
            label={hasLiveValue ? "Statement Value" : "Net Liquidation"}
            value={formatCurrency(snapshot?.netLiquidation ?? 0)}
          />
          <AccountKpiCard label="Cash" value={formatCurrency(snapshot?.cash ?? 0)} />
          <AccountKpiCard
            label="Market Value"
            value={formatCurrency(snapshot?.marketValue ?? 0)}
          />
          <AccountKpiCard
            label="Day P/L"
            value={formatCurrency(livePnl ?? aggregatePnl)}
            trend={livePnl ?? aggregatePnl}
          />
          <AccountKpiCard
            label="Buying Power"
            value={formatCurrency(snapshot?.buyingPower ?? 0)}
          />
        </section>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <PositionsTable positions={positions} />
          <HoldingsDonutChart positions={positions} />
        </section>
      </div>
    </main>
  );
}

function hasFreshLiveQuote(positions: AccountSnapshot["positions"]): boolean {
  const newestQuoteAt = positions.reduce<number | undefined>((newest, position) => {
    if (!position.quoteTime) {
      return newest;
    }
    const timestamp = new Date(position.quoteTime).getTime();
    if (!Number.isFinite(timestamp)) {
      return newest;
    }
    return newest === undefined ? timestamp : Math.max(newest, timestamp);
  }, undefined);

  if (newestQuoteAt === undefined) {
    return false;
  }

  return Date.now() - newestQuoteAt <= 15 * 60 * 1000;
}
