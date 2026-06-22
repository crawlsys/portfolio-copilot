import { AccountDashboard } from "@/components/AccountDashboard";
import { getPortfolio } from "@/api/client";
import { getAccountOptions } from "@/lib/accounts";

export const dynamic = "force-dynamic";

type HomePageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function HomePage({ searchParams }: HomePageProps) {
  const accounts = getAccountOptions();
  const params = await searchParams;
  const requestedAccountId =
    typeof params.account === "string" ? params.account : accounts[0]?.id;
  const result = await loadFirstAvailablePortfolio(requestedAccountId, accounts.map((a) => a.id));

  return (
    <AccountDashboard
      accounts={accounts}
      selectedAccountId={result.accountId ?? requestedAccountId ?? ""}
      snapshot={result.snapshot}
      error={result.error}
    />
  );
}

async function loadFirstAvailablePortfolio(
  requestedAccountId: string | undefined,
  accountIds: string[],
) {
  const candidates = [
    requestedAccountId,
    ...accountIds.filter((accountId) => accountId !== requestedAccountId),
  ].filter((accountId): accountId is string => Boolean(accountId));

  let lastError = "No accounts configured.";
  for (const accountId of candidates) {
    try {
      return {
        accountId,
        snapshot: await getPortfolio(accountId),
        error: undefined,
      };
    } catch (error) {
      lastError = error instanceof Error ? error.message : "Unable to load portfolio.";
    }
  }

  return {
    accountId: requestedAccountId,
    snapshot: undefined,
    error: lastError,
  };
}
