import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { getCongressionalDisclosure } from "@/api/client";
import {
  formatAmountRange,
  formatCurrencyPrecise,
  formatDate,
} from "@/lib/format";
import { Button } from "@/components/ui/button";
import { DisclosureCard } from "@/components/disclosure-feed/DisclosureCard";
import { MemberBadge } from "@/components/congressional/MemberBadge";
import { SiteNav } from "@/components/SiteNav";

export const dynamic = "force-dynamic";

type DisclosureDetailPageProps = {
  params: Promise<{ filingId: string }>;
};

export default async function DisclosureDetailPage({
  params,
}: DisclosureDetailPageProps) {
  const { filingId } = await params;
  const disclosure = await loadDisclosure(filingId);

  if (!disclosure) {
    notFound();
  }

  const member = disclosure.member;

  return (
    <main className="min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-border pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
              <Link href="/congressional">
                <ArrowLeft className="h-4 w-4" />
                Feed
              </Link>
            </Button>
            <p className="text-sm text-muted-foreground">Disclosure</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-normal text-foreground">
              {disclosure.symbol ?? disclosure.assetDescription}
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Filed {formatDate(disclosure.disclosureDate)} · traded{" "}
              {formatDate(disclosure.transactionDate)}
            </p>
          </div>
          <SiteNav />
        </header>

        <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="grid gap-4">
            <section className="rounded-md border border-border bg-card p-5">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="space-y-3">
                  <MemberBadge
                    name={disclosure.memberName}
                    party={member?.party ?? "Unknown"}
                    chamber={member?.chamber ?? "congress"}
                    state={member?.state}
                  />
                  <div>
                    <h2 className="text-xl font-semibold tracking-normal text-foreground">
                      {disclosure.transactionType} ·{" "}
                      {formatAmountRange(disclosure.amountRangeLow, disclosure.amountRangeHigh)}
                    </h2>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {disclosure.assetDescription}
                    </p>
                  </div>
                </div>
                <div className="rounded-md border border-border bg-background p-3 text-sm">
                  <div className="text-muted-foreground">Current price</div>
                  <div className="mt-1 text-lg font-semibold text-foreground">
                    {disclosure.currentPrice
                      ? formatCurrencyPrecise(disclosure.currentPrice)
                      : "Unavailable"}
                  </div>
                </div>
              </div>

              <div className="mt-5 grid gap-3 border-t border-border pt-5 sm:grid-cols-3">
                <DetailStat label="Disclosure lag" value={`${disclosure.lagDays} days`} />
                <DetailStat
                  label="Portfolio"
                  value={disclosure.inPortfolio ? "Held" : "Not held"}
                />
                <DetailStat label="Filing ID" value={disclosure.filingId} />
              </div>
            </section>

            <section className="rounded-md border border-border bg-card p-5">
              <h2 className="text-base font-semibold tracking-normal text-foreground">
                Member
              </h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <DetailStat label="Party" value={member?.party ?? "Unknown"} />
                <DetailStat label="Chamber" value={member?.chamber ?? "Unknown"} />
                <DetailStat label="State" value={member?.state ?? "Unknown"} />
                <DetailStat
                  label="Committees"
                  value={
                    member?.committees.length ? member.committees.join(", ") : "None listed"
                  }
                />
              </div>
              <Button asChild variant="outline" size="sm" className="mt-4">
                <Link href={`/congressional?member=${encodeURIComponent(disclosure.memberId)}`}>
                  Other disclosures
                  <ExternalLink className="h-4 w-4" />
                </Link>
              </Button>
            </section>
          </div>

          <aside className="rounded-md border border-border bg-card p-4">
            <h2 className="text-base font-semibold tracking-normal text-foreground">
              Recent from this member
            </h2>
            <div className="mt-4 grid gap-3">
              {disclosure.recentMemberDisclosures.map((recent) => (
                <DisclosureCard key={recent.filingId} disclosure={recent} compact />
              ))}
              {disclosure.recentMemberDisclosures.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No other recent disclosures found.
                </p>
              ) : null}
            </div>
          </aside>
        </section>
      </div>
    </main>
  );
}

async function loadDisclosure(filingId: string) {
  try {
    return await getCongressionalDisclosure(filingId);
  } catch {
    return null;
  }
}

function DetailStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-normal text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 break-words text-sm font-medium text-foreground">{value}</div>
    </div>
  );
}
