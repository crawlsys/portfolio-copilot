"""Tests for the recommendation ledger (digest continuity).

Two tiers:
- Pure tests (parser, block stripping, acted-on rules) — no DB, always run.
- Lifecycle tests (execute() end-to-end with a mocked LLM + FakeBroker) —
  require DATABASE_URL, like the other application-layer DB tests.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

import trading.application.signals.generate_digest as gd
from trading.adapters.fake.broker import FakeBroker
from trading.adapters.persistence.models import RecommendationRow
from trading.application.common.clock import FrozenClock
from trading.application.common.unit_of_work import UnitOfWork
from trading.application.signals.generate_digest import (
    DETECTION_TOLERANCE,
    GenerateDigestCommand,
    _check_one,
    _parse_recommendation_block,
    _strip_recommendation_block,
    execute,
)
from trading.domain import Money, Position, Symbol

DIGEST_DT = datetime(2026, 7, 1, tzinfo=UTC)


# --- Parser (pure) -------------------------------------------------------------


def test_parse_valid_buy_block() -> None:
    text_block = (
        "## Action of the Day\nBuy VTI.\n\n"
        "<<<RECOMMENDATION>>>\n"
        "verb: BUY\n"
        "symbol: VTI\n"
        "amount_usd: 5000\n"
        "window: this-week\n"
        "rationale: Defensive DCA entry, light equity weighting\n"
        "<<<END>>>"
    )
    rec = _parse_recommendation_block(text_block, DIGEST_DT)
    assert rec.verb == "BUY"
    assert rec.symbol == "VTI"
    assert rec.amount_usd == Decimal("5000")
    assert rec.window == "this-week"
    assert rec.due_date == DIGEST_DT + timedelta(days=7)
    assert rec.rationale.startswith("Defensive DCA")
    assert rec.supersedes_date is None


def test_parse_hold_block_has_null_symbol_and_amount() -> None:
    text_block = (
        "<<<RECOMMENDATION>>>\n"
        "verb: HOLD\n"
        "window: immediate\n"
        "rationale: No action warranted — all positions within tolerance\n"
        "<<<END>>>"
    )
    rec = _parse_recommendation_block(text_block, DIGEST_DT)
    assert rec.verb == "HOLD"
    assert rec.symbol is None
    assert rec.amount_usd is None
    assert rec.due_date == DIGEST_DT + timedelta(days=1)


def test_parse_missing_block_falls_back_to_hold() -> None:
    rec = _parse_recommendation_block("# Digest with no block at all", DIGEST_DT)
    assert rec.verb == "HOLD"
    assert "parse failed" in rec.rationale


def test_parse_unknown_verb_falls_back_to_hold() -> None:
    text_block = "<<<RECOMMENDATION>>>\nverb: SELL\nsymbol: VTI\n<<<END>>>"
    rec = _parse_recommendation_block(text_block, DIGEST_DT)
    assert rec.verb == "HOLD"
    assert "unknown verb" in rec.rationale


def test_parse_supersedes_date() -> None:
    text_block = (
        "<<<RECOMMENDATION>>>\n"
        "verb: BUY\nsymbol: SCHD\namount_usd: $3,000\nwindow: 2-3-weeks\n"
        "rationale: Pivot from VTI\nsupersedes: 2026-06-30\n<<<END>>>"
    )
    rec = _parse_recommendation_block(text_block, DIGEST_DT)
    assert rec.supersedes_date == date(2026, 6, 30)
    assert rec.amount_usd == Decimal("3000")  # $ and comma tolerated
    assert rec.due_date == DIGEST_DT + timedelta(days=21)


def test_parse_unknown_window_defaults_to_immediate() -> None:
    text_block = (
        "<<<RECOMMENDATION>>>\nverb: BUY\nsymbol: VTI\namount_usd: 100\n"
        "window: someday\nrationale: x\n<<<END>>>"
    )
    rec = _parse_recommendation_block(text_block, DIGEST_DT)
    assert rec.window == "immediate"


def test_strip_removes_block_and_keeps_prose() -> None:
    text_block = (
        "## Action of the Day\nBuy VTI this week.\n\n"
        "<<<RECOMMENDATION>>>\nverb: BUY\nsymbol: VTI\n<<<END>>>"
    )
    stripped = _strip_recommendation_block(text_block)
    assert "<<<RECOMMENDATION>>>" not in stripped
    assert "Buy VTI this week." in stripped


def test_strip_removes_code_fenced_block() -> None:
    text_block = (
        "Prose before.\n\n```\n<<<RECOMMENDATION>>>\nverb: HOLD\n<<<END>>>\n```"
    )
    stripped = _strip_recommendation_block(text_block)
    assert "<<<" not in stripped
    assert "```" not in stripped
    assert "Prose before." in stripped


# --- Acted-on detection rules (pure) --------------------------------------------


def _rec(
    symbol: str | None = "VTI",
    amount: str = "5000",
    baseline_qty: str = "0",
    baseline_cash: str = "100000",
) -> RecommendationRow:
    return RecommendationRow(
        recommendation_id="rec-test",
        digest_id="digest-test",
        digest_date=DIGEST_DT,
        verb="BUY",
        symbol=symbol,
        amount_usd=Decimal(amount),
        window="this-week",
        due_date=DIGEST_DT + timedelta(days=7),
        rationale="test",
        status="active",
        baseline_qty=Decimal(baseline_qty),
        baseline_cash=Decimal(baseline_cash),
    )


def _pos(symbol: str, qty: str, avg_cost: str) -> Position:
    quantity = Decimal(qty)
    cost = Decimal(avg_cost)
    return Position(
        account_id="self-1",
        symbol=Symbol(symbol),
        quantity=quantity,
        average_cost=Money.usd(avg_cost),
        market_value=Money(amount=(quantity * cost).quantize(Decimal("0.0001")), currency="USD"),
        unrealized_pnl=Money.usd("0"),
        as_of=DIGEST_DT,
    )


def test_check_one_quantity_growth_triggers() -> None:
    # $5000 at $100/share → est 50 shares; qty grew 0 → 50 = ratio 1.0.
    rec = _rec()
    triggered, detail = _check_one(rec, {"VTI": _pos("VTI", "50", "100")}, Decimal("100000"))
    assert triggered
    assert "VTI" in detail and "+50" in detail


def test_check_one_cash_drop_triggers() -> None:
    # Ticker not held (rule 1 can't fire); cash dropped exactly by target.
    rec = _rec()
    triggered, detail = _check_one(rec, {}, Decimal("95000"))
    assert triggered
    assert "cash" in detail


def test_check_one_no_change_stays_inactive() -> None:
    rec = _rec()
    triggered, _ = _check_one(rec, {"VTI": _pos("VTI", "0.0001", "100")}, Decimal("100000"))
    assert not triggered


def test_check_one_quantity_tolerance_boundary() -> None:
    # est 50 shares; 1 − tolerance = 0.85 → 42.5 shares is the floor.
    rec = _rec()
    at_floor, _ = _check_one(rec, {"VTI": _pos("VTI", "42.5", "100")}, Decimal("100000"))
    below_floor, _ = _check_one(rec, {"VTI": _pos("VTI", "42", "100")}, Decimal("100000"))
    assert at_floor
    assert not below_floor
    # Sanity: the boundary math above assumes the documented tolerance.
    assert Decimal("0.15") == DETECTION_TOLERANCE


def test_check_one_null_baseline_qty_never_reads_preexisting_holding_as_fill() -> None:
    # Rec issued without a broker snapshot (baseline_qty NULL): a pre-existing
    # 190-share position must NOT be mistaken for a +190 fill on the next run.
    rec = _rec()
    rec.baseline_qty = None
    triggered, _ = _check_one(rec, {"VTI": _pos("VTI", "190", "366")}, Decimal("100000"))
    assert not triggered


def test_check_one_cash_drop_beyond_upper_tolerance_does_not_trigger() -> None:
    # Cash dropped 40% more than target — likely something else; don't claim it.
    rec = _rec()
    triggered, _ = _check_one(rec, {}, Decimal("93000"))
    assert not triggered


# --- Lifecycle (DB) --------------------------------------------------------------

pytestmark_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL required for recommendation lifecycle tests",
)


def _async_url() -> str:
    return os.environ["DATABASE_URL"].replace("+psycopg", "+psycopg_async")


@pytest.fixture()
def engine():  # type: ignore[no-untyped-def]
    eng = create_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _clean(request):  # type: ignore[no-untyped-def]
    if "engine" not in request.fixturenames:
        yield
        return
    engine = request.getfixturevalue("engine")
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM recommendations"))
        conn.execute(text("DELETE FROM digests"))
        conn.execute(text("DELETE FROM outbox"))
        conn.commit()
    yield


@pytest.fixture()
async def async_session():  # type: ignore[no-untyped-def]
    eng = create_async_engine(_async_url(), poolclass=NullPool)
    async with AsyncSession(eng, expire_on_commit=False) as session:
        yield session
    await eng.dispose()


NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


@pytest.fixture()
async def uow(async_session):  # type: ignore[no-untyped-def]
    return UnitOfWork(session=async_session, clock=FrozenClock(NOW), correlation_id=uuid4())


def _seed_rec(
    rec_id: str,
    digest_date: datetime,
    due_date: datetime,
    symbol: str | None = "VTI",
    amount: str = "5000",
    baseline_qty: str = "0",
    baseline_cash: str = "100000",
    verb: str = "BUY",
) -> RecommendationRow:
    return RecommendationRow(
        recommendation_id=rec_id,
        digest_id=f"digest-for-{rec_id}",
        digest_date=digest_date,
        verb=verb,
        symbol=symbol,
        amount_usd=Decimal(amount) if symbol else None,
        window="this-week",
        due_date=due_date,
        rationale="seeded",
        status="active",
        baseline_qty=Decimal(baseline_qty) if symbol else None,
        baseline_cash=Decimal(baseline_cash),
    )


def _fake_llm(block: str):  # type: ignore[no-untyped-def]
    """Patchable _call_openrouter returning a digest containing `block`."""

    captured: dict[str, str] = {}

    async def call(context: str, api_key: str, model: str) -> tuple[str, str]:
        captured["context"] = context
        md = (
            "# Daily Digest\n\n## TL;DR\n- test\n\n## Action of the Day\n"
            "Do the thing.\n\n" + block + "\n"
        ) * 3  # padding: execute() rejects responses < 200 chars
        return md, "push summary"

    call.captured = captured  # type: ignore[attr-defined]
    return call


BUY_BLOCK = (
    "<<<RECOMMENDATION>>>\n"
    "verb: BUY\nsymbol: VTI\namount_usd: 5000\nwindow: this-week\n"
    "rationale: test buy\n<<<END>>>"
)


@pytestmark_db
@pytest.mark.asyncio
async def test_execute_inserts_recommendation_and_strips_block(
    engine, uow, async_session, monkeypatch
) -> None:
    monkeypatch.setattr(gd, "_call_openrouter", _fake_llm(BUY_BLOCK))

    async with uow:
        result = await execute(
            GenerateDigestCommand(correlation_id=uuid4(), actor="test"),
            uow=uow,
            openrouter_api_key="test-key",
        )

    assert result.generated_by == "openrouter"
    assert "<<<RECOMMENDATION>>>" not in result.summary_markdown
    assert "Action of the Day" in result.summary_markdown

    rows = (await async_session.scalars(select(RecommendationRow))).all()
    assert len(rows) == 1
    rec = rows[0]
    assert (rec.verb, rec.symbol, rec.status) == ("BUY", "VTI", "active")
    assert rec.amount_usd == Decimal("5000")
    assert rec.digest_id == result.digest_id


@pytestmark_db
@pytest.mark.asyncio
async def test_prior_rec_appears_in_llm_context(
    engine, uow, async_session, monkeypatch
) -> None:
    async_session.add(
        _seed_rec("rec-prior", NOW - timedelta(days=1), NOW + timedelta(days=6))
    )
    await async_session.commit()

    llm = _fake_llm(BUY_BLOCK)
    monkeypatch.setattr(gd, "_call_openrouter", llm)

    async with uow:
        await execute(
            GenerateDigestCommand(correlation_id=uuid4(), actor="test"),
            uow=uow,
            openrouter_api_key="test-key",
        )

    ctx = llm.captured["context"]  # type: ignore[attr-defined]
    assert "OPEN RECOMMENDATIONS" in ctx
    assert "BUY VTI" in ctx
    assert "CONTINUITY RULES" in ctx


@pytestmark_db
@pytest.mark.asyncio
async def test_supersedes_marks_prior_rec(engine, uow, async_session, monkeypatch) -> None:
    prior_date = NOW - timedelta(days=1)
    async_session.add(_seed_rec("rec-prior", prior_date, NOW + timedelta(days=6)))
    await async_session.commit()

    pivot_block = (
        "<<<RECOMMENDATION>>>\n"
        "verb: BUY\nsymbol: SCHD\namount_usd: 3000\nwindow: this-week\n"
        f"rationale: pivot\nsupersedes: {prior_date.date().isoformat()}\n<<<END>>>"
    )
    monkeypatch.setattr(gd, "_call_openrouter", _fake_llm(pivot_block))

    async with uow:
        await execute(
            GenerateDigestCommand(correlation_id=uuid4(), actor="test"),
            uow=uow,
            openrouter_api_key="test-key",
        )

    prior = await async_session.get(RecommendationRow, "rec-prior")
    assert prior is not None
    assert prior.status == "superseded"
    new_rows = (
        await async_session.scalars(
            select(RecommendationRow).where(RecommendationRow.symbol == "SCHD")
        )
    ).all()
    assert len(new_rows) == 1
    assert prior.superseded_by == new_rows[0].recommendation_id


@pytestmark_db
@pytest.mark.asyncio
async def test_past_due_recs_expire(engine, uow, async_session, monkeypatch) -> None:
    async_session.add(
        _seed_rec("rec-stale", NOW - timedelta(days=10), NOW - timedelta(days=3))
    )
    await async_session.commit()

    monkeypatch.setattr(gd, "_call_openrouter", _fake_llm(BUY_BLOCK))

    async with uow:
        await execute(
            GenerateDigestCommand(correlation_id=uuid4(), actor="test"),
            uow=uow,
            openrouter_api_key="test-key",
        )

    stale = await async_session.get(RecommendationRow, "rec-stale")
    assert stale is not None
    assert stale.status == "expired"


@pytestmark_db
@pytest.mark.asyncio
async def test_schwab_qty_increase_marks_acted_on(
    engine, uow, async_session, monkeypatch
) -> None:
    async_session.add(
        _seed_rec("rec-vti", NOW - timedelta(days=1), NOW + timedelta(days=6))
    )
    await async_session.commit()

    broker = FakeBroker()
    broker.add_account(
        account_id="self-1",
        nickname="Self",
        masked_schwab_id="****3450",
        cash=Money.usd("100000"),
    )
    # $5000 at $100/share = est 50 shares; the account now holds 50 → acted on.
    broker.set_position(
        account_id="self-1",
        symbol=Symbol("VTI"),
        quantity=Decimal("50"),
        average_cost=Money.usd("100"),
    )

    monkeypatch.setattr(gd, "_call_openrouter", _fake_llm(BUY_BLOCK))

    async with uow:
        await execute(
            GenerateDigestCommand(correlation_id=uuid4(), actor="test"),
            uow=uow,
            openrouter_api_key="test-key",
            broker=broker,
            self_directed_account_id="self-1",
        )

    rec = await async_session.get(RecommendationRow, "rec-vti")
    assert rec is not None
    assert rec.status == "acted_on"
    assert rec.acted_on_detail and "VTI" in rec.acted_on_detail


@pytestmark_db
@pytest.mark.asyncio
async def test_malformed_block_still_persists_digest_with_hold(
    engine, uow, async_session, monkeypatch
) -> None:
    monkeypatch.setattr(gd, "_call_openrouter", _fake_llm("no machine block here"))

    async with uow:
        result = await execute(
            GenerateDigestCommand(correlation_id=uuid4(), actor="test"),
            uow=uow,
            openrouter_api_key="test-key",
        )

    assert result.digest_id  # digest survived
    rows = (await async_session.scalars(select(RecommendationRow))).all()
    assert len(rows) == 1
    assert rows[0].verb == "HOLD"
    assert "parse failed" in rows[0].rationale
