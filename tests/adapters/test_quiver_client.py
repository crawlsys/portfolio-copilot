from __future__ import annotations

from datetime import date

import pytest
import vcr as vcr_module

from trading.adapters.quiver import QuiverClient
from trading.domain import Symbol, TransactionType


@pytest.mark.asyncio
async def test_get_recent_disclosures_cassette(trading_vcr: vcr_module.VCR) -> None:
    client = QuiverClient(api_key="test-token")

    with trading_vcr.use_cassette("quiver/recent_disclosures.yaml"):
        disclosures = await client.get_recent_disclosures(since=date(2026, 6, 1), limit=2)

    assert len(disclosures) == 2
    assert disclosures[0].member_name == "Sheri Biggs"
    assert disclosures[0].symbol is None
    assert disclosures[0].amount_range_low == 1001
    assert disclosures[0].amount_range_high == 15000
    assert disclosures[1].symbol == Symbol("NVDA")
    assert disclosures[1].transaction_type is TransactionType.SALE_PARTIAL


@pytest.mark.asyncio
async def test_get_disclosures_by_symbol_cassette(trading_vcr: vcr_module.VCR) -> None:
    client = QuiverClient(api_key="test-token")

    with trading_vcr.use_cassette("quiver/disclosures_by_symbol.yaml"):
        disclosures = await client.get_disclosures_by_symbol(Symbol("NVDA"), since=date(2026, 1, 1))

    assert len(disclosures) == 2
    assert {disclosure.symbol for disclosure in disclosures} == {Symbol("NVDA")}
    assert disclosures[0].member_id == "P000197"
