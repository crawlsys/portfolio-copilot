import { NextResponse } from "next/server";

// Liveness/readiness endpoint for Kubernetes probes. Intentionally does NOT
// call the backend API so pod health stays decoupled from upstream latency or
// availability — probing the data-fetching homepage caused the pod to fail
// readiness (1s probe timeout vs. a 1-2s server-side API fetch) and 502.
export const dynamic = "force-static";

export function GET() {
  return NextResponse.json({ status: "ok" });
}
