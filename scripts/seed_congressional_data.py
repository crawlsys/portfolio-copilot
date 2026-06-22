"""Seed local Congressional disclosure development data.

Run:
    uv run python scripts/seed_congressional_data.py
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.common.settings import get_settings
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from trading.adapters.persistence.models import (
    MemberRow,
    QuoteCacheRow,
    TradeDisclosureRow,
)

MEMBERS = [
    {
        "member_id": "P000197",
        "name": "Nancy Pelosi",
        "chamber": "house",
        "party": "Democratic",
        "state": "CA",
        "district": "11",
        "committees": ["Appropriations"],
        "bioguide_id": "P000197",
    },
    {
        "member_id": "C000880",
        "name": "Mike Crapo",
        "chamber": "senate",
        "party": "Republican",
        "state": "ID",
        "district": None,
        "committees": ["Finance", "Banking, Housing, and Urban Affairs"],
        "bioguide_id": "C000880",
    },
    {
        "member_id": "K000389",
        "name": "Ro Khanna",
        "chamber": "house",
        "party": "Democratic",
        "state": "CA",
        "district": "17",
        "committees": ["Armed Services", "Oversight and Accountability"],
        "bioguide_id": "K000389",
    },
    {
        "member_id": "G000575",
        "name": "Josh Gottheimer",
        "chamber": "house",
        "party": "Democratic",
        "state": "NJ",
        "district": "5",
        "committees": ["Financial Services", "Intelligence"],
        "bioguide_id": "G000575",
    },
    {
        "member_id": "W000817",
        "name": "Ron Wyden",
        "chamber": "senate",
        "party": "Democratic",
        "state": "OR",
        "district": None,
        "committees": ["Finance", "Intelligence"],
        "bioguide_id": "W000817",
    },
    {
        "member_id": "T000278",
        "name": "Pat Toomey",
        "chamber": "senate",
        "party": "Republican",
        "state": "PA",
        "district": None,
        "committees": ["Banking, Housing, and Urban Affairs"],
        "bioguide_id": "T000278",
    },
    {
        "member_id": "D000624",
        "name": "Suzan DelBene",
        "chamber": "house",
        "party": "Democratic",
        "state": "WA",
        "district": "1",
        "committees": ["Ways and Means"],
        "bioguide_id": "D000624",
    },
    {
        "member_id": "M001153",
        "name": "Mitch McConnell",
        "chamber": "senate",
        "party": "Republican",
        "state": "KY",
        "district": None,
        "committees": ["Rules and Administration"],
        "bioguide_id": "M001153",
    },
]

DISCLOSURES = [
    ("P000197", "NVDA", "NVIDIA Corporation", "BUY", 15, 30, 500001, 1000000),
    ("P000197", "AAPL", "Apple Inc.", "BUY", 35, 42, 100001, 250000),
    ("P000197", "MSFT", "Microsoft Corporation", "BUY", 52, 65, 250001, 500000),
    ("K000389", "TSLA", "Tesla, Inc.", "SELL", 12, 18, 15001, 50000),
    ("K000389", "META", "Meta Platforms, Inc.", "BUY", 44, 51, 50001, 100000),
    ("K000389", "NVDA", "NVIDIA Corporation", "BUY", 61, 75, 15001, 50000),
    ("G000575", "AAPL", "Apple Inc.", "SELL", 21, 28, 1001, 15000),
    ("G000575", "GOOGL", "Alphabet Inc.", "BUY", 39, 45, 15001, 50000),
    ("G000575", "MSFT", "Microsoft Corporation", "EXCHANGE", 68, 72, 50001, 100000),
    ("C000880", "JPM", "JPMorgan Chase & Co.", "BUY", 25, 37, 15001, 50000),
    ("C000880", "BAC", "Bank of America Corporation", "SELL", 57, 66, 1001, 15000),
    ("C000880", "V", "Visa Inc.", "BUY", 47, 55, 50001, 100000),
    ("W000817", "AMZN", "Amazon.com, Inc.", "BUY", 9, 31, 15001, 50000),
    ("W000817", "MSFT", "Microsoft Corporation", "SELL", 33, 39, 15001, 50000),
    ("W000817", "CRM", "Salesforce, Inc.", "BUY", 71, 88, 1001, 15000),
    ("T000278", "XOM", "Exxon Mobil Corporation", "BUY", 11, 24, 15001, 50000),
    ("T000278", "CVX", "Chevron Corporation", "SELL", 50, 63, 50001, 100000),
    ("T000278", "AAPL", "Apple Inc.", "BUY", 82, 91, 1001, 15000),
    ("D000624", "MSFT", "Microsoft Corporation", "BUY", 17, 29, 100001, 250000),
    ("D000624", "ADBE", "Adobe Inc.", "BUY", 58, 70, 15001, 50000),
    ("D000624", "META", "Meta Platforms, Inc.", "SELL", 77, 84, 15001, 50000),
    ("M001153", "KO", "The Coca-Cola Company", "BUY", 20, 43, 1001, 15000),
    ("M001153", "LLY", "Eli Lilly and Company", "BUY", 41, 55, 50001, 100000),
    ("M001153", "NVDA", "NVIDIA Corporation", "SELL", 69, 83, 15001, 50000),
    ("P000197", "GOOGL", "Alphabet Inc.", "BUY", 6, 20, 100001, 250000),
    ("K000389", "AAPL", "Apple Inc.", "BUY", 93, 102, 15001, 50000),
    ("G000575", "TSLA", "Tesla, Inc.", "SELL", 104, 114, 50001, 100000),
    ("C000880", "MSFT", "Microsoft Corporation", "BUY", 110, 120, 1001, 15000),
]

QUOTES = {
    "AAPL": "214.75",
    "ADBE": "495.10",
    "AMZN": "187.40",
    "BAC": "39.25",
    "CRM": "258.66",
    "CVX": "156.84",
    "GOOGL": "176.22",
    "JPM": "202.11",
    "KO": "62.34",
    "LLY": "884.19",
    "META": "504.33",
    "MSFT": "436.58",
    "NVDA": "129.45",
    "TSLA": "184.90",
    "V": "276.80",
    "XOM": "112.06",
}


def main() -> None:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required to seed congressional data.")

    engine = create_engine(settings.database_url)
    now = datetime.now(UTC)

    with Session(engine) as session:
        session.execute(
            delete(TradeDisclosureRow).where(TradeDisclosureRow.filing_id.like("seed-%"))
        )

        for member in MEMBERS:
            session.merge(MemberRow(**member))

        for index, item in enumerate(DISCLOSURES, start=1):
            member_id, symbol, description, txn_type, txn_days_ago, filed_days_ago, low, high = item
            member = next(m for m in MEMBERS if m["member_id"] == member_id)
            session.add(
                TradeDisclosureRow(
                    filing_id=f"seed-{index:03d}-{member_id}-{symbol}",
                    member_id=member_id,
                    member_name=str(member["name"]),
                    symbol=symbol,
                    asset_class="EQUITY",
                    asset_description=description,
                    transaction_type=txn_type,
                    transaction_date=now - timedelta(days=txn_days_ago),
                    disclosure_date=now - timedelta(days=filed_days_ago),
                    amount_range_low=low,
                    amount_range_high=high,
                    raw_blob_key=f"seed/congressional/{index:03d}.json",
                    ingested_at=now,
                )
            )

        for symbol, last in QUOTES.items():
            value = Decimal(last)
            session.merge(
                QuoteCacheRow(
                    symbol=symbol,
                    bid=value - Decimal("0.05"),
                    ask=value + Decimal("0.05"),
                    last=value,
                    volume=1_000_000,
                    observed_at=now,
                    updated_at=now,
                )
            )

        session.commit()

    print(f"Seeded {len(MEMBERS)} members and {len(DISCLOSURES)} disclosures.")


if __name__ == "__main__":
    main()
