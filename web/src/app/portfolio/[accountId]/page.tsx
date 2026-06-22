import { AccountDashboard } from "@/components/AccountDashboard";
import { getPortfolio } from "@/api/client";
import { getAccountOptions } from "@/lib/accounts";

export const dynamic = "force-dynamic";

type PortfolioPageProps = {
  params: Promise<{
    accountId: string;
  }>;
};

export default async function PortfolioPage({ params }: PortfolioPageProps) {
  const { accountId } = await params;
  const accounts = getAccountOptions();

  try {
    const snapshot = await getPortfolio(accountId, { live: true });
    return (
      <AccountDashboard
        accounts={accounts}
        selectedAccountId={accountId}
        snapshot={snapshot}
        showRefresh
      />
    );
  } catch (error) {
    return (
      <AccountDashboard
        accounts={accounts}
        selectedAccountId={accountId}
        error={error instanceof Error ? error.message : "Unable to load portfolio."}
        showRefresh
      />
    );
  }
}
