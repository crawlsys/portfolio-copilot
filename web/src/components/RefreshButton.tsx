"use client";

import { useState, useTransition } from "react";
import { RefreshCw } from "lucide-react";
import { refreshPortfolioAction } from "@/app/actions";
import { Button } from "@/components/ui/button";

type RefreshButtonProps = {
  accountId: string;
};

export function RefreshButton({ accountId }: RefreshButtonProps) {
  const [isPending, startTransition] = useTransition();
  const [message, setMessage] = useState<string | null>(null);

  return (
    <div className="flex min-h-9 flex-col gap-1 sm:items-end">
      <Button
        type="button"
        variant="outline"
        disabled={isPending || !accountId}
        onClick={() => {
          setMessage(null);
          startTransition(async () => {
            try {
              const result = await refreshPortfolioAction(accountId);
              setMessage(`Refreshed ${result.refreshed_positions_count} positions`);
            } catch (error) {
              setMessage(error instanceof Error ? error.message : "Refresh failed");
            }
          });
        }}
      >
        <RefreshCw className={isPending ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
        Refresh
      </Button>
      {message ? <p className="max-w-80 text-xs text-muted-foreground">{message}</p> : null}
    </div>
  );
}
