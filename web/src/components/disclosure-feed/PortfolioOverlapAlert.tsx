import type { PortfolioOverlapItem } from "@/api/client";
import { formatCurrencyPrecise, formatQuantity } from "@/lib/format";
import { DisclosureCard } from "@/components/disclosure-feed/DisclosureCard";

type PortfolioOverlapAlertProps = {
  overlap: PortfolioOverlapItem;
};

export function PortfolioOverlapAlert({ overlap }: PortfolioOverlapAlertProps) {
  const multipleMembers = overlap.memberCount > 1;

  return (
    <section className="rounded-md border border-border bg-card">
      <div className="flex flex-col gap-3 border-b border-border p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold tracking-normal text-foreground">
              {overlap.symbol}
            </h2>
            {multipleMembers ? (
              <span className="rounded-md border border-amber-400/40 bg-amber-400/10 px-2 py-0.5 text-xs font-medium text-amber-100">
                {overlap.memberCount} members active
              </span>
            ) : null}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {formatQuantity(overlap.position.quantity)} shares ·{" "}
            {formatCurrencyPrecise(overlap.position.marketValue)}
          </p>
        </div>
        <div className="text-sm text-muted-foreground">
          {overlap.disclosures.length} matching disclosures
        </div>
      </div>
      <div className="grid gap-3 p-4">
        {overlap.disclosures.map((disclosure) => (
          <DisclosureCard
            key={disclosure.filingId}
            disclosure={disclosure}
            compact
          />
        ))}
      </div>
    </section>
  );
}
