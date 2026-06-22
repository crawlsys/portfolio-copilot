import type { AccountSnapshot } from "@/api/client";
import type { AccountOption } from "@/lib/accounts";
import { accountAsOf, totalUnrealizedPnl } from "@/lib/portfolio";
import { formatCurrency } from "@/lib/format";
import { AccountKpiCard } from "@/components/AccountKpiCard";
import { AccountSelector } from "@/components/AccountSelector";
import { HoldingsDonutChart } from "@/components/HoldingsDonutChart";
import { PositionsTable } from "@/components/PositionsTable";
import { RefreshButton } from "@/components/RefreshButton";

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
            <AccountSelector accounts={accounts} selectedAccountId={selectedAccountId} />
            {showRefresh ? <RefreshButton accountId={selectedAccountId} /> : null}
          </div>
        </header>

        {error ? (
          <section className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive-foreground">
            {error}
          </section>
        ) : null}

        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <AccountKpiCard
            label="Net Liquidation"
            value={formatCurrency(snapshot?.netLiquidation ?? 0)}
          />
          <AccountKpiCard label="Cash" value={formatCurrency(snapshot?.cash ?? 0)} />
          <AccountKpiCard
            label="Market Value"
            value={formatCurrency(snapshot?.marketValue ?? 0)}
          />
          <AccountKpiCard
            label="Day P/L"
            value={formatCurrency(aggregatePnl)}
            trend={aggregatePnl}
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
