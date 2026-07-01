# Recommendation Ledger — Implementation Spec

**Status:** Ready to build · **Owner:** handoff to Claude/Fable
**Depends on:** existing digest pipeline (`generate_digest.py`), Schwab live broker
**Estimated effort:** 1 session (~3-5 hours)

---

## Problem

The daily digest LLM has **no memory of prior recommendations**. Each day it
sees the same static cash balance and invents a fresh deployment plan from
scratch, so advice drifts day-to-day with no continuity:

- Day 1: *"put $5,000 in VTI this week, the rest in 2-3 weeks"*
- Day 2: *"put $1,000 in VTI and the rest 2-3 weeks from now"* ← ignores Day 1
- Day 3: pivots to a different ticker entirely without acknowledging the prior plan

There is no structured persistence of recommendations, no detection of whether
they were acted on, and no feedback of prior advice into the next day's
prompt. The "Action of the Day" is currently **free-text markdown** with zero
lifecycle.

---

## Approved design

Three decisions were locked in with the user:

1. **Auto-detect acted-on from Schwab** (not manual). Compare active BUY
   recommendations against live position/cash deltas since issuance.
2. **Structured extraction** from a machine-readable block the LLM emits.
3. **LLM must explicitly call out pivots** — no silent superseding.

---

## Schema — `recommendations` table

New migration: `migrations/versions/0003_recommendations.py` (match the alembic
pattern in `migrations/versions/2026_06_24_0002_digests.py`).

Columns:
```python
class RecommendationRow(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        Index("ix_recommendations_status_date", "status", "digest_date"),
        Index("ix_recommendations_symbol", "symbol"),
    )

    recommendation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    digest_id: Mapped[str] = mapped_column(String(64), nullable=False)  # FK→digests.digest_id
    digest_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # The recommendation itself
    verb: Mapped[str] = mapped_column(String(16), nullable=False)   # BUY | HOLD
    symbol: Mapped[str | None] = mapped_column(String(32))          # null for HOLD
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    window: Mapped[str] = mapped_column(String(16), nullable=False) # this-week|2-3-weeks|this-month|immediate
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # computed from window
    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    # Lifecycle
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # active | acted_on | expired | superseded
    superseded_by: Mapped[str | None] = mapped_column(String(64))  # FK→recommendations
    acted_on_detail: Mapped[str | None] = mapped_column(Text)      # what the detector saw

    # Baseline snapshot for detection (captured at issue time)
    baseline_qty: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))  # ticker qty in self-directed acct
    baseline_cash: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False)
```

Add this model to `src/trading/adapters/persistence/models.py` (match the
existing style — see `DigestRow` at line 224).

---

## Structured extraction — the machine-readable block

The digest LLM is required to emit, after the human-readable "Action of the
Day" section, a parseable block:

```
<<<RECOMMENDATION>>>
verb: BUY
symbol: VTI
amount_usd: 5000
window: this-week
rationale: Defensive DCA entry, light equity weighting
supersedes: 2026-06-30
<<<END>>>
```

Rules:
- `supersedes:` is **optional** — present only when today's recommendation
  changes/cancels an active prior one (the date identifies which one).
- HOLD recommendations have `symbol`/`amount_usd` empty:
  ```
  <<<RECOMMENDATION>>>
  verb: HOLD
  window: immediate
  rationale: No action warranted — all positions within tolerance
  <<<END>>>
  ```
- If the block is malformed or missing → fall back to HOLD with a
  `"parse failed"` rationale. **Never lose the digest over a bad block.**

### Parser — `_parse_recommendation_block()`

Location: `src/trading/application/signals/generate_digest.py`

```python
import re

_REC_PATTERN = re.compile(
    r"<<<RECOMMENDATION>>>\s*\n(.*?)\n<<<END>>>", re.DOTALL
)

_WINDOW_DAYS = {
    "immediate": 1,
    "this-week": 7,
    "2-3-weeks": 21,
    "this-month": 30,
}

def _parse_recommendation_block(text: str, digest_date: datetime) -> ParsedRecommendation:
    """Extract the structured recommendation. Falls back to HOLD on any error."""
    m = _REC_PATTERN.search(text)
    if not m:
        return _hold_fallback("no recommendation block found")

    fields: dict[str, str] = {}
    for line in m.group(1).strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip().lower()] = val.strip()

    verb = fields.get("verb", "HOLD").upper()
    if verb not in ("BUY", "HOLD"):
        return _hold_fallback(f"unknown verb: {verb}")

    window = fields.get("window", "immediate").lower()
    if window not in _WINDOW_DAYS:
        window = "immediate"

    due_date = digest_date + timedelta(days=_WINDOW_DAYS[window])

    return ParsedRecommendation(
        verb=verb,
        symbol=fields.get("symbol") or None,
        amount_usd=Decimal(fields["amount_usd"]) if fields.get("amount_usd") else None,
        window=window,
        due_date=due_date,
        rationale=fields.get("rationale", "")[:500],
        supersedes_date=_parse_date(fields.get("supersedes")),
    )
```

---

## Auto-detect acted-on from Schwab

At the **start** of each digest run, for each active BUY recommendation:

1. Fetch the current live positions + cash for the **self-directed account**
   (`account_id` = the self-directed Schwab account hash — pass it in via
   settings/env `SELF_DIRECTED_ACCOUNT_ID`, e.g. `****3450`)
2. Compare to the `baseline_qty` / `baseline_cash` captured when the rec was issued
3. Detection rules (any one triggers `acted_on`):
   - The ticker's quantity grew by ≥ the target amount's worth (within ±15%
     tolerance — make `DETECTION_TOLERANCE = Decimal("0.15")` a module constant)
   - Cash dropped by ~the target amount (within ±15%)
4. On detection: set `status = acted_on`, record what was seen in
   `acted_on_detail` (e.g. *"VTI +12 shares (was 198, now 210), cash −$3,100"*)

```python
DETECTION_TOLERANCE = Decimal("0.15")

async def _detect_acted_on(
    session: AsyncSession,
    broker: BrokerPort,
    self_directed_account_id: str,
) -> list[RecommendationRow]:
    """Diff live positions/cash against baselines. Returns rows that were acted on."""
    active = (await session.scalars(
        select(RecommendationRow).where(
            RecommendationRow.status == "active",
            RecommendationRow.verb == "BUY",
        )
    )).all()
    if not active:
        return []

    positions = {p.symbol: p for p in await broker.get_positions(self_directed_account_id)}
    account = await broker.get_account(self_directed_account_id)
    current_cash = account.cash.amount

    acted_on = []
    for rec in active:
        triggered, detail = _check_one(rec, positions, current_cash)
        if triggered:
            rec.status = "acted_on"
            rec.acted_on_detail = detail
            acted_on.append(rec)
    return acted_on


def _check_one(rec, positions_by_sym, current_cash) -> tuple[bool, str]:
    """Return (was_acted_on, human_readable_detail)."""
    # Rule 1: quantity grew by ~target amount
    if rec.symbol and rec.symbol in positions_by_sym:
        pos = positions_by_sym[rec.symbol]
        qty_delta = pos.quantity - (rec.baseline_qty or 0)
        est_shares = (rec.amount_usd or 0) / (pos.average_cost or Decimal("1"))
        if qty_delta > 0:
            ratio = qty_delta / est_shares if est_shares > 0 else Decimal("0")
            if (Decimal("1") - DETECTION_TOLERANCE) <= ratio:
                return True, f"{rec.symbol} +{qty_delta} shares (est target {est_shares:.1f})"

    # Rule 2: cash dropped by ~target amount
    if rec.amount_usd and rec.baseline_cash is not None:
        cash_delta = rec.baseline_cash - current_cash
        ratio = cash_delta / rec.amount_usd
        if (Decimal("1") - DETECTION_TOLERANCE) <= ratio <= (Decimal("1") + DETECTION_TOLERANCE):
            return True, f"cash −${cash_delta:,.2f} (target ${rec.amount_usd:,.2f})"

    return False, ""
```

---

## Prompt continuity

### Context injection

Before the LLM call, query open recommendations and inject them into context:

```python
async def _build_continuity_context(session: AsyncSession, today: datetime) -> str:
    """Build the OPEN RECOMMENDATIONS / ACTED ON / EXPIRED context block."""
    # Active (still pending)
    active = (await session.scalars(
        select(RecommendationRow).where(RecommendationRow.status == "active")
        .order_by(RecommendationRow.digest_date.desc())
    )).all()

    # Recently acted-on / expired (last 7 days, for the LLM's awareness)
    recent = (await session.scalars(
        select(RecommendationRow).where(
            RecommendationRow.status.in_(["acted_on", "expired", "superseded"]),
            RecommendationRow.digest_date >= today - timedelta(days=7),
        ).order_by(RecommendationRow.digest_date.desc())
    )).all()

    lines = []
    if active:
        lines.append("OPEN RECOMMENDATIONS (you issued these on prior days — still pending):")
        for r in active:
            amt = f"${r.amount_usd:,.0f} " if r.amount_usd else ""
            lines.append(f"- [{r.digest_date.date()}] {r.verb} {r.symbol or ''} {amt}by {r.due_date.date()} ({r.window}) — {r.rationale}")
    if recent:
        lines.append("\nRECENTLY RESOLVED (last 7 days):")
        for r in recent:
            lines.append(f"- [{r.digest_date.date()}] {r.verb} {r.symbol or ''} → {r.status}: {r.acted_on_detail or ''}")
    if not active and not recent:
        return ""  # no continuity context needed

    lines.append("""
CONTINUITY RULES:
- If today continues an open rec, say so and reference the date.
- If today CHANGES/CANCELS an open rec, you MUST emit `supersedes: <YYYY-MM-DD>` and explain the pivot. The old rec will be marked superseded.
- Don't re-issue a fresh amount for a ticker with an active rec unless pivoting.
- Respect the windows you set. "2-3 weeks" can't silently become "this week" — that's a pivot, call it out.""")
    return "\n".join(lines)
```

### System prompt update

Add the continuity context to `_SYSTEM_PROMPT` in `generate_digest.py`. The
context block is appended to the existing prompt (after the portfolio/disclosure
context, before the "Action of the Day" instructions). Also add to the prompt:

> After your human-readable "Action of the Day" section, you MUST emit a
> machine-readable block in this exact format:
> ```
> <<<RECOMMENDATION>>>
> verb: BUY|HOLD
> symbol: <TICKER>          (omit for HOLD)
> amount_usd: <number>      (omit for HOLD)
> window: this-week|2-3-weeks|this-month|immediate
> rationale: <one sentence>
> supersedes: <YYYY-MM-DD>  (ONLY if pivoting from a prior active rec)
> <<<END>>>
> ```

### Post-LLM processing

After parsing the block and before inserting the new recommendation:
- If `supersedes_date` is present, mark the matching active recommendation
  (same symbol, matching date) as `status = superseded` and set its
  `superseded_by` to the new recommendation's id.

---

## Lifecycle — run order in `execute()`

Modify `execute()` in `src/trading/application/signals/generate_digest.py`.
The new run order (insert the new steps before the existing LLM call):

1. **Expire** — `UPDATE recommendations SET status='expired' WHERE status='active' AND due_date < now()`
2. **Detect acted-on** — `_detect_acted_on(...)` → marks matched rows `acted_on`
3. **Load context** — `_build_continuity_context(...)` → the prompt block
4. **Call LLM** (existing behavior, now with continuity context in the prompt)
5. **Parse** the recommendation block from the LLM output
6. **Insert** the new `RecommendationRow` (with baseline snapshot from live
   positions at issue time)
7. **Mark superseded** — if `supersedes_date` present, update the prior rec

The baseline snapshot (step 6) captures the self-directed account's current
qty for the recommended symbol + current cash, so future detection has a
reference point.

---

## Threading the broker + account id

Currently `execute()` only receives `market_data`. You need to add:
- `broker: BrokerPort` parameter
- `self_directed_account_id: str` parameter

Update the call site in `apps/worker/jobs/generate_digest_job.py` to pass both
(from `comp.broker` and `settings.self_directed_account_id`).

Add to `apps/common/settings.py`:
```python
self_directed_account_id: str = Field(default="")
```

The detection steps (1-2) should be **best-effort** — if the broker is
unavailable or the account id isn't set, skip detection and log a warning.
Never block the digest on detection failures.

---

## Files to create/modify

| File | Action |
|------|--------|
| `migrations/versions/0003_recommendations.py` | **Create** — new table |
| `src/trading/adapters/persistence/models.py` | **Modify** — add `RecommendationRow` |
| `src/trading/application/signals/generate_digest.py` | **Modify** — the bulk: parser, lifecycle, context builder, prompt update, `execute()` changes |
| `apps/worker/jobs/generate_digest_job.py` | **Modify** — pass broker + account id to `execute()` |
| `apps/common/settings.py` | **Modify** — add `self_directed_account_id` |
| `tests/application/test_generate_digest_recommendations.py` | **Create** — parser + lifecycle tests |

---

## Tests required

1. **Parser** (`_parse_recommendation_block`):
   - Valid BUY block → correct fields + computed `due_date`
   - HOLD block (no symbol/amount) → verb=HOLD, nulls
   - Malformed block → HOLD fallback with parse-failed rationale
   - Missing block entirely → HOLD fallback
   - `supersedes:` date parsing
2. **Detection** (`_detect_acted_on`):
   - Quantity grew by ~target → `acted_on` (with detail)
   - Cash dropped by ~target → `acted_on`
   - No change → stays `active`
   - Tolerance boundary (±15%)
3. **Lifecycle**:
   - Past-due active recs → `expired`
   - `supersedes:` → prior rec marked `superseded` + `superseded_by` set
4. **No-submit guarantee**: `execute()` with LLM mock → confirms a
   `RecommendationRow` is inserted, and the human-readable markdown is
   unchanged in quality (the block is stripped from the visible output)

Use stub/fake brokers for tests — no live Schwab calls. Match the existing
test patterns in `tests/application/`.

---

## Acceptance criteria

- [ ] `0003_recommendations` migration applies cleanly
- [ ] Digest run creates a `recommendations` row with structured fields
- [ ] A second digest run (next day) shows the prior rec in the LLM context
- [ ] Simulating a Schwab qty increase marks the prior BUY rec `acted_on`
- [ ] A pivot (`supersedes:`) marks the prior rec `superseded` and records the link
- [ ] Past-due recs auto-expire
- [ ] Malformed/missing block → HOLD fallback, digest still succeeds + pushes
- [ ] All new tests pass; `uv run mypy src/` is clean
- [ ] Human-readable digest quality is unchanged (the block is stripped from
      what's shown to the user / pushed via Pushover)

---

## Risk notes

- **Detection tolerance** (±15%) may need tuning once real fills are observed.
  Keep it a module constant.
- **Baseline snapshot timing**: capture at issue time (in `execute()`), not at
  detection time. The `positions` table only holds current state, so without a
  baseline the detector can't compute a delta.
- **HOLD recommendations** are still recorded (for the audit trail) but have
  no detection logic — they just age out and eventually get cleared.
- **Prompt length**: the continuity context adds tokens. Cap the open-recs
  list at ~10 entries (oldest trimmed) to avoid unbounded growth.
- This changes **only the digest path**. The Congressional-only **briefing**
  is explicitly non-advisory and is untouched.

---

## Key file references (for the implementing agent)

- Digest generation: `src/trading/application/signals/generate_digest.py`
  - `_SYSTEM_PROMPT` (around line 40-90)
  - `execute()` (the main function)
  - The `PUSH:` extraction at line ~353 (reuse the strip-block pattern)
- Digest job: `apps/worker/jobs/generate_digest_job.py` (the call site)
- Migration pattern: `migrations/versions/2026_06_24_0002_digests.py`
- Model pattern: `src/trading/adapters/persistence/models.py` line 224 (`DigestRow`)
- BrokerPort: `src/trading/adapters/ports/broker.py` (`get_positions`, `get_account`)
- Test patterns: `tests/application/test_refresh_positions.py`, `tests/application/test_place_order.py`
- The domain explicitly notes a `Recommendation` type "may be added when
  execution lands" — see `src/trading/domain/signals/entities.py` line 3-30
