import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import {
  getCongressionalDisclosures,
  type CongressionalDisclosure,
} from "@/api/client";
import { Button } from "@/components/ui/button";
import { DisclosureCard } from "@/components/disclosure-feed/DisclosureCard";
import {
  FilterBar,
  type CongressionalFilters,
} from "@/components/disclosure-feed/FilterBar";
import { SiteNav } from "@/components/SiteNav";

export const dynamic = "force-dynamic";

type CongressionalPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function CongressionalPage({ searchParams }: CongressionalPageProps) {
  const params = await searchParams;
  const filters = getFilters(params);
  const result = await loadDisclosures(filters);

  return (
    <main className="min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-border pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-sm text-muted-foreground">Congressional</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-normal text-foreground">
              Disclosure Feed
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              STOCK Act filings matched with member context and disclosure lag.
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <SiteNav />
            <Button asChild>
              <Link href="/congressional/overlap">Portfolio overlap</Link>
            </Button>
          </div>
        </header>

        <FilterBar filters={filters} />

        {result.error ? (
          <section className="rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive-foreground">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4" />
              <span>{result.error}</span>
            </div>
          </section>
        ) : null}

        <section className="grid gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold tracking-normal text-foreground">
              {result.disclosures.length} disclosures
            </h2>
            <p className="text-sm text-muted-foreground">
              Sorted by{" "}
              {filters.sort === "transaction_date" ? "transaction date" : "disclosure date"}
            </p>
          </div>
          {result.disclosures.map((disclosure) => (
            <DisclosureCard key={disclosure.filingId} disclosure={disclosure} />
          ))}
          {!result.error && result.disclosures.length === 0 ? (
            <section className="rounded-md border border-border bg-card p-8 text-center text-sm text-muted-foreground">
              No disclosures match the current filters.
            </section>
          ) : null}
        </section>
      </div>
    </main>
  );
}

function getFilters(
  params: Record<string, string | string[] | undefined>,
): CongressionalFilters {
  return {
    member: stringParam(params.member),
    symbol: stringParam(params.symbol).toUpperCase(),
    since: stringParam(params.since),
    chamber: stringParam(params.chamber) || "all",
    sort: stringParam(params.sort) || "disclosure_date",
  };
}

async function loadDisclosures(filters: CongressionalFilters): Promise<{
  disclosures: CongressionalDisclosure[];
  error?: string;
}> {
  try {
    const disclosures = await getCongressionalDisclosures({
      member: filters.member,
      symbol: filters.symbol,
      since: filters.since,
      limit: 100,
    });
    return {
      disclosures: sortDisclosures(filterByChamber(disclosures, filters.chamber), filters.sort),
    };
  } catch (error) {
    return {
      disclosures: [],
      error: error instanceof Error ? error.message : "Unable to load disclosures.",
    };
  }
}

function filterByChamber(
  disclosures: CongressionalDisclosure[],
  chamber: string,
): CongressionalDisclosure[] {
  if (!chamber || chamber === "all") {
    return disclosures;
  }
  return disclosures.filter((disclosure) => disclosure.member?.chamber === chamber);
}

function sortDisclosures(
  disclosures: CongressionalDisclosure[],
  sort: string,
): CongressionalDisclosure[] {
  const field = sort === "transaction_date" ? "transactionDate" : "disclosureDate";
  return [...disclosures].sort(
    (a, b) => new Date(b[field]).getTime() - new Date(a[field]).getTime(),
  );
}

function stringParam(value: string | string[] | undefined): string {
  return typeof value === "string" ? value : "";
}
