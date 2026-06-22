import createClient from "openapi-fetch";
import type { components, paths } from "@/api/generated/schema";

export type AccountSnapshot = components["schemas"]["AccountSnapshot"];
export type PositionSnapshot = components["schemas"]["PositionSnapshot"];
export type RefreshPortfolioResponse =
  components["schemas"]["RefreshPortfolioResponse"];

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

const noStoreFetch: typeof fetch = (input, init) =>
  fetch(input, {
    ...init,
    cache: "no-store",
  });

export const apiClient = createClient<paths>({
  baseUrl: apiBaseUrl,
  fetch: noStoreFetch,
});

export async function getPortfolio(accountId: string): Promise<AccountSnapshot> {
  const { data, error, response } = await apiClient.GET("/portfolio/{account_id}", {
    params: {
      path: {
        account_id: accountId,
      },
    },
  });

  if (error || !data) {
    throw new Error(formatApiError("portfolio", accountId, response.status, error));
  }

  return data;
}

export async function refreshPortfolio(
  accountId: string,
): Promise<RefreshPortfolioResponse> {
  const { data, error, response } = await apiClient.POST(
    "/portfolio/{account_id}/refresh",
    {
      params: {
        path: {
          account_id: accountId,
        },
      },
    },
  );

  if (error || !data) {
    throw new Error(formatApiError("refresh", accountId, response.status, error));
  }

  return data;
}

function formatApiError(
  action: string,
  accountId: string,
  status: number,
  error: unknown,
) {
  if (typeof error === "object" && error && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    return `${action} failed for ${accountId}: ${String(detail)} (${status})`;
  }
  return `${action} failed for ${accountId} (${status})`;
}
