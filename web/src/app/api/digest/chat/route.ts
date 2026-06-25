import type { NextRequest } from "next/server";

// Same-origin proxy for the digest chat. The browser POSTs here (trackdash),
// and we stream from the internal FastAPI service (tracker-api) — this avoids
// a cross-origin browser→API call, which would be blocked (the API sets no
// CORS). Mirrors the server-side base-URL resolution in src/api/client.ts.
export const dynamic = "force-dynamic";

function apiBaseUrl(): string {
  const internal = process.env.API_INTERNAL_URL?.replace(/\/$/, "");
  if (internal) return internal;
  const svcHost = process.env.TRACKER_API_SERVICE_HOST;
  if (svcHost) return `http://${svcHost}:8001`;
  return "http://tracker-api:8001";
}

export async function POST(req: NextRequest): Promise<Response> {
  const body = await req.text();

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl()}/digest/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
      cache: "no-store",
    });
  } catch {
    return new Response("data: \"[error: chat backend unreachable]\"\n\ndata: [DONE]\n\n", {
      status: 502,
      headers: { "content-type": "text/event-stream" },
    });
  }

  // Pipe the SSE stream straight through to the browser.
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "text/event-stream",
      "cache-control": "no-cache",
    },
  });
}
