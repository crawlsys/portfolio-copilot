import Link from "next/link";
import { Newspaper } from "lucide-react";
import { getLatestDigest, getDigestForDate, getDigestDates } from "@/api/client";
import { SiteNav } from "@/components/SiteNav";

export const dynamic = "force-dynamic";

type DigestPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function fmtUsd(v: string | null): string | null {
  if (!v) return null;
  const n = Number(v);
  if (Number.isNaN(n)) return v;
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export default async function DigestPage({ searchParams }: DigestPageProps) {
  const params = await searchParams;
  const dateParam = typeof params.date === "string" ? params.date : undefined;

  const [digest, dates] = await Promise.all([
    dateParam ? getDigestForDate(dateParam) : getLatestDigest(),
    getDigestDates(),
  ]);

  return (
    <main className="min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-border pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Newspaper className="h-4 w-4" /> Daily Digest
            </p>
            <h1 className="mt-1 text-3xl font-semibold tracking-normal text-foreground">
              {digest ? digest.digestDate : "No digest yet"}
            </h1>
            {digest ? (
              <p className="mt-2 text-sm text-muted-foreground">
                {fmtUsd(digest.netLiquidation) ? `Book ${fmtUsd(digest.netLiquidation)} · ` : ""}
                {fmtUsd(digest.cashToDeploy) ? `${fmtUsd(digest.cashToDeploy)} cash to deploy · ` : ""}
                <span className="rounded-full border border-border px-2 py-0.5 text-xs text-accent-foreground">
                  {digest.model}
                </span>
              </p>
            ) : null}
          </div>
          <SiteNav />
        </header>

        {digest ? (
          <>
            <div className="rounded-xl border border-border border-l-4 border-l-primary bg-card p-4 text-sm text-foreground">
              <span className="font-semibold text-muted-foreground">Push summary: </span>
              {digest.pushExcerpt}
            </div>

            <article
              className="digest-prose"
              dangerouslySetInnerHTML={{ __html: digest.summaryHtml }}
            />

            {dates.length > 1 ? (
              <nav className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
                <span className="text-sm text-muted-foreground">Archive:</span>
                {dates.map((d) => (
                  <Link
                    key={d}
                    href={`/digest?date=${d}`}
                    className={`text-sm underline-offset-2 hover:underline ${
                      d === digest.digestDate ? "font-semibold text-foreground" : "text-accent-foreground"
                    }`}
                  >
                    {d}
                  </Link>
                ))}
              </nav>
            ) : null}
          </>
        ) : (
          <p className="text-muted-foreground">
            No digest has been generated yet. The daily digest runs at 7:00 AM ET.
          </p>
        )}
      </div>
    </main>
  );
}
