import Link from "next/link";
import { AlertTriangle, ArrowLeft } from "lucide-react";
import { getPortfolioOverlap, type PortfolioOverlapItem } from "@/api/client";
import { Button } from "@/components/ui/button";
import { PortfolioOverlapAlert } from "@/components/disclosure-feed/PortfolioOverlapAlert";
import { SiteNav } from "@/components/SiteNav";

export const dynamic = "force-dynamic";

export default async function CongressionalOverlapPage() {
  const result = await loadOverlap();
  const activeMembers = new Set(
    result.overlap.flatMap((item) =>
      item.disclosures.map((disclosure) => disclosure.memberId),
    ),
  ).size;

  return (
    <main className="min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-border pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
              <Link href="/congressional">
                <ArrowLeft className="h-4 w-4" />
                Feed
              </Link>
            </Button>
            <p className="text-sm text-muted-foreground">Congressional</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-normal text-foreground">
              Portfolio Overlap
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Congressional disclosures touching tickers currently held in your portfolio.
            </p>
          </div>
          <SiteNav />
        </header>

        {result.error ? (
          <section className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive-foreground">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4" />
              <span>{result.error}</span>
            </div>
          </section>
        ) : null}

        <section className="grid gap-3 sm:grid-cols-3">
          <Kpi label="Held tickers with activity" value={String(result.overlap.length)} />
          <Kpi label="Active members" value={String(activeMembers)} />
          <Kpi
            label="Matching disclosures"
            value={String(
              result.overlap.reduce((total, item) => total + item.disclosures.length, 0),
            )}
          />
        </section>

        <section className="grid gap-4">
          {result.overlap.map((overlap) => (
            <PortfolioOverlapAlert key={overlap.symbol} overlap={overlap} />
          ))}
          {!result.error && result.overlap.length === 0 ? (
            <section className="rounded-md border border-border bg-card p-8 text-center text-sm text-muted-foreground">
              No Congressional disclosures currently overlap with held positions.
            </section>
          ) : null}
        </section>
      </div>
    </main>
  );
}

async function loadOverlap(): Promise<{
  overlap: PortfolioOverlapItem[];
  error?: string;
}> {
  try {
    return { overlap: await getPortfolioOverlap() };
  } catch (error) {
    return {
      overlap: [],
      error: error instanceof Error ? error.message : "Unable to load overlap data.",
    };
  }
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <div className="text-xs uppercase tracking-normal text-muted-foreground">
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-normal text-foreground">
        {value}
      </div>
    </div>
  );
}
