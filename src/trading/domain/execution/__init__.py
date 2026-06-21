"""Execution context — STUB ONLY. Not implemented in v1.

This module exists to preserve type-level seams for the future. It defines
the lifecycle types (`OrderIntent`, `ExecutableOrder`, `Order`, `Fill`) but
does NOT implement any of the safety apparatus: no `ApprovalPort`, no
broker submit worker, no `find_recent_order_by_fingerprint`, no saga state
machine. None of these types is ever instantiated in v1.

WHY THIS IS DEFERRED
--------------------
An adversarial red team reviewed the academic evidence on
"copy-trade Congress after disclosure" and found the strategy has effectively
no alpha post-STOCK-Act (Huang & Xuan: 0.9%/yr gross, statistically
insignificant, before costs). Building execution infrastructure for an
unvalidated strategy is building safety apparatus around noise.

The user decided to defer the alpha question: build portfolio tooling and a
research surface now; validate any specific trading thesis via backtest
(spec §11) before adding execution.

WHAT'S PRESERVED
----------------
- The type names, so that when execution lands, downstream code (event catalog,
  OpenAPI schema, MCP tools, dashboard) already knows the shapes.
- The four candidate trading theses (spec §11) referenced from `theses.py`.
- The money-path red-team fixes (spec §10) so they're not rediscovered.

WHAT HAPPENS WHEN EXECUTION IS ACTIVATED
----------------------------------------
1. Implement `ApprovalPort` with the `ExecutableOrder` sealed type.
2. Implement `BrokerSubmitWorker` as a separate k8s Deployment with Schwab
   credentials the MCP pod cannot reach.
3. Apply every money-path fix in spec §10 — especially:
   - `find_recent_order_by_fingerprint` is a fiction; recovery defaults to
     "manual", pages user, freezes further live submissions.
   - Idempotency key derived from intent hash, not caller-supplied.
   - Re-check buying power inside the submit worker right before `place_order`.
   - PaperBroker needs chaos modes (partial fills, rejections, delays).
4. Apply every ops fix for OAuth operational story (spec §Schwab OAuth).
5. Re-run the red-team reviews against the new execution surface.

Until then, the `BrokerPort` protocol (in src/trading/adapters/ports/) exposes
read-only methods only. Trading methods are commented out as type-level seams.
"""
