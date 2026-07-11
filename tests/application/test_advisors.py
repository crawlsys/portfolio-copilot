"""Advisor council — snapshot building and the agent failure contract."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from trading.application.advisors import (
    ADVISOR_REGISTRY,
    BuffettAdvisor,
    InsufficientDataError,
    PeriodFundamentals,
    build_snapshot,
    extract_json,
)
from trading.application.advisors.llm import LLMParseError
from trading.domain import SignalKind


def _period(report: str, **overrides: object) -> PeriodFundamentals:
    defaults: dict = {
        "report_period": report,
        "filing_date": report,
        "market_cap": 3.0e12,
        "price_to_earnings_ratio": 30.0,
        "return_on_equity": 1.2,
        "gross_margin": 0.45,
        "operating_margin": 0.30,
        "net_margin": 0.25,
        "debt_to_equity": 1.2,
        "current_ratio": 1.05,
        "revenue_growth": 0.08,
        "earnings_per_share": 6.5,
        "book_value_per_share": 5.3,
        "free_cash_flow_per_share": 6.9,
    }
    defaults.update(overrides)
    return PeriodFundamentals(**defaults)


class _StubFundamentals:
    def __init__(self, rows: list[PeriodFundamentals]) -> None:
        self._rows = rows

    async def get_fundamentals_history(
        self, ticker: str, as_of: date, limit: int = 20
    ) -> list[PeriodFundamentals]:
        return self._rows[:limit]


class _StubLLM:
    model = "stub-model"

    def __init__(self, response: str | Exception) -> None:
        self._response = response
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        self.calls += 1
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


_FOUR_PERIODS = [
    _period("2025-12-27", book_value_per_share=5.3),
    _period("2025-09-27", book_value_per_share=5.1),
    _period("2025-06-27", book_value_per_share=4.9),
    _period("2025-03-27", book_value_per_share=4.7),
]


class TestBuildSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_aggregates(self) -> None:
        snap = await build_snapshot("AAPL", date(2026, 7, 10), _StubFundamentals(_FOUR_PERIODS))
        assert snap.ticker == "AAPL"
        assert snap.as_of == "2026-07-10"
        assert len(snap.periods) == 4
        assert snap.roe_avg == pytest.approx(1.2)
        assert snap.debt_to_equity_latest == pytest.approx(1.2)
        assert snap.market_cap_latest == pytest.approx(3.0e12)
        # 3 quarters oldest→latest: (5.3/4.7)^(1/0.75) - 1
        assert snap.bvps_cagr == pytest.approx((5.3 / 4.7) ** (4 / 3) - 1)

    @pytest.mark.asyncio
    async def test_content_hash_stable_and_content_sensitive(self) -> None:
        stub = _StubFundamentals(_FOUR_PERIODS)
        a = await build_snapshot("AAPL", date(2026, 7, 10), stub)
        b = await build_snapshot("AAPL", date(2026, 7, 10), stub)
        assert a.content_hash == b.content_hash

        changed = [_period("2025-12-27", net_margin=0.26), *_FOUR_PERIODS[1:]]
        c = await build_snapshot("AAPL", date(2026, 7, 10), _StubFundamentals(changed))
        assert c.content_hash != a.content_hash

    @pytest.mark.asyncio
    async def test_insufficient_history_raises(self) -> None:
        with pytest.raises(InsufficientDataError):
            await build_snapshot(
                "NEWIPO", date(2026, 7, 10), _StubFundamentals(_FOUR_PERIODS[:2])
            )

    @pytest.mark.asyncio
    async def test_render_contains_periods(self) -> None:
        snap = await build_snapshot("AAPL", date(2026, 7, 10), _StubFundamentals(_FOUR_PERIODS))
        rendered = snap.render()
        assert "Company: AAPL" in rendered
        assert "2025-12-27" in rendered
        assert "publicly filed by this date" in rendered


class TestAdvisorContract:
    @pytest.mark.asyncio
    async def test_valid_response_becomes_view(self) -> None:
        llm = _StubLLM(
            '{"signal": "bullish", "confidence": 85, "reasoning": "A wonderful business."}'
        )
        snap = await build_snapshot("AAPL", date(2026, 7, 10), _StubFundamentals(_FOUR_PERIODS))
        view = await BuffettAdvisor(llm).form_view(snap)
        assert view.advisor == "buffett"
        assert view.stance == "bullish"
        assert view.confidence == 85
        assert view.score == pytest.approx(0.85)
        assert not view.abstained
        # Audit trail carries the exact prompts + raw response
        assert "Warren Buffett" in view.system_prompt
        assert view.user_prompt == snap.render()
        assert view.raw_response.startswith('{"signal"')
        assert view.snapshot_hash == snap.content_hash

    @pytest.mark.asyncio
    async def test_llm_failure_abstains(self) -> None:
        llm = _StubLLM(RuntimeError("gateway down"))
        snap = await build_snapshot("AAPL", date(2026, 7, 10), _StubFundamentals(_FOUR_PERIODS))
        view = await BuffettAdvisor(llm).form_view(snap)
        assert view.abstained
        assert view.stance == "neutral"
        assert view.confidence == 0
        assert view.score == 0.0
        assert "LLM call failed" in (view.abstain_reason or "")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad",
        [
            "not json at all",
            '{"signal": "sideways", "confidence": 50, "reasoning": "?"}',
            '{"signal": "bullish", "confidence": 250, "reasoning": "?"}',
        ],
    )
    async def test_bad_response_abstains_and_keeps_raw(self, bad: str) -> None:
        snap = await build_snapshot("AAPL", date(2026, 7, 10), _StubFundamentals(_FOUR_PERIODS))
        view = await BuffettAdvisor(_StubLLM(bad)).form_view(snap)
        assert view.abstained
        assert view.raw_response == bad  # the debug trail survives

    @pytest.mark.asyncio
    async def test_bearish_score_is_negative(self) -> None:
        llm = _StubLLM('{"signal": "bearish", "confidence": 60, "reasoning": "Deteriorating."}')
        snap = await build_snapshot("AAPL", date(2026, 7, 10), _StubFundamentals(_FOUR_PERIODS))
        view = await BuffettAdvisor(llm).form_view(snap)
        assert view.score == pytest.approx(-0.6)

    @pytest.mark.asyncio
    async def test_to_signal_projects_domain_vocabulary(self) -> None:
        llm = _StubLLM('{"signal": "bullish", "confidence": 85, "reasoning": "Moat."}')
        snap = await build_snapshot("AAPL", date(2026, 7, 10), _StubFundamentals(_FOUR_PERIODS))
        view = await BuffettAdvisor(llm).form_view(snap)

        observed = datetime(2026, 7, 10, 11, 30, tzinfo=UTC)
        signal = view.to_signal("sig-1", observed)
        assert signal.kind is SignalKind.ADVISOR_VIEW
        assert signal.symbol is not None and signal.symbol.ticker == "AAPL"
        assert signal.score == Decimal("0.85")
        assert signal.thesis == "Moat."
        assert signal.features["stance"] == "bullish"
        assert signal.features["advisor"] == "buffett"
        assert signal.features["snapshot_hash"] == snap.content_hash
        assert signal.observed_at == observed


class TestRegistry:
    """Every registered persona must honour the advisor contract."""

    def test_registry_keys_match_persona_names(self) -> None:
        for key, cls in ADVISOR_REGISTRY.items():
            assert cls(_StubLLM("")).name == key

    def test_every_prompt_carries_schema_and_no_lookahead_rule(self) -> None:
        for cls in ADVISOR_REGISTRY.values():
            prompt = cls(_StubLLM("")).get_system_prompt()
            assert '"signal"' in prompt and '"confidence"' in prompt
            assert "after the as-of date" in prompt  # the anti-lookahead guard

    @pytest.mark.asyncio
    async def test_every_persona_forms_a_valid_view(self) -> None:
        snap = await build_snapshot("AAPL", date(2026, 7, 10), _StubFundamentals(_FOUR_PERIODS))
        for name, cls in ADVISOR_REGISTRY.items():
            llm = _StubLLM('{"signal": "neutral", "confidence": 55, "reasoning": "Mixed."}')
            view = await cls(llm).form_view(snap)
            assert view.advisor == name
            assert view.stance == "neutral"
            assert not view.abstained


class TestExtractJson:
    def test_fenced_json(self) -> None:
        text = 'Here you go:\n```json\n{"signal": "bullish", "confidence": 80}\n```\nDone.'
        assert extract_json(text)["signal"] == "bullish"

    def test_bare_json(self) -> None:
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_embedded_balanced_object(self) -> None:
        text = 'I think {"signal": "neutral", "nested": {"x": 1}} covers it.'
        assert extract_json(text)["nested"] == {"x": 1}

    def test_no_json_raises(self) -> None:
        with pytest.raises(LLMParseError):
            extract_json("hold everything, no json here")
