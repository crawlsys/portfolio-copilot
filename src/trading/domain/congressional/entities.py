"""Congressional context entities.

The raw signal feed. Immutable. Disclosures are never edited — corrected
filings produce a new TradeDisclosure + a FilingCorrected event.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import NewType

from trading.domain.common.value_objects import Chamber, Party, Symbol, TransactionType

FilingId = NewType("FilingId", str)
MemberId = NewType("MemberId", str)        # bioguide_id when known


@dataclass(frozen=True, slots=True)
class Committee:
    name: str
    chamber: Chamber


@dataclass(frozen=True, slots=True)
class Member:
    """A current member of Congress. Slowly-changing reference data."""

    member_id: MemberId
    name: str
    chamber: Chamber
    party: Party
    state: str | None = None
    district: str | None = None
    committees: frozenset[str] = frozenset()
    bioguide_id: str | None = None


@dataclass(frozen=True, slots=True)
class TradeDisclosure:
    """A single STOCK Act trade disclosure. Immutable once written.

    Quality caveats (must be surfaced in UI):
    - 30-45 day disclosure lag (STOCK Act allows; signal is stale)
    - amount_range is a band, not exact amount
    - Senate filings sometimes OCR-derived (prone to error)

    Raw payload (Quiver response, original PDF) lives in Garage; this object
    holds the parsed, typed fields and a `BlobRef` to the raw.
    """

    filing_id: FilingId
    member_id: MemberId
    member_name: str          # denormalized for display convenience
    symbol: Symbol | None     # None when disclosure references an unlisted asset
    asset_description: str    # raw asset name when symbol is None
    transaction_type: TransactionType
    transaction_date: date
    disclosure_date: date
    amount_range_low: int | None = None       # USD lower bound
    amount_range_high: int | None = None      # USD upper bound
    raw_blob_key: str | None = None           # Garage key for raw Quiver payload

    @property
    def lag_days(self) -> int:
        """Days between transaction and disclosure. Surfaces the stale-signal risk."""
        return (self.disclosure_date - self.transaction_date).days
