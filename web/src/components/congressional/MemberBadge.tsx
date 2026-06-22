import { cn } from "@/lib/utils";

type MemberBadgeProps = {
  name: string;
  party: string;
  chamber: string;
  state?: string | null;
  className?: string;
};

const partyStyles: Record<string, string> = {
  democratic: "border-sky-400/40 bg-sky-400/10 text-sky-200",
  democrat: "border-sky-400/40 bg-sky-400/10 text-sky-200",
  republican: "border-rose-400/40 bg-rose-400/10 text-rose-200",
  independent: "border-amber-400/40 bg-amber-400/10 text-amber-100",
};

export function MemberBadge({
  name,
  party,
  chamber,
  state,
  className,
}: MemberBadgeProps) {
  const key = party.toLowerCase();
  const style =
    partyStyles[key] ?? "border-border bg-secondary text-secondary-foreground";
  const chamberLabel = chamber ? chamber[0]?.toUpperCase() + chamber.slice(1) : "Congress";

  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-2 rounded-md border px-2.5 py-1 text-xs font-medium",
        style,
        className,
      )}
    >
      <span className="truncate">{name}</span>
      <span className="shrink-0 text-muted-foreground">
        {partyLabel(party)} · {chamberLabel}
        {state ? ` · ${state}` : ""}
      </span>
    </span>
  );
}

function partyLabel(party: string): string {
  const normalized = party.toLowerCase();
  if (normalized.startsWith("dem")) {
    return "D";
  }
  if (normalized.startsWith("rep")) {
    return "R";
  }
  if (normalized.startsWith("ind")) {
    return "I";
  }
  return party.slice(0, 1).toUpperCase();
}
