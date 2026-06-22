import createClient from "openapi-fetch";
import type { components, paths } from "@/api/generated/schema";

export type AccountSnapshot = components["schemas"]["AccountSnapshot"];
export type PositionSnapshot = components["schemas"]["PositionSnapshot"];
export type RefreshPortfolioResponse =
  components["schemas"]["RefreshPortfolioResponse"];
export type CongressionalDisclosure =
  components["schemas"]["DisclosureSummary"];
export type CongressionalDisclosureDetail =
  components["schemas"]["DisclosureDetail"];
export type CongressionalMember = components["schemas"]["MemberSummary"];
export type CongressionalMemberDetail = components["schemas"]["MemberDetail"];
export type PortfolioOverlapItem =
  components["schemas"]["PortfolioOverlapItem"];

export type DisclosureFilters = {
  member?: string;
  symbol?: string;
  since?: string;
  limit?: number;
};

// Next.js standalone inlines process.env at build time, so runtime k8s
// env vars (TRACKER_API_SERVICE_HOST) aren't available to server components.
// Instead, we read the env var via a runtime-friendly approach: on the
// server side in production (standalone), default to the k8s internal DNS.
function resolveApiBaseUrl(): string {
  if (typeof window !== "undefined") {
    return (
      process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
      "http://localhost:8001"
    );
  }
  // Server-side. Try runtime env first (works if Next reads it at request time).
  const internal = process.env.API_INTERNAL_URL?.replace(/\/$/, "");
  if (internal) return internal;
  const svcHost = process.env.TRACKER_API_SERVICE_HOST;
  if (svcHost) {
    return `http://${svcHost}:8001`;
  }
  // In k8s production, the internal DNS name always works.
  // This is the reliable fallback for standalone Next.js.
  if (process.env.NODE_ENV === "production") {
    return "http://tracker-api:8001";
  }
  return (
    process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
    "http://localhost:8001"
  );
}

const apiBaseUrl = resolveApiBaseUrl();

const noStoreFetch: typeof fetch = (input, init) =>
  fetch(input, {
    ...init,
    cache: "no-store",
  });

export const apiClient = createClient<paths>({
  baseUrl: apiBaseUrl,
  fetch: noStoreFetch,
});

export async function getPortfolio(
  accountId: string,
  options: { live?: boolean } = {},
): Promise<AccountSnapshot> {
  const { data, error, response } = await apiClient.GET("/portfolio/{account_id}", {
    params: {
      path: {
        account_id: accountId,
      },
      query: options.live ? { live: true } : undefined,
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

export async function getCongressionalDisclosures(
  filters: DisclosureFilters = {},
): Promise<CongressionalDisclosure[]> {
  const { data, error, response } = await apiClient.GET("/congressional/disclosures", {
    params: {
      query: pruneEmpty(filters),
    },
  });

  if (error || !data) {
    throw new Error(formatApiError("congressional disclosures", "feed", response.status, error));
  }

  return data;
}

export async function getCongressionalDisclosure(
  filingId: string,
): Promise<CongressionalDisclosureDetail> {
  const { data, error, response } = await apiClient.GET(
    "/congressional/disclosures/{filing_id}",
    {
      params: {
        path: {
          filing_id: filingId,
        },
      },
    },
  );

  if (error || !data) {
    throw new Error(formatApiError("congressional disclosure", filingId, response.status, error));
  }

  return data;
}

export async function getCongressionalMembers(): Promise<CongressionalMember[]> {
  const { data, error } = await apiClient.GET("/congressional/members", {});

  if (error || !data) {
    throw new Error("congressional members failed for list");
  }

  return data;
}

export async function getCongressionalMember(
  memberId: string,
): Promise<CongressionalMemberDetail> {
  const { data, error, response } = await apiClient.GET(
    "/congressional/members/{member_id}",
    {
      params: {
        path: {
          member_id: memberId,
        },
      },
    },
  );

  if (error || !data) {
    throw new Error(formatApiError("congressional member", memberId, response.status, error));
  }

  return data;
}

export async function getPortfolioOverlap(
  limit = 100,
): Promise<PortfolioOverlapItem[]> {
  const { data, error, response } = await apiClient.GET(
    "/congressional/portfolio-overlap",
    {
      params: {
        query: { limit },
      },
    },
  );

  if (error || !data) {
    throw new Error(formatApiError("portfolio overlap", "congressional", response.status, error));
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

function pruneEmpty(filters: DisclosureFilters) {
  return Object.fromEntries(
    Object.entries(filters).filter(([, value]) => value !== undefined && value !== ""),
  );
}
