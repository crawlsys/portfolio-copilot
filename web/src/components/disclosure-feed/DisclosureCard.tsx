import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowRight, CalendarDays, Clock3 } from "lucide-react";
import type { CongressionalDisclosure } from "@/api/client";
import { formatAmountRange, formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { MemberBadge } from "@/components/congressional/MemberBadge";

type DisclosureCardProps = {
  disclosure: CongressionalDisclosure;
  compact?: boolean;
};

const transactionStyles: Record<string, string> = {
  BUY: "border-emerald-400/40 bg-emerald-400/10 text-emerald-200",
  PURCHASE: "border-emerald-400/40 bg-emerald-400/10 text-emerald-200",
  SELL: "border-rose-400/40 bg-rose-400/10 text-rose-200",
  SALE: "border-rose-400/40 bg-rose-400/10 text-rose-200",
  EXCHANGE: "border-border bg-secondary text-secondary-foreground",
};

export function DisclosureCard({ disclosure, compact = false }: DisclosureCardProps) {
  const member = disclosure.member;
  const transactionClass =
    transactionStyles[disclosure.transactionType.toUpperCase()] ??
    "border-border bg-secondary text-secondary-foreground";

  return (
    <article className="rounded-md border border-border bg-card p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-3">
          <MemberBadge
            name={disclosure.memberName}
            party={member?.party ?? "Unknown"}
            chamber={member?.chamber ?? "congress"}
            state={member?.state}
          />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href={`/congressional/${encodeURIComponent(disclosure.filingId)}`}
                className="text-xl font-semibold tracking-normal text-foreground hover:text-primary"
              >
                {disclosure.symbol ?? "Unlisted"}
              </Link>
              <span
                className={cn(
                  "rounded-md border px-2 py-0.5 text-xs font-semibold",
                  transactionClass,
                )}
              >
                {disclosure.transactionType}
              </span>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {disclosure.assetDescription}
            </p>
          </div>
        </div>

        <div className="text-left sm:text-right">
          <div className="text-sm font-medium text-foreground">
            {formatAmountRange(disclosure.amountRangeLow, disclosure.amountRangeHigh)}
          </div>
          <Link
            href={`/congressional/${encodeURIComponent(disclosure.filingId)}`}
            className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:text-primary/80"
          >
            Details
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </div>

      <div
        className={cn(
          "mt-4 grid gap-3 border-t border-border pt-4 text-sm sm:grid-cols-3",
          compact && "sm:grid-cols-2",
        )}
      >
        <DateStat
          icon={<CalendarDays className="h-4 w-4" />}
          label="Transaction"
          value={formatDate(disclosure.transactionDate)}
        />
        <DateStat
          icon={<CalendarDays className="h-4 w-4" />}
          label="Disclosed"
          value={formatDate(disclosure.disclosureDate)}
        />
        {!compact ? (
          <DateStat
            icon={<Clock3 className="h-4 w-4" />}
            label="Lag"
            value={`${disclosure.lagDays} days`}
          />
        ) : null}
      </div>
    </article>
  );
}

function DateStat({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2 text-muted-foreground">
      {icon}
      <div>
        <div className="text-xs uppercase tracking-normal">{label}</div>
        <div className="text-sm text-foreground">{value}</div>
      </div>
    </div>
  );
}
