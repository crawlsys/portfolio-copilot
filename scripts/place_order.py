#!/usr/bin/env python3
"""Place a live Schwab equity order via the preview → confirm → submit flow.

Examples:
    # Buy ~$3000 of VTI at market in the self-directed account
    uv run python scripts/place_order.py --account ****3450 --buy VTI --usd 3000 --market

    # Buy 100 shares of AAPL at a $230 limit
    uv run python scripts/place_order.py --account ****3450 --buy AAPL --qty 100 --limit 230

    # Sell 50 shares of T at market
    uv run python scripts/place_order.py --account ****3450 --sell T --qty 50 --market

The script ALWAYS previews first and shows you the spec + estimated cost +
buying-power impact. It only submits after you type 'yes' (or pass --yes).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading.application.execution.place_order import (  # noqa: E402
    OrderValidationError,
    PlaceOrderCommand,
    make_audit_record,
    preview,
    submit,
)
from trading.domain.execution.types import OrderSide, OrderType  # noqa: E402


async def _run(args: argparse.Namespace) -> int:
    from apps.common.composition import make_composition  # noqa: PLC0415
    from apps.common.settings import get_settings  # noqa: PLC0415

    s = get_settings()
    comp = make_composition(
        broker_mode=s.broker_mode,
        database_url=s.database_url,
        massive_api_key=s.massive_api_key,
        schwab_client_id=s.schwab_client_id,
        schwab_client_secret=s.schwab_client_secret,
        schwab_redirect_uri=s.schwab_redirect_uri,
        schwab_token_path=s.schwab_token_path,
    )

    side = OrderSide.BUY if args.buy else OrderSide.SELL
    if args.limit is not None:
        order_type = OrderType.LIMIT
    else:
        order_type = OrderType.MARKET

    cmd = PlaceOrderCommand(
        account_id=args.account,
        symbol=args.symbol,
        side=side,
        order_type=order_type,
        quantity=Decimal(str(args.qty)) if args.qty else None,
        target_usd=Decimal(str(args.usd)) if args.usd else None,
        limit_price=Decimal(str(args.limit)) if args.limit is not None else None,
        actor=args.actor,
    )

    # --- Preview -----------------------------------------------------------
    print("=" * 64)
    print("  ORDER PREVIEW — NOT YET SUBMITTED")
    print("=" * 64)
    try:
        pv = await preview(cmd, broker=comp.broker)
    except OrderValidationError as e:
        print(f"\n  ✗ Validation failed: {e}", file=sys.stderr)
        return 2

    print(f"  Account      : {args.account}")
    print(f"  Symbol       : {pv.symbol}")
    print(f"  Side         : {pv.side.name}")
    print(f"  Type         : {pv.order_type.name}")
    print(f"  Quantity     : {pv.quantity} shares")
    if args.limit is not None:
        print(f"  Limit price  : ${Decimal(str(args.limit)):.2f}")
    print(f"  Est. cost    : ${pv.estimated_cost:.2f}")
    print(f"  Buying power : ${pv.buying_power_before:.2f} → ${pv.buying_power_after:.2f}")
    if pv.warnings:
        for w in pv.warnings:
            print(f"  ⚠ {w}")
    print()
    print("  Broker preview (validation response):")
    print("  " + json.dumps(pv.broker_preview, indent=2, default=str).replace("\n", "\n  "))
    print()
    print("  Order spec:")
    print("  " + json.dumps(pv.order_spec, indent=2, default=str).replace("\n", "\n  "))
    print("=" * 64)

    if not pv.is_within_buying_power and side in (OrderSide.BUY, OrderSide.BUY_TO_OPEN):
        print("\n  ✗ Estimated cost exceeds buying power. Aborting.", file=sys.stderr)
        return 2

    # --- Confirm -----------------------------------------------------------
    if args.yes:
        print("\n  --yes passed, submitting without prompt.")
        confirmed = True
    else:
        try:
            answer = input("\n  Submit this order? Type 'yes' to confirm: ").strip().lower()
        except EOFError:
            print("\n  No input received. Aborting (use --yes for non-interactive).",
                  file=sys.stderr)
            return 1
        confirmed = answer in ("yes", "y")

    if not confirmed:
        print("  Order NOT submitted.")
        return 1

    # --- Submit ------------------------------------------------------------
    print("\n  Submitting...")
    order_id = await submit(cmd, broker=comp.broker)
    print(f"\n  ✓ Order submitted. Broker order id: {order_id}")

    # --- Audit (best-effort; the audit row needs a session, logged separately) ---
    record = make_audit_record(
        cmd=cmd,
        order_id=order_id,
        preview=pv,
        actor=args.actor,
        occurred_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    print(f"  Audit record: {record.audit_id} (action={record.action})")
    print()
    print("  Verify in Schwab: the order should appear under Orders shortly.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Place a live Schwab equity order (preview → confirm → submit).",
    )
    # Side (mutually exclusive)
    side = p.add_mutually_exclusive_group(required=True)
    side.add_argument("--buy", action="store_true", help="Buy")
    side.add_argument("--sell", action="store_true", help="Sell")
    # Symbol
    p.add_argument("symbol", help="Ticker symbol, e.g. VTI")
    # Quantity (exactly one of --qty / --usd)
    qty = p.add_mutually_exclusive_group(required=True)
    qty.add_argument("--qty", type=str, help="Share quantity (whole shares)")
    qty.add_argument("--usd", type=str, help="Dollar amount (market orders; "
                        "computes whole-share qty from live quote, rounds DOWN)")
    # Order type
    p.add_argument("--market", action="store_true", help="Market order (default)")
    p.add_argument("--limit", type=str, help="Limit price (e.g. 230.50)")
    # Account + options
    p.add_argument("--account", required=True,
                   help="Account id, hash, or masked (e.g. ****3450)")
    p.add_argument("--actor", default="agent-cli", help="Actor name for audit")
    p.add_argument("--yes", action="store_true",
                   help="Skip the confirmation prompt (NON-INTERACTIVE SUBMIT)")
    args = p.parse_args()

    if args.limit is not None and not args.limit:
        p.error("--limit requires a value")

    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
