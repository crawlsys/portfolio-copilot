#!/usr/bin/env python3
"""Seed the local DB with anonymized demo data for screenshots + local dev.

Loads data/holdings-demo.json into a demo brokerage account + positions,
inserts ~20 synthetic Congressional trade disclosures (public figures,
public tickers — STOCK Act data is public record), and one demo digest
referencing the demo portfolio.

Idempotent: safe to re-run. Existing demo rows (account_id='demo-account',
filing_id starting with 'demo-') are deleted before re-inserting.

Usage:
    uv run python scripts/seed_demo.py [--dsn ...]

Requires a running Postgres with migrations applied.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, delete, text  # noqa: E402

from trading.adapters.persistence.models import (  # noqa: E402
    BrokerAccountRow,
    DigestRow,
    MemberRow,
    PositionRow,
    TradeDisclosureRow,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_ACCOUNT_ID = "demo-account"

# --- Demo Congressional members (public figures, public offices) ----------------
MEMBERS = [
    {
        "member_id": "demo-pelosi",
        "name": "Nancy Pelosi",
        "chamber": "house",
        "party": "D",
        "state": "CA",
        "district": "11",
        "committees": [],
        "bioguide_id": "P000197",
    },
    {
        "member_id": "demo-crapo",
        "name": "Mike Crapo",
        "chamber": "senate",
        "party": "R",
        "state": "ID",
        "district": None,
        "committees": ["Finance"],
        "bioguide_id": "C000880",
    },
    {
        "member_id": "demo-moskowitz",
        "name": "Jared Moskowitz",
        "chamber": "house",
        "party": "D",
        "state": "FL",
        "district": "23",
        "committees": ["Oversight"],
        "bioguide_id": "M001217",
    },
]

# --- Demo disclosures. Tickers overlap the demo portfolio so the overlap
#     view has content. Dates are relative to today so the feed always looks fresh.
def _disclosures(now: datetime) -> list[dict]:
    base = [
        ("demo-pelosi", "Nancy Pelosi", "NVDA", "PURCHASE", 1_000_001, 5_000_000, "NVIDIA CORP"),
        ("demo-pelosi", "Nancy Pelosi", "AAPL", "PURCHASE", 100_001, 250_000, "APPLE INC"),
        ("demo-crapo", "Mike Crapo", "MSFT", "EXCHANGE", 50_001, 100_000, "MICROSOFT CORP"),
        ("demo-moskowitz", "Jared Moskowitz", "NVDA", "PURCHASE", 15_001, 50_000, "NVIDIA CORP"),
        ("demo-moskowitz", "Jared Moskowitz", "META", "SALE (PARTIAL)", 1_001, 15_000, "META PLATFORMS"),
        ("demo-pelosi", "Nancy Pelosi", "GOOGL", "PURCHASE", 1_000_001, 5_000_000, "ALPHABET INC"),
        ("demo-crapo", "Mike Crapo", "AVGO", "PURCHASE", 100_001, 250_000, "BROADCOM INC"),
        ("demo-moskowitz", "Jared Moskowitz", "COST", "PURCHASE", 1_001, 15_000, "COSTCO"),
        ("demo-pelosi", "Nancy Pelosi", "MSFT", "PURCHASE", 250_001, 500_000, "MICROSOFT CORP"),
        ("demo-crapo", "Mike Crapo", "JNJ", "SALE (FULL)", 15_001, 50_000, "JOHNSON & JOHNSON"),
        ("demo-moskowitz", "Jared Moskowitz", "AAPL", "PURCHASE", 1_001, 15_000, "APPLE INC"),
        ("demo-pelosi", "Nancy Pelosi", "AVGO", "PURCHASE", 1_000_001, 5_000_000, "BROADCOM INC"),
        ("demo-crapo", "Mike Crapo", "NVDA", "SALE (PARTIAL)", 50_001, 100_000, "NVIDIA CORP"),
        ("demo-moskowitz", "Jared Moskowitz", "MSFT", "PURCHASE", 1_001, 15_000, "MICROSOFT CORP"),
        ("demo-pelosi", "Nancy Pelosi", "META", "PURCHASE", 250_001, 500_000, "META PLATFORMS"),
        ("demo-crapo", "Mike Crapo", "GOOGL", "PURCHASE", 100_001, 250_000, "ALPHABET INC"),
        ("demo-moskowitz", "Jared Moskowitz", "VTI", "PURCHASE", 1_001, 15_000, "VANGUARD TOTAL STOCK"),
        ("demo-pelosi", "Nancy Pelosi", "COST", "PURCHASE", 50_001, 100_000, "COSTCO"),
        ("demo-crapo", "Mike Crapo", "META", "PURCHASE", 15_001, 50_000, "META PLATFORMS"),
        ("demo-moskowitz", "Jared Moskowitz", "GOOGL", "SALE (PARTIAL)", 1_001, 15_000, "ALPHABET INC"),
    ]
    rows = []
    for i, (mid, name, sym, ttype, lo, hi, desc) in enumerate(base):
        tx_date = now - timedelta(days=8 + (i % 12))
        file_date = tx_date + timedelta(days=2 + (i % 6))
        rows.append({
            "filing_id": f"demo-disc-{i+1:03d}",
            "member_id": mid,
            "member_name": name,
            "symbol": sym,
            "asset_class": "EQUITY",
            "asset_description": desc,
            "transaction_type": ttype,
            "transaction_date": tx_date,
            "disclosure_date": file_date,
            "amount_range_low": lo,
            "amount_range_high": hi,
        })
    return rows


DEMO_DIGEST_MD = """## Portfolio Snapshot

**Net liquidation:** $95,576 · **Cash to deploy:** $24,500 · **Unrealized P/L:** +$8,546 (+13.7%)

Your self-directed account is **68% invested, 26% cash, 6% bonds**. Equity
concentration is reasonable — the top three positions (VTI, AAPL, SGOV) make
up 31% of invested capital. No single name exceeds 13%.

## Congressional Signal — This Cycle

**20 disclosures** filed in the last 15 days across **3 members**. **6 overlap
your holdings:**

| Member | Ticker | Action | Amount | Filed |
|--------|--------|--------|--------|-------|
| Pelosi | NVDA | Purchase | $1M–$5M | 9d ago |
| Pelosi | GOOGL | Purchase | $1M–$5M | 11d ago |
| Crapo | MSFT | Exchange | $50K–$100K | 8d ago |
| Moskowitz | META | Sale (Partial) | $1K–$15K | 7d ago |
| Pelosi | AAPL | Purchase | $100K–$250K | 12d ago |
| Crapo | JNJ | Sale (Full) | $15K–$50K | 10d ago |

**Read:** Pelosi's tech purchases (NVDA, GOOGL, AAPL) are high-conviction by
size. They align with your existing overweight. No new information that
warrants a change — you're already positioned for the thesis they're trading.

## Action of the Day — ONE clear call

**Deploy $5,000 into VTI this week** (first tranche). Rationale: your equity
weighting is light at 68%, VTI is your core holding, and DCA-ing the cash
over the next 4 weeks reduces timing risk. Park the remaining $19,500 in
SGOV (already held) to earn ~5.3% while you stage the deployment.

**HOLD** on individual names — current exposures are well within your risk
tolerance and the Congressional signal confirms, not contradicts, the positions.

PUSH: Deploy $5K VTI this week (first tranche), hold SGOV, no name changes.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed anonymized demo data.")
    ap.add_argument(
        "--dsn",
        default=os.environ.get("DATABASE_URL") if (os := __import__("os")) else "",
        help="PostgreSQL DSN (default: $DATABASE_URL)",
    )
    args = ap.parse_args()
    if not args.dsn:
        print("ERROR: --dsn or DATABASE_URL required", file=sys.stderr)
        return 1

    engine = create_engine(args.dsn)
    now = datetime.now(UTC)

    with engine.begin() as conn:
        # Idempotent: clear prior demo rows.
        conn.execute(delete(TradeDisclosureRow).where(
            TradeDisclosureRow.filing_id.like("demo-disc-%")
        ))
        conn.execute(delete(DigestRow).where(DigestRow.digest_id.like("demo-digest-%")))
        conn.execute(delete(PositionRow).where(PositionRow.account_id == DEMO_ACCOUNT_ID))
        conn.execute(delete(BrokerAccountRow).where(
            BrokerAccountRow.account_id == DEMO_ACCOUNT_ID
        ))
        conn.execute(delete(MemberRow).where(MemberRow.member_id.like("demo-%")))

        # 1. Account + positions from holdings-demo.json
        import json  # noqa: PLC0415
        holdings_path = REPO_ROOT / "data" / "holdings-demo.json"
        hd = json.loads(holdings_path.read_text())
        conn.execute(text(
            "INSERT INTO broker_accounts "
            "(account_id, nickname, masked_schwab_id, account_type, margin_enabled, "
            " allowed_instruments, is_paper, created_at, updated_at) "
            "VALUES (:id, :nick, :masked, :atype, false, '{}', false, now(), now()) "
            "ON CONFLICT (account_id) DO UPDATE SET nickname=EXCLUDED.nickname, updated_at=now()"
        ), {"id": DEMO_ACCOUNT_ID, "nick": hd["nickname"], "masked": hd["masked_schwab_id"],
            "atype": "MARGIN"})

        pos_rows = []
        for h in hd["holdings"]:
            pos_rows.append({
                "account_id": DEMO_ACCOUNT_ID,
                "symbol": h["symbol"],
                "asset_class": "EQUITY",
                "quantity": Decimal(h["quantity"]),
                "average_cost": (Decimal(h["cost_basis"]) / Decimal(h["quantity"])).quantize(
                    Decimal("0.0001")
                ),
                "market_value": Decimal(h["market_value"]),
                "unrealized_pnl": Decimal(h["unrealized_pnl"]),
                "as_of": now,
            })
        conn.execute(text(
            "INSERT INTO positions "
            "(account_id, symbol, asset_class, quantity, average_cost, "
            " average_cost_currency, market_value, unrealized_pnl, as_of) "
            "VALUES (:account_id, :symbol, :asset_class, :quantity, :average_cost, "
            "        'USD', :market_value, :unrealized_pnl, :as_of)"
        ), pos_rows)

        # 2. Members
        import json as _json  # noqa: PLC0415
        for m in MEMBERS:
            params = {k: v for k, v in m.items() if k != "committees"}
            params["committees"] = _json.dumps(m["committees"])  # JSONB needs a JSON string
            conn.execute(text(
                "INSERT INTO members "
                "(member_id, name, chamber, party, state, district, committees, "
                " bioguide_id, updated_at) "
                "VALUES (:member_id, :name, :chamber, :party, :state, :district, "
                "        CAST(:committees AS jsonb), :bioguide_id, now()) "
                "ON CONFLICT (member_id) DO UPDATE SET name=EXCLUDED.name, updated_at=now()"
            ), params)

        # 3. Disclosures
        for d in _disclosures(now):
            conn.execute(text(
                "INSERT INTO trade_disclosures "
                "(filing_id, member_id, member_name, symbol, asset_class, "
                " asset_description, transaction_type, transaction_date, "
                " disclosure_date, amount_range_low, amount_range_high, ingested_at) "
                "VALUES (:filing_id, :member_id, :member_name, :symbol, 'EQUITY', "
                "        :asset_description, :transaction_type, :transaction_date, "
                "        :disclosure_date, :amount_range_low, :amount_range_high, now()) "
                "ON CONFLICT (filing_id) DO NOTHING"
            ), d)

        # 4. Digest
        digest_id = f"demo-digest-{now.strftime('%Y%m%d')}"
        conn.execute(text(
            "INSERT INTO digests "
            "(digest_id, digest_date, summary_markdown, push_excerpt, model, "
            " net_liquidation, cash_to_deploy, disclosures_count, generated_at) "
            "VALUES (:digest_id, :digest_date, :summary_markdown, :push_excerpt, "
            "        :model, :net_liquidation, :cash_to_deploy, :disclosures_count, now()) "
            "ON CONFLICT (digest_id) DO UPDATE SET "
            " summary_markdown=EXCLUDED.summary_markdown, push_excerpt=EXCLUDED.push_excerpt"
        ), {
            "digest_id": digest_id,
            "digest_date": now,
            "summary_markdown": DEMO_DIGEST_MD,
            "push_excerpt": "Deploy $5K VTI this week (first tranche), hold SGOV, no name changes.",
            "model": "demo-local-strong",
            "net_liquidation": "95576.35",
            "cash_to_deploy": "24500.00",
            "disclosures_count": 20,
        })

    # Report counts
    with engine.connect() as conn:
        for label, tname, where in [
            ("positions", "positions", f"account_id='{DEMO_ACCOUNT_ID}'"),
            ("members", "members", "member_id LIKE 'demo-%'"),
            ("disclosures", "trade_disclosures", "filing_id LIKE 'demo-disc-%'"),
            ("digests", "digests", "digest_id LIKE 'demo-digest-%'"),
        ]:
            n = conn.execute(text(f"SELECT count(*) FROM {tname} WHERE {where}")).scalar()
            print(f"  {label:14s}: {n}")

    print("\nDemo data seeded. Account: demo-account (use ?live=true for live prices).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
